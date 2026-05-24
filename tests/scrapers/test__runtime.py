"""Unit tests for the polite-request runtime (pulpo/scrapers/_runtime.py).

No network. Mocks httpx and Playwright via duck-typed stand-ins.
"""
from __future__ import annotations
import random
import sys
import time
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers import _runtime  # noqa: E402
from pulpo.scrapers._policy import Policy, get_policy, DEFAULT_POLICY  # noqa: E402


# ── UA pool ────────────────────────────────────────────────────────────


def test_pick_user_agent_returns_from_named_pool():
    ua = _runtime.pick_user_agent("safari_macos", rng=random.Random(0))
    assert ua in _runtime.UA_POOLS["safari_macos"]


def test_pick_user_agent_unknown_pool_falls_back_to_default():
    ua = _runtime.pick_user_agent("does-not-exist", rng=random.Random(0))
    assert ua in _runtime.UA_POOLS["default"]


def test_pick_user_agent_rotates_across_calls():
    seen: set[str] = set()
    r = random.Random(0)
    for _ in range(20):
        seen.add(_runtime.pick_user_agent("default", rng=r))
    # Three UAs in the default pool — across 20 picks we should see >1.
    assert len(seen) >= 2


# ── Jitter ─────────────────────────────────────────────────────────────


def test_jitter_sleep_respects_disable_env(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    secs = _runtime.jitter_sleep(DEFAULT_POLICY, rng=random.Random(0))
    assert secs == 0.0


def test_jitter_sleep_bounded_by_policy(monkeypatch):
    monkeypatch.delenv("PULPO_DISABLE_JITTER", raising=False)
    p = Policy(jitter_ms=(10, 20))
    # Patch time.sleep so the test doesn't actually pause.
    slept: list[float] = []
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: slept.append(s))
    secs = _runtime.jitter_sleep(p, rng=random.Random(0))
    assert 0.010 <= secs <= 0.020
    assert slept and 0.010 <= slept[0] <= 0.020


# ── Rate limiter ───────────────────────────────────────────────────────


def test_rate_limiter_first_acquire_no_wait(monkeypatch):
    lim = _runtime.RateLimiter(rps=1.0)
    waited = lim.acquire()
    assert waited == 0.0


def test_rate_limiter_enforces_min_interval(monkeypatch):
    """Two acquires in a row should block the second for ~min_interval."""
    lim = _runtime.RateLimiter(rps=10.0)  # 0.1s min interval

    sleeps: list[float] = []
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: sleeps.append(s))
    lim.acquire()
    lim.acquire()
    # Second acquire should have requested a small sleep (close to 0.1s).
    assert sleeps, "expected RateLimiter to sleep on back-to-back acquires"
    assert 0.0 < sleeps[0] <= 0.1


def test_rate_limiter_zero_rps_disables_throttling():
    lim = _runtime.RateLimiter(rps=0.0)
    # Two consecutive acquires must return immediately.
    assert lim.acquire() == 0.0
    assert lim.acquire() == 0.0


def test_get_limiter_returns_singleton_per_source():
    a = _runtime.get_limiter("test-source-X", Policy(rate_limit_rps=1.0))
    b = _runtime.get_limiter("test-source-X", Policy(rate_limit_rps=1.0))
    assert a is b


# ── decide_retry ───────────────────────────────────────────────────────


def test_decide_retry_exhausted_budget():
    d = _runtime.decide_retry(attempt=3, policy=Policy(retry_max=3), status_code=500)
    assert d.should_retry is False
    assert "exhausted" in d.reason


def test_decide_retry_honors_retry_after_seconds():
    d = _runtime.decide_retry(
        attempt=1, policy=Policy(retry_max=3),
        status_code=429, retry_after="12",
    )
    assert d.should_retry is True
    assert d.sleep_seconds == 12.0
    assert "retry_after" in d.reason


def test_decide_retry_caps_retry_after_at_300s():
    d = _runtime.decide_retry(
        attempt=1, policy=Policy(retry_max=3),
        status_code=429, retry_after="9999",
    )
    assert d.sleep_seconds == 300.0


def test_decide_retry_exponential_backoff_no_retry_after():
    d = _runtime.decide_retry(
        attempt=2, policy=Policy(retry_max=5, retry_backoff_base_s=2.0),
        status_code=503,
    )
    assert d.should_retry is True
    # base=2.0, attempt=2 -> 2 * 2^1 = 4.0
    assert d.sleep_seconds == 4.0


def test_decide_retry_non_retryable_4xx():
    d = _runtime.decide_retry(attempt=1, policy=Policy(retry_max=3), status_code=403)
    assert d.should_retry is False
    assert "no_retry" in d.reason


def test_decide_retry_on_exception():
    d = _runtime.decide_retry(
        attempt=1, policy=Policy(retry_max=3),
        exception=TimeoutError("boom"),
    )
    assert d.should_retry is True


# ── polite_get integration ─────────────────────────────────────────────


class _FakeResponse:
    def __init__(self, status_code: int, headers: Optional[dict] = None, text: str = ""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text


def test_polite_get_returns_2xx_on_first_try(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    p = Policy(rate_limit_rps=0.0, retry_max=3)

    client = MagicMock()
    client.get.return_value = _FakeResponse(200, text="ok")

    resp = _runtime.polite_get(client, "https://x.test/", source="testsrc", policy=p)
    assert resp.status_code == 200
    assert client.get.call_count == 1


def test_polite_get_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    p = Policy(rate_limit_rps=0.0, retry_max=3, retry_backoff_base_s=0.01)

    client = MagicMock()
    client.get.side_effect = [
        _FakeResponse(503),
        _FakeResponse(503),
        _FakeResponse(200, text="ok"),
    ]
    resp = _runtime.polite_get(client, "https://x.test/", source="testsrc2", policy=p)
    assert resp.status_code == 200
    assert client.get.call_count == 3


def test_polite_get_returns_429_after_budget(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    p = Policy(rate_limit_rps=0.0, retry_max=2, retry_backoff_base_s=0.01)

    client = MagicMock()
    client.get.return_value = _FakeResponse(429, headers={"Retry-After": "0.1"})

    resp = _runtime.polite_get(client, "https://x.test/", source="testsrc3", policy=p)
    # Budget exhausted; we let the caller see the bad response.
    assert resp.status_code == 429
    assert client.get.call_count == 2


def test_polite_get_4xx_no_retry_immediate(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    p = Policy(rate_limit_rps=0.0, retry_max=3)

    client = MagicMock()
    client.get.return_value = _FakeResponse(403)

    resp = _runtime.polite_get(client, "https://x.test/", source="testsrc4", policy=p)
    assert resp.status_code == 403
    assert client.get.call_count == 1


def test_polite_get_user_agent_rotates_per_request(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    p = Policy(rate_limit_rps=0.0, retry_max=5, retry_backoff_base_s=0.01,
               user_agent_pool="default")

    captured: list[str] = []

    def _get(url, headers=None):  # noqa: ARG001
        captured.append((headers or {}).get("User-Agent", ""))
        return _FakeResponse(503)  # force retries

    client = MagicMock()
    client.get.side_effect = _get
    # Use a deterministic rng so the test is stable.
    rng = random.Random(0)
    _runtime.polite_get(client, "https://x.test/", source="testsrc5", policy=p, rng=rng)
    # Across 5 attempts we should have at least 2 distinct UAs from the pool.
    assert len(set(captured)) >= 2
    for ua in captured:
        assert ua in _runtime.UA_POOLS["default"]
