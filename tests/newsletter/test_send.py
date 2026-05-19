"""send.py — dry-run gate, real-send happy path, retries, header / tag wiring.

Uses the `post_override` test seam to bypass httpx entirely.
"""

from __future__ import annotations

from automation.newsletter import send as send_mod


class _Resp:
    def __init__(self, status: int, body: dict | None = None, text: str = ""):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = text

    def json(self):
        return self._body


def _make_post(behaviour):
    calls = []
    def _post(url, headers=None, body=None, timeout=None):
        calls.append({"url": url, "headers": headers, "body": body, "timeout": timeout})
        return behaviour(len(calls) - 1)
    _post.calls = calls
    return _post


# ── dry-run ──────────────────────────────────────────────────────────────
def test_dry_run_default_no_http(monkeypatch):
    monkeypatch.delenv("PULPO_NEWSLETTER_DRY_RUN", raising=False)
    poster = _make_post(lambda _i: _Resp(200, {"id": "should-not-be-called"}))
    out = send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc123",
        issue_number=1,
        subject="Hi",
        html="<p>hi</p>",
        post_override=poster,
    )
    assert out.ok is True
    assert out.dry_run is True
    assert out.message_id is not None
    assert out.message_id.startswith("dry_")
    assert len(poster.calls) == 0   # no HTTP


def test_explicit_dry_run_off_makes_real_call(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mail.pulpo.club")
    monkeypatch.setenv("PULPO_UNSUBSCRIBE_SECRET", "test-secret")

    poster = _make_post(lambda _i: _Resp(200, {"id": "msg_123"}))
    out = send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc123",
        issue_number=2,
        subject="Hi",
        html="<p>hi</p>",
        post_override=poster,
    )
    assert out.ok is True
    assert out.dry_run is False
    assert out.message_id == "msg_123"
    assert len(poster.calls) == 1
    body = poster.calls[0]["body"]
    assert body["from"] == "hello@mail.pulpo.club"
    assert body["to"] == ["ops@pulpo.club"]
    assert body["subject"] == "Hi"
    assert body["html"] == "<p>hi</p>"
    # List-Unsubscribe headers must be present and reference the recipient
    assert "List-Unsubscribe" in body["headers"]
    assert "abc123" in body["headers"]["List-Unsubscribe"]
    assert body["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_missing_api_key_returns_error(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mail.pulpo.club")
    out = send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc",
        issue_number=1,
        subject="x",
        html="<p>x</p>",
        post_override=_make_post(lambda _i: _Resp(200)),
    )
    assert out.ok is False
    assert out.error == "missing_api_key"


def test_missing_from_email_returns_error(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.delenv("RESEND_FROM_EMAIL", raising=False)
    out = send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc",
        issue_number=1,
        subject="x",
        html="<p>x</p>",
        post_override=_make_post(lambda _i: _Resp(200)),
    )
    assert out.ok is False
    assert out.error == "missing_from_email"


def test_invalid_email_returns_error(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mail.pulpo.club")
    out = send_mod.send_issue(
        to_email="not-an-email",
        recipient_hash="abc",
        issue_number=1,
        subject="x",
        html="<p>x</p>",
    )
    assert out.ok is False
    assert out.error == "invalid_email"


# ── retries ──────────────────────────────────────────────────────────────
def test_retries_on_429_then_success(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mail.pulpo.club")
    monkeypatch.setattr(send_mod, "BACKOFF_SECONDS", 0)  # speed up

    poster = _make_post(lambda i: _Resp(429) if i < 1 else _Resp(200, {"id": "msg_ok"}))
    out = send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc",
        issue_number=1,
        subject="x",
        html="<p>x</p>",
        post_override=poster,
    )
    assert out.ok is True
    assert out.attempt == 2
    assert len(poster.calls) == 2


def test_retries_on_5xx_then_fail(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mail.pulpo.club")
    monkeypatch.setattr(send_mod, "BACKOFF_SECONDS", 0)

    poster = _make_post(lambda _i: _Resp(503, text="upstream down"))
    out = send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc",
        issue_number=1,
        subject="x",
        html="<p>x</p>",
        post_override=poster,
    )
    assert out.ok is False
    assert out.error == "http_503"
    assert out.attempt == send_mod.MAX_ATTEMPTS  # exhausted


def test_4xx_other_than_429_does_not_retry(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mail.pulpo.club")
    poster = _make_post(lambda _i: _Resp(422, text="invalid_from_email"))
    out = send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc",
        issue_number=1,
        subject="x",
        html="<p>x</p>",
        post_override=poster,
    )
    assert out.ok is False
    assert out.error == "http_422"
    assert out.attempt == 1   # no retry on 4xx (other than 429)
    assert len(poster.calls) == 1


def test_network_exception_retries_then_fails(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mail.pulpo.club")
    monkeypatch.setattr(send_mod, "BACKOFF_SECONDS", 0)

    def _post(url, headers=None, body=None, timeout=None):
        raise ConnectionError("dns lookup failed")
    out = send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc",
        issue_number=1,
        subject="x",
        html="<p>x</p>",
        post_override=_post,
    )
    assert out.ok is False
    assert out.error == "ConnectionError"
    assert out.attempt == send_mod.MAX_ATTEMPTS


# ── unsubscribe token ────────────────────────────────────────────────────
def test_unsubscribe_token_deterministic():
    a = send_mod.unsubscribe_token("abc", 1, "secret")
    b = send_mod.unsubscribe_token("abc", 1, "secret")
    c = send_mod.unsubscribe_token("abc", 2, "secret")
    d = send_mod.unsubscribe_token("xyz", 1, "secret")
    e = send_mod.unsubscribe_token("abc", 1, "other-secret")
    assert a == b
    assert a != c
    assert a != d
    assert a != e
    assert len(a) == 32


def test_list_unsubscribe_headers(monkeypatch):
    monkeypatch.setenv("PULPO_UNSUBSCRIBE_SECRET", "test-secret")
    headers = send_mod.list_unsubscribe_headers("abc", 1)
    assert "List-Unsubscribe" in headers
    assert headers["List-Unsubscribe"].startswith("<https://")
    assert "?r=abc&i=1&t=" in headers["List-Unsubscribe"]
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


# ── tags + html_to_text ──────────────────────────────────────────────────
def test_tags_get_sanitised(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("RESEND_FROM_EMAIL", "hello@mail.pulpo.club")
    poster = _make_post(lambda _i: _Resp(200, {"id": "ok"}))
    send_mod.send_issue(
        to_email="ops@pulpo.club",
        recipient_hash="abc",
        issue_number=1,
        subject="x",
        html="<p>x</p>",
        tags={"cohort": "pro_prefs", "locale": "en", "weird:key": "ok"},
        post_override=poster,
    )
    tags = poster.calls[0]["body"]["tags"]
    names = [t["name"] for t in tags]
    # Resend tag names must be ASCII letters/digits/underscore/dash
    assert "weird_key" in names
    assert "cohort" in names


def test_html_to_text_strips_style_and_blocks():
    html = "<style>body { color: red; }</style><p>Hello <b>world</b>.</p><p>Next.</p>"
    text = send_mod.html_to_text(html)
    assert "Hello world." in text
    assert "Next." in text
    assert "color: red" not in text
    assert "<" not in text and ">" not in text


def test_is_dry_run_explicit_off(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "0")
    assert send_mod.is_dry_run() is False
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "false")
    assert send_mod.is_dry_run() is False
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "no")
    assert send_mod.is_dry_run() is False
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "1")
    assert send_mod.is_dry_run() is True
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "")
    assert send_mod.is_dry_run() is True   # missing/empty defaults to dry-run
