"""Tests for the thin GH-Actions poll wrapper at
scripts/poll_webhook_health_endpoint.py.

The script's contract is "if the Vercel cron returned a non-ok
provider status, exit non-zero; if the endpoint itself is unreachable
or returns non-2xx, post Slack and exit non-zero". Everything else
keeps the workflow green so the Vercel-side Slack lines aren't
double-fired by the GH workflow.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import poll_webhook_health_endpoint as poll  # noqa: E402


def _ok_response(payload: dict):
    """Build a MagicMock matching urllib's response interface."""
    body = json.dumps(payload).encode("utf-8")
    res = MagicMock()
    res.read.return_value = body
    res.__enter__ = lambda self: self
    res.__exit__ = lambda self, *_args: None
    return res


def _no_token(monkeypatch):
    """Unset both so the misconfig path runs without touching the network."""
    monkeypatch.delenv("PULPO_CRON_SECRET", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)


def test_exits_one_when_token_missing(monkeypatch, capsys):
    _no_token(monkeypatch)
    rc = poll.main()
    assert rc == 1
    assert "PULPO_CRON_SECRET" in capsys.readouterr().err


# --- misconfiguration must be loud AND distinguishable from an outage ---
#
# Regression guard (2026-08-09): this branch used to `return 1` with no
# Slack post, so the only alert was the workflow's generic "JOB FAILED —
# monitor may be silent", which never named the cause. The poller then
# ran 100 consecutive failing runs (at least 2026-07-15 → 2026-08-09,
# ~25 days) with Clerk/Resend liveness entirely unmonitored, because
# every page looked identical and unactionable.
#
# The bug class is NOT "the secret is missing" — that's an ops fact that
# changes. It's a misconfigured monitor being indistinguishable from a
# real outage: both exit 1 and go red, and only the message tells them
# apart. So these assert on the message, not the exit code.


def test_missing_token_pages_slack(monkeypatch):
    """The silent branch is the actual bug."""
    _no_token(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(poll, "post_slack", lambda url, text: sent.append(text))
    poll.main()
    assert len(sent) == 1, "misconfiguration must page, not fail silently"


def test_missing_token_message_is_actionable(monkeypatch, capsys):
    """Naming the secret + remediation is what makes the page actionable."""
    _no_token(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(poll, "post_slack", lambda url, text: sent.append(text))
    poll.main()
    blob = sent[0] + capsys.readouterr().err
    assert "PULPO_CRON_SECRET" in blob, "the alert must name the missing secret"
    assert "Vercel" in blob, "the alert must carry the remediation"


def test_missing_token_not_reported_as_outage(monkeypatch):
    """A misconfigured monitor must never read as 'the webhooks are down'."""
    _no_token(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr(poll, "post_slack", lambda url, text: sent.append(text))
    poll.main()
    assert "misconfigur" in sent[0].lower()
    assert "not a webhook outage" in sent[0].lower()


def test_missing_token_emits_github_annotation(monkeypatch, capsys):
    """Surfaces the cause on the run summary, not a collapsed step log."""
    _no_token(monkeypatch)
    monkeypatch.setattr(poll, "post_slack", lambda url, text: None)
    poll.main()
    assert "::error title=" in capsys.readouterr().out


def test_green_when_both_providers_ok(monkeypatch):
    monkeypatch.setenv("PULPO_CRON_SECRET", "secret")
    monkeypatch.setenv("PULPO_HEALTH_URL", "https://pulpo.club/api/cron/webhook-health")
    with patch("urllib.request.urlopen", return_value=_ok_response({
        "clerk": {"status": "ok"},
        "resend": {"status": "ok"},
        "heartbeat_at": "2026-06-03T00:00:00+00:00",
        "elapsed_ms": 123,
    })):
        assert poll.main() == 0


def test_green_when_provider_degraded(monkeypatch):
    """`degraded` (stuck invitations / domain issues) keeps the
    workflow green; the Vercel function already posted to Slack."""
    monkeypatch.setenv("PULPO_CRON_SECRET", "secret")
    with patch("urllib.request.urlopen", return_value=_ok_response({
        "clerk": {"status": "degraded", "stuck_count": 1},
        "resend": {"status": "ok"},
    })):
        assert poll.main() == 0


def test_red_when_provider_unavailable(monkeypatch):
    """`unavailable` means the provider blocked the call OR the Vercel
    function uncaught-excepted. Surface as a red workflow badge."""
    monkeypatch.setenv("PULPO_CRON_SECRET", "secret")
    with patch("urllib.request.urlopen", return_value=_ok_response({
        "clerk": {"status": "unavailable", "reason": "clerk_403"},
        "resend": {"status": "ok"},
    })):
        assert poll.main() == 1


def test_slack_fires_on_http_error(monkeypatch):
    """Vercel function down → Slack the explicit URL so oncall can pin
    the runtime that's misbehaving."""
    monkeypatch.setenv("PULPO_CRON_SECRET", "secret")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/x")
    monkeypatch.setenv("PULPO_HEALTH_URL", "https://pulpo.club/api/cron/webhook-health")

    import urllib.error
    err = urllib.error.HTTPError(
        url="https://pulpo.club/api/cron/webhook-health",
        code=502, msg="Bad Gateway", hdrs={},  # type: ignore[arg-type]
        fp=io.BytesIO(b"upstream timeout"),
    )

    slack_calls: list = []

    def fake_open(req, timeout=None):
        # First call (GET endpoint) raises; second call (POST to Slack)
        # we capture.
        if req.get_method() == "GET":
            raise err
        slack_calls.append(req.get_full_url())
        return MagicMock()

    with patch("urllib.request.urlopen", side_effect=fake_open):
        rc = poll.main()

    assert rc == 1
    assert "hooks.slack.test" in (slack_calls[0] if slack_calls else "")
