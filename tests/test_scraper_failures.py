"""Unit tests for automation/scraper_failures.py — the Phase-1 diagnostic-
capture helper."""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation import scraper_failures  # noqa: E402


@pytest.fixture
def _tmp_failures_dir(tmp_path, monkeypatch):
    """Redirect the FAILURES_DIR for the duration of a test."""
    target = tmp_path / "scraper_failures"
    monkeypatch.setattr(scraper_failures, "FAILURES_DIR", target)
    return target


class _FakeHttpxResponse:
    def __init__(self, status_code=403, headers=None, text="<html>blocked</html>"):
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/html"}
        self.text = text


# ── happy-path: exception snapshot ─────────────────────────────────────


def test_write_snapshot_for_exception_succeeds(_tmp_failures_dir):
    try:
        raise RuntimeError("scraper exploded")
    except RuntimeError as exc:
        fid = scraper_failures.write_failure_snapshot(
            "testsrc",
            kind="exception",
            exception=exc,
            response=_FakeHttpxResponse(),
            request_url="https://api.test/listings",
            request_headers={"User-Agent": "ua-x", "Authorization": "secret-token"},
            context={"duration_s": 1.5},
        )
    assert fid is not None
    files = list(_tmp_failures_dir.glob("testsrc_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text())
    assert data["failure_id"] == fid
    assert data["source"] == "testsrc"
    assert data["kind"] == "exception"
    assert data["exception"]["class"] == "RuntimeError"
    assert "scraper exploded" in data["exception"]["repr"]
    assert data["response"]["status_code"] == 403
    assert data["request"]["url"] == "https://api.test/listings"
    assert data["context"]["duration_s"] == 1.5


# ── auth redaction ─────────────────────────────────────────────────────


def test_authorization_and_cookie_headers_are_redacted(_tmp_failures_dir):
    fid = scraper_failures.write_failure_snapshot(
        "testsrc",
        kind="exception",
        exception=Exception("err"),
        request_url="https://x.test/",
        request_headers={
            "Authorization": "Bearer SECRET",
            "Cookie":        "session=SECRET",
            "X-API-Key":     "SECRET",
            "User-Agent":    "polite/1.0",
        },
    )
    assert fid is not None
    files = list(_tmp_failures_dir.glob("testsrc_*.json"))
    data = json.loads(files[0].read_text())
    headers = data["request"]["headers"]
    assert headers["Authorization"] == "<redacted>"
    assert headers["Cookie"] == "<redacted>"
    assert headers["X-API-Key"] == "<redacted>"
    assert headers["User-Agent"] == "polite/1.0"


# ── body-snippet capping ───────────────────────────────────────────────


def test_response_body_snippet_capped(_tmp_failures_dir):
    big = "A" * 20_000
    fid = scraper_failures.write_failure_snapshot(
        "testsrc",
        kind="exception",
        exception=Exception("err"),
        response=_FakeHttpxResponse(text=big),
    )
    assert fid is not None
    files = list(_tmp_failures_dir.glob("testsrc_*.json"))
    data = json.loads(files[0].read_text())
    assert len(data["response"]["body_snippet"]) == scraper_failures.BODY_SNIPPET_BYTES


# ── empty_yield kind ───────────────────────────────────────────────────


def test_empty_yield_kind_writes_minimal_snapshot(_tmp_failures_dir):
    fid = scraper_failures.write_failure_snapshot(
        "testsrc",
        kind="empty_yield",
        context={"duration_s": 0.5, "max_pages_hit": False, "limit_hit": False},
    )
    assert fid is not None
    files = list(_tmp_failures_dir.glob("testsrc_*.json"))
    data = json.loads(files[0].read_text())
    assert data["kind"] == "empty_yield"
    assert data["exception"] is None
    assert data["response"] is None
    assert data["context"]["duration_s"] == 0.5


# ── retention pruning ──────────────────────────────────────────────────


def test_retention_prunes_old_snapshots(_tmp_failures_dir, monkeypatch):
    """RETAIN_PER_SOURCE bounds disk growth."""
    monkeypatch.setattr(scraper_failures, "RETAIN_PER_SOURCE", 3)
    for i in range(6):
        scraper_failures.write_failure_snapshot(
            "noisy",
            kind="empty_yield",
            ts=f"2026-05-{i + 1:02d}T06:00:00+00:00",
        )
    files = sorted(_tmp_failures_dir.glob("noisy_*.json"))
    # We wrote 6 but retention=3, so only 3 survive.
    assert len(files) == 3


# ── never raises on bad input ──────────────────────────────────────────


def test_unserializable_context_does_not_raise(_tmp_failures_dir):
    class _NotSerializable:
        def __repr__(self):
            raise RuntimeError("cursed __repr__")

    # The function must absorb this and return None or a failure_id —
    # never propagate the cursed exception.
    try:
        fid = scraper_failures.write_failure_snapshot(
            "testsrc",
            kind="exception",
            exception=Exception("err"),
            context={"bad": _NotSerializable()},
        )
    except Exception as e:
        pytest.fail(f"telemetry helper raised: {e!r}")
    # fid may be None (serialization failed) — that's acceptable.
    assert fid is None or isinstance(fid, str)


# ── is_enabled escape hatch ────────────────────────────────────────────


def test_is_enabled_default_true(monkeypatch):
    monkeypatch.delenv("PULPO_DISABLE_FAILURE_CAPTURE", raising=False)
    assert scraper_failures.is_enabled() is True


def test_is_enabled_false_when_env_set(monkeypatch):
    monkeypatch.setenv("PULPO_DISABLE_FAILURE_CAPTURE", "1")
    assert scraper_failures.is_enabled() is False
