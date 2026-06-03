"""Tests for the Vercel Python serverless handler at
api/cron/webhook-health.py.

The handler routes around the Cloudflare 1010 block (PRD P0-1/P0-2) by
running provider-API checks from the Vercel runtime. Tests cover the
pure helpers `_check_clerk` and `_check_resend` directly — the
`BaseHTTPRequestHandler` interface is hard to mock cleanly and the
authn / response-shape paths are exercised end-to-end via the GH
poller in `tests/scripts/test_poll_webhook_health_endpoint.py`.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

# The Vercel module is named `webhook-health.py` (Vercel route names use
# hyphens), so a regular `import` doesn't work — load it by path.
_module_path = REPO / "api" / "cron" / "webhook-health.py"
_spec = importlib.util.spec_from_file_location("webhook_health", _module_path)
assert _spec is not None and _spec.loader is not None
wh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wh)


# The handler now inlines HTTPCallError so Vercel can bundle it
# without needing to trace `automation.monitors`. Use the handler's
# local class so synthetic errors match its `except` clause.
HTTPCallError = wh.HTTPCallError


# ── _check_clerk ────────────────────────────────────────────────────


def test_check_clerk_unavailable_when_secret_missing(monkeypatch):
    monkeypatch.delenv("CLERK_SECRET_KEY", raising=False)
    out = wh._check_clerk()
    assert out["status"] == "unavailable"
    assert out["reason"] == "missing_secret"


def test_check_clerk_status_ok_on_zero_stuck(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test")
    # Invitation older than 6h means it's stuck; this one is fresh, so
    # the status should remain "ok".
    fresh_created = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
    ).isoformat()
    with patch.object(wh, "request_json", return_value={
        "data": [
            {"id": "inv_1", "created_at": fresh_created},
        ],
    }):
        out = wh._check_clerk()
    assert out["status"] == "ok"
    assert out["stuck_count"] == 0
    assert out["pending_invitations"] == 1


def test_check_clerk_status_degraded_on_stuck(monkeypatch):
    """Threshold defaults to 6h; rows older than that are stuck."""
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test")
    old_created = (
        dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    ).isoformat()
    with patch.object(wh, "request_json", return_value={
        "data": [
            {"id": "inv_old", "created_at": old_created},
        ],
    }):
        out = wh._check_clerk()
    assert out["status"] == "degraded"
    assert out["stuck_count"] == 1
    assert out["threshold_hours"] == 6.0


def test_check_clerk_translates_403_to_unavailable(monkeypatch):
    """Cloudflare 1010 / API forbidden lands as `unavailable` so the
    heartbeat dashboard catches the regression — not silent."""
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test")
    err = HTTPCallError(
        "GET", "https://api.clerk.com/v1/invitations", 403,
        "error code: 1010",
    )
    with patch.object(wh, "request_json", side_effect=err):
        out = wh._check_clerk()
    assert out["status"] == "unavailable"
    assert out["reason"] == "clerk_403"
    assert "1010" in out["detail"]


# ── _check_resend ───────────────────────────────────────────────────


def test_check_resend_unavailable_when_secret_missing(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    out = wh._check_resend()
    assert out["status"] == "unavailable"
    assert out["reason"] == "missing_secret"


def test_check_resend_status_ok_when_all_verified(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.delenv("PULPO_ACTIVATION_FROM_EMAIL", raising=False)
    monkeypatch.delenv("RESEND_FROM_NOREPLY", raising=False)
    with patch.object(wh, "request_json", return_value={
        "data": [{
            "name": "mail.pulpo.club",
            "status": "verified",
            "records": [{"type": "TXT", "status": "verified"}],
        }],
    }):
        out = wh._check_resend()
    assert out["status"] == "ok"
    assert out["issue_count"] == 0


def test_check_resend_flags_unverified_dns(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.delenv("PULPO_ACTIVATION_FROM_EMAIL", raising=False)
    monkeypatch.delenv("RESEND_FROM_NOREPLY", raising=False)
    with patch.object(wh, "request_json", return_value={
        "data": [{
            "name": "mail.pulpo.club",
            "status": "verified",
            "records": [{"type": "DKIM", "status": "pending"}],
        }],
    }):
        out = wh._check_resend()
    assert out["status"] == "degraded"
    assert out["issue_count"] == 1
    assert any("DKIM" in i for i in out["issues"])


def test_check_resend_flags_noreply_activation_sender(monkeypatch):
    """Activation mail from noreply@ gets a soft warning — keeps the
    deliverability check truthful even when all DNS is green."""
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv(
        "PULPO_ACTIVATION_FROM_EMAIL",
        "Pulpo <noreply@mail.pulpo.club>",
    )
    monkeypatch.delenv("RESEND_FROM_NOREPLY", raising=False)
    with patch.object(wh, "request_json", return_value={"data": []}):
        out = wh._check_resend()
    assert out["status"] == "degraded"
    assert any("noreply" in i for i in out["issues"])


def test_check_resend_translates_403_to_unavailable(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    err = HTTPCallError(
        "GET", "https://api.resend.com/domains", 403,
        "error code: 1010",
    )
    with patch.object(wh, "request_json", side_effect=err):
        out = wh._check_resend()
    assert out["status"] == "unavailable"
    assert out["reason"] == "resend_403"
