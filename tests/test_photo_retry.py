"""
Pins the bounded-retry contract on automation.run._fetch_photo_with_retry
(image-pipeline audit 2026-07-29, PR-C).

Contract:
- transient failures (transport errors / timeouts / HTTP 5xx) get exactly
  one retry, then raise;
- non-transient HTTP 4xx raises immediately (retrying a dead broker URL
  burns budget for nothing);
- a success after a transient failure returns the response.

httpx.get is monkeypatched — no network. backoff is passed as 0 to keep
the suite fast; the default (1.5s) only matters in production.
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.run import _fetch_photo_with_retry  # noqa: E402

TIMEOUT = httpx.Timeout(5.0, connect=5.0, read=5.0, write=5.0, pool=5.0)


class _FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code
        self.content = b"ok-bytes"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://x"),
                response=self,  # type: ignore[arg-type]
            )


def _sequenced_get(monkeypatch, outcomes):
    """Patch httpx.get to pop one outcome per call. An outcome is either
    an exception instance (raised) or an int status (returned)."""
    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _FakeResponse(outcome)

    monkeypatch.setattr(httpx, "get", fake_get)
    return calls


def test_success_first_try(monkeypatch):
    calls = _sequenced_get(monkeypatch, [200])
    r = _fetch_photo_with_retry("http://x/a.jpg", timeout=TIMEOUT, backoff_s=0)
    assert r.content == b"ok-bytes"
    assert len(calls) == 1


def test_transient_timeout_then_success(monkeypatch):
    calls = _sequenced_get(
        monkeypatch, [httpx.ReadTimeout("dribble"), 200]
    )
    r = _fetch_photo_with_retry("http://x/a.jpg", timeout=TIMEOUT, backoff_s=0)
    assert r.content == b"ok-bytes"
    assert len(calls) == 2


def test_http_5xx_then_success(monkeypatch):
    calls = _sequenced_get(monkeypatch, [503, 200])
    r = _fetch_photo_with_retry("http://x/a.jpg", timeout=TIMEOUT, backoff_s=0)
    assert r.status_code == 200
    assert len(calls) == 2


def test_http_4xx_raises_immediately(monkeypatch):
    calls = _sequenced_get(monkeypatch, [404, 200])
    with pytest.raises(httpx.HTTPStatusError):
        _fetch_photo_with_retry("http://x/a.jpg", timeout=TIMEOUT, backoff_s=0)
    assert len(calls) == 1  # no second attempt on a dead URL


def test_retry_is_bounded(monkeypatch):
    calls = _sequenced_get(
        monkeypatch,
        [httpx.ConnectError("down"), httpx.ConnectError("still down"), 200],
    )
    with pytest.raises(httpx.ConnectError):
        _fetch_photo_with_retry("http://x/a.jpg", timeout=TIMEOUT, backoff_s=0)
    assert len(calls) == 2  # 1 attempt + exactly 1 retry, never a third


def test_non_transport_error_propagates(monkeypatch):
    calls = _sequenced_get(monkeypatch, [ValueError("boom"), 200])
    with pytest.raises(ValueError):
        _fetch_photo_with_retry("http://x/a.jpg", timeout=TIMEOUT, backoff_s=0)
    assert len(calls) == 1
