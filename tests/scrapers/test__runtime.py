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


# ── polite_curl_cffi_get — TLS-impersonating transport ─────────────────
#
# These tests mock the lazy-imported ``curl_cffi.requests`` module so
# they run without the C-extension installed. The rate-limit / jitter /
# retry contract is the same as polite_get, so the asserts mirror the
# httpx-transport tests above.


class _FakeCurlCffiResponse:
    def __init__(self, status_code: int, *, headers=None, text: str = "", url: str = ""):
        self.status_code = status_code
        self.headers = headers or {}
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url


def _install_fake_curl_cffi(monkeypatch, side_effect):
    """Replace the lazy-imported curl_cffi.requests with a fake module.

    ``side_effect`` is forwarded to ``MagicMock.side_effect`` so tests
    can return a sequence of responses or raise exceptions deterministic-
    ally without hitting the network.
    """
    fake_requests = MagicMock()
    fake_requests.get = MagicMock(side_effect=side_effect)
    monkeypatch.setattr(_runtime, "_curl_requests", fake_requests)
    return fake_requests


def test_polite_curl_cffi_get_returns_2xx_on_first_try(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    p = Policy(transport="curl_cffi", rate_limit_rps=0.0, retry_max=3)
    fake = _install_fake_curl_cffi(monkeypatch, [_FakeCurlCffiResponse(200, text="ok")])

    resp = _runtime.polite_curl_cffi_get("https://x.test/", source="cffisrc1", policy=p)
    assert resp.status_code == 200
    assert resp.text == "ok"
    assert fake.get.call_count == 1
    # The Chrome impersonation profile must be passed to curl_cffi.
    assert fake.get.call_args.kwargs["impersonate"] == p.curl_cffi_impersonate


def test_polite_curl_cffi_get_retries_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    p = Policy(transport="curl_cffi", rate_limit_rps=0.0, retry_max=3,
               retry_backoff_base_s=0.01)
    fake = _install_fake_curl_cffi(monkeypatch, [
        _FakeCurlCffiResponse(503),
        _FakeCurlCffiResponse(503),
        _FakeCurlCffiResponse(200, text="ok"),
    ])

    resp = _runtime.polite_curl_cffi_get("https://x.test/", source="cffisrc2", policy=p)
    assert resp.status_code == 200
    assert fake.get.call_count == 3


def test_polite_curl_cffi_get_returns_429_after_budget(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    monkeypatch.setattr(_runtime.time, "sleep", lambda s: None)
    p = Policy(transport="curl_cffi", rate_limit_rps=0.0, retry_max=2,
               retry_backoff_base_s=0.01)
    _install_fake_curl_cffi(monkeypatch, [
        _FakeCurlCffiResponse(429, headers={"Retry-After": "0.1"}),
        _FakeCurlCffiResponse(429, headers={"Retry-After": "0.1"}),
    ])

    resp = _runtime.polite_curl_cffi_get("https://x.test/", source="cffisrc3", policy=p)
    assert resp.status_code == 429


def test_polite_curl_cffi_get_403_no_retry(monkeypatch):
    """403 is the canonical WAF reject — return immediately, no retries."""
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    p = Policy(transport="curl_cffi", rate_limit_rps=0.0, retry_max=3)
    fake = _install_fake_curl_cffi(monkeypatch, [_FakeCurlCffiResponse(403)])

    resp = _runtime.polite_curl_cffi_get("https://x.test/", source="cffisrc4", policy=p)
    assert resp.status_code == 403
    assert fake.get.call_count == 1


def test_polite_curl_cffi_get_raises_for_status_on_4xx(monkeypatch):
    """The _PoliteResponse facade must raise like httpx on 4xx/5xx."""
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    p = Policy(transport="curl_cffi", rate_limit_rps=0.0, retry_max=1)
    _install_fake_curl_cffi(monkeypatch, [_FakeCurlCffiResponse(404)])

    resp = _runtime.polite_curl_cffi_get("https://x.test/", source="cffisrc5", policy=p)
    with pytest.raises(_runtime._PoliteHTTPError):
        resp.raise_for_status()


def test_polite_curl_cffi_get_rejects_wrong_transport_policy(monkeypatch):
    """Calling polite_curl_cffi_get for an httpx source is a programmer
    error and should be caught loudly — not produce silent 0-record runs."""
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    p = Policy(transport="httpx")
    with pytest.raises(RuntimeError, match="curl_cffi"):
        _runtime.polite_curl_cffi_get("https://x.test/", source="cffisrc6", policy=p)


def test_polite_get_for_dispatches_to_curl_cffi_for_curl_policy(monkeypatch):
    """polite_get_for must dispatch transport based on the source's policy.

    This is the single seam that lets a one-line policy change in
    _policy.py flip an existing scraper from httpx to curl_cffi without
    touching its call sites.
    """
    monkeypatch.setenv("PULPO_DISABLE_JITTER", "1")
    from pulpo.scrapers import _base, _policy

    monkeypatch.setitem(
        _policy.POLICIES,
        "dispatch_test_src",
        Policy(transport="curl_cffi", rate_limit_rps=0.0, retry_max=1),
    )
    fake = _install_fake_curl_cffi(monkeypatch, [_FakeCurlCffiResponse(200, text="ok")])

    get = _base.polite_get_for("dispatch_test_src")
    # The httpx client argument must be ignored on the curl_cffi path.
    resp = get(client=None, url="https://x.test/")
    assert resp.status_code == 200
    assert fake.get.call_count == 1


# ── browser-realistic headers (Port A from events-discovery) ───────────


def test_browser_realistic_headers_includes_user_agent():
    ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 "\
         "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    h = _runtime.browser_realistic_headers(ua)
    assert h["User-Agent"] == ua


def test_browser_realistic_headers_includes_sec_fetch_family():
    """Sec-Fetch-* are the cheapest unlock for Cloudflare fingerprint
    gates — they MUST always be present regardless of UA family."""
    h = _runtime.browser_realistic_headers("Mozilla/5.0 (any)")
    assert h["Sec-Fetch-Site"] == "none"
    assert h["Sec-Fetch-Mode"] == "navigate"
    assert h["Sec-Fetch-User"] == "?1"
    assert h["Sec-Fetch-Dest"] == "document"


def test_browser_realistic_headers_includes_sv_accept_language():
    """es-SV locale is a meaningful signal to local broker WAFs — the
    default Pulpo locale should look like a Salvadoran reader, not a
    Dutch tourist (events-discovery ships nl-NL; we mirror with es-SV)."""
    h = _runtime.browser_realistic_headers("Mozilla/5.0 (any)")
    assert h["Accept-Language"].startswith("es-SV")


def test_browser_realistic_headers_emits_chrome_client_hints_for_chrome_ua():
    """Chrome UA → Sec-CH-UA family should appear with the matching
    major version. Pins the UA-to-hints binding so a UA pool refresh
    doesn't silently drift to wrong client hints."""
    chrome_ua = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
    )
    h = _runtime.browser_realistic_headers(chrome_ua)
    assert "sec-ch-ua" in h
    assert "121" in h["sec-ch-ua"]
    assert h["sec-ch-ua-mobile"] == "?0"
    assert h["sec-ch-ua-platform"] == '"Windows"'


def test_browser_realistic_headers_omits_client_hints_for_safari_ua():
    """Safari does not send Sec-CH-UA. Emitting them on a Safari UA
    would make the request MORE suspicious, not less — missing the
    headers is part of the realistic fingerprint."""
    safari_ua = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_2) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    )
    h = _runtime.browser_realistic_headers(safari_ua)
    assert "sec-ch-ua" not in h
    assert "sec-ch-ua-mobile" not in h
    assert "sec-ch-ua-platform" not in h


def test_browser_realistic_headers_handles_chrome_on_macos_and_linux():
    """Platform string must match the UA's OS — not always 'Windows'."""
    for ua_os, expected in [
        ("Windows NT 10.0; Win64; x64", '"Windows"'),
        ("Macintosh; Intel Mac OS X 14_2", '"macOS"'),
        ("X11; Linux x86_64", '"Linux"'),
    ]:
        ua = (
            f"Mozilla/5.0 ({ua_os}) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )
        h = _runtime.browser_realistic_headers(ua)
        assert h["sec-ch-ua-platform"] == expected, f"{ua_os} → {h.get('sec-ch-ua-platform')}"


def test_browser_realistic_headers_safe_on_empty_ua():
    """Defensive: an empty UA must NOT raise — at worst we emit a
    minimal set so the surrounding polite_get keeps working."""
    h = _runtime.browser_realistic_headers("")
    assert isinstance(h, dict)
    # Sec-Fetch-* are universal so they still appear
    assert "Sec-Fetch-Dest" in h
    # No client hints for a UA that isn't recognizably Chrome
    assert "sec-ch-ua" not in h
