"""Free welcome / welcome-back dispatch contract.

DB-free, Clerk-free, dry-run by default. Idempotency is the caller's
`is_new_contact` flag (new Resend contact → welcome once).
"""

from __future__ import annotations

import json

import pytest

from automation.newsletter.free_welcome_dispatch import dispatch_free_welcome


@pytest.fixture
def ranked_file(tmp_path, ranked_pool):
    """_load_ranked reads a JSON path off disk — materialize the fixture."""
    p = tmp_path / "ranked.json"
    p.write_text(json.dumps(ranked_pool))
    return str(p)


def test_new_contact_sends_dry_run(ranked_file, monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "1")
    r = dispatch_free_welcome(email="newbie@example.com", locale="en",
                              ranked_path=ranked_file, is_new_contact=True,
                              source="signup")
    assert r.status == "sent"
    assert r.dry_run is True
    assert r.recipient_hash and r.recipient_hash != "newbie@example.com"  # hashed


def test_returning_contact_skips(ranked_file, monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "1")
    r = dispatch_free_welcome(email="dup@example.com", ranked_path=ranked_file,
                              is_new_contact=False)
    assert r.status == "skipped"
    assert r.reason == "already_subscribed"


def test_force_overrides_idempotency(ranked_file, monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "1")
    r = dispatch_free_welcome(email="me@example.com", ranked_path=ranked_file,
                              is_new_contact=False, force=True, source="admin")
    assert r.status == "sent"


def test_ranked_missing_skips(monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "1")
    r = dispatch_free_welcome(email="x@example.com",
                              ranked_path="/nonexistent/ranked.json",
                              is_new_contact=True)
    assert r.status == "skipped"
    assert r.reason == "ranked_missing"


def test_unknown_variant_falls_back_to_welcome(ranked_file, monkeypatch):
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "1")
    r = dispatch_free_welcome(email="v@example.com", variant="garbage",
                              ranked_path=ranked_file, is_new_contact=True)
    assert r.status == "sent"


def test_capture_events_fire(ranked_file, monkeypatch):
    """The sent path fires newsletter.free_welcome_sent; welcome-back fires
    the _back event. Capture the telemetry to prove the funnel is wired."""
    events = []
    monkeypatch.setenv("PULPO_NEWSLETTER_DRY_RUN", "1")
    monkeypatch.setattr("automation.newsletter.free_welcome_dispatch._capture",
                        lambda ev, props: events.append(ev))
    dispatch_free_welcome(email="a@example.com", ranked_path=ranked_file,
                          is_new_contact=True)
    dispatch_free_welcome(email="b@example.com", variant="free_welcome_back",
                          ranked_path=ranked_file, is_new_contact=True)
    assert "newsletter.free_welcome_sent" in events
    assert "newsletter.free_welcome_back_sent" in events
