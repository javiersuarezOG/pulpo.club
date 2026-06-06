"""Exact-match guard for `find_clerk_user_by_email`.

The Clerk `/users?email_address[]=…` filter was observed returning the
first user (NOT a real match) for a non-existent address. Because the
dispatcher then sends a welcome to whatever `email` was passed, that let
a bogus address (e.g. a fake test email) receive a real send — a spam /
Resend-reputation vector, made worse by the ungated /admin test-send.

These tests pin the defensive contract: the lookup only returns a user
whose email EXACTLY equals the queried address. Anything else → None →
the dispatcher's clerk_lookup_failed branch → no send.
"""

from __future__ import annotations

import pytest

from automation.newsletter import welcome_dispatch as wd


class _FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _clerk_row(email: str, uid: str = "user_real"):
    """Minimal Clerk /users row shape the parser reads."""
    return {
        "id": uid,
        "first_name": "Javier",
        "last_name": None,
        "email_addresses": [
            {"id": "idn_1", "email_address": email}
        ],
        "primary_email_address_id": "idn_1",
        "public_metadata": {"plan": "pro"},
    }


@pytest.fixture(autouse=True)
def _clerk_secret(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_dummy")


def _patch_httpx(monkeypatch, payload, captured):
    import httpx  # noqa: PLC0415

    def _fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx, "get", _fake_get)


def test_exact_match_returns_user(monkeypatch):
    """Clerk returns the user we asked for → lookup resolves it."""
    captured = {}
    payload = {"data": [_clerk_row("javier@suarez.ventures")]}
    _patch_httpx(monkeypatch, payload, captured)

    user = wd.find_clerk_user_by_email("javier@suarez.ventures")
    assert user is not None
    assert user.email == "javier@suarez.ventures"
    assert user.id == "user_real"


def test_mismatched_email_is_rejected(monkeypatch):
    """THE BUG: Clerk's filter returns the first user (a DIFFERENT email)
    for a bogus query → the guard rejects it so no welcome is sent to the
    bogus address."""
    captured = {}
    # Queried a fake address; Clerk handed back a real, unrelated user.
    payload = {"data": [_clerk_row("someone-else@real.user")]}
    _patch_httpx(monkeypatch, payload, captured)

    user = wd.find_clerk_user_by_email("diagnostic-fake@nonexistent.invalid")
    assert user is None


def test_case_insensitive_match(monkeypatch):
    """Clerk row casing differs from the query → still a real match."""
    captured = {}
    payload = {"data": [_clerk_row("Javier@Suarez.Ventures")]}
    _patch_httpx(monkeypatch, payload, captured)

    user = wd.find_clerk_user_by_email("javier@suarez.ventures")
    assert user is not None
    assert user.email.lower() == "javier@suarez.ventures"


def test_empty_result_returns_none(monkeypatch):
    captured = {}
    _patch_httpx(monkeypatch, {"data": []}, captured)
    assert wd.find_clerk_user_by_email("nobody@test.local") is None


def test_email_is_url_encoded(monkeypatch):
    """The email value goes into the query string percent-encoded so
    special characters can't break the filter."""
    captured = {}
    payload = {"data": [_clerk_row("a+b@test.local")]}
    _patch_httpx(monkeypatch, payload, captured)

    wd.find_clerk_user_by_email("a+b@test.local")
    # '+' and '@' must be encoded in the emitted URL.
    assert "a%2Bb%40test.local" in captured["url"]
    assert "a+b@test.local" not in captured["url"]
