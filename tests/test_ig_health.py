"""The IG health canary detects real trouble, SUPPRESSES false alarms while
the feed is intentionally paused, and NEVER blocks (exit 0). Offline."""
from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta, timezone

from scripts import check_ig_health as h

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
_counter = itertools.count()


def _iso(dt):
    return dt.isoformat()


def _jsonl(tmp_path, rows):
    p = tmp_path / f"f{next(_counter)}.jsonl"
    p.write_text("\n".join(json.dumps(x) for x in rows), encoding="utf-8")
    return p


def _json(tmp_path, obj):
    p = tmp_path / f"f{next(_counter)}.json"
    p.write_text("" if obj is None else json.dumps(obj), encoding="utf-8")
    return p


# ── freshness (the paused-suppression is the key robustness bit) ───────

def test_freshness_ok_when_recent(tmp_path):
    log = _jsonl(tmp_path, [{"status": "posted", "ts": _iso(NOW - timedelta(hours=6))}])
    assert h.check_freshness(NOW, paused=False, log_path=log)["status"] == h.OK


def test_freshness_alerts_when_stale_and_live(tmp_path):
    log = _jsonl(tmp_path, [{"status": "posted", "ts": _iso(NOW - timedelta(days=5))}])
    assert h.check_freshness(NOW, paused=False, log_path=log)["status"] == h.ALERT


def test_freshness_suppressed_when_paused(tmp_path):
    log = _jsonl(tmp_path, [{"status": "posted", "ts": _iso(NOW - timedelta(days=30))}])
    assert h.check_freshness(NOW, paused=True, log_path=log)["status"] == h.OK


def test_freshness_unknown_with_no_posts(tmp_path):
    assert h.check_freshness(NOW, paused=False, log_path=_jsonl(tmp_path, []))["status"] == h.UNKNOWN


# ── insights flow ──────────────────────────────────────────────────────

def test_insights_warn_when_none(tmp_path):
    log = _jsonl(tmp_path, [{"status": "posted", "ts": _iso(NOW - timedelta(days=2))}])
    assert h.check_insights_flow(NOW, log_path=log, insights_path=_jsonl(tmp_path, []))["status"] == h.WARN


def test_insights_ok_when_recent(tmp_path):
    log = _jsonl(tmp_path, [{"status": "posted", "ts": _iso(NOW - timedelta(days=2))}])
    ins = _jsonl(tmp_path, [{"media_id": "m", "polled_at": _iso(NOW - timedelta(hours=6))}])
    assert h.check_insights_flow(NOW, log_path=log, insights_path=ins)["status"] == h.OK


# ── token ──────────────────────────────────────────────────────────────

def test_token_alert_when_expiring_soon(tmp_path):
    assert h.check_token(NOW, token_path=_json(tmp_path, {"expires_at": _iso(NOW + timedelta(days=3))}))["status"] == h.ALERT


def test_token_alert_when_expired(tmp_path):
    assert h.check_token(NOW, token_path=_json(tmp_path, {"expires_at": _iso(NOW - timedelta(days=1))}))["status"] == h.ALERT


def test_token_ok_when_healthy(tmp_path):
    assert h.check_token(NOW, token_path=_json(tmp_path, {"expires_at": _iso(NOW + timedelta(days=40))}))["status"] == h.OK


def test_token_unknown_without_meta(tmp_path):
    assert h.check_token(NOW, token_path=_json(tmp_path, None))["status"] == h.UNKNOWN


# ── queue supply ───────────────────────────────────────────────────────

def test_queue_warns_when_empty_and_live(tmp_path):
    q = _json(tmp_path, {"items": [{"approved": True, "posted": True}]})  # 0 unposted
    assert h.check_queue_supply(queue_path=q, paused=False)["status"] == h.WARN


def test_queue_ok_when_empty_but_paused(tmp_path):
    assert h.check_queue_supply(queue_path=_json(tmp_path, {"items": []}), paused=True)["status"] == h.OK


def test_queue_ok_when_supplied(tmp_path):
    q = _json(tmp_path, {"items": [{"approved": True, "posted": False}]})
    assert h.check_queue_supply(queue_path=q, paused=False)["status"] == h.OK


# ── aggregation + main ─────────────────────────────────────────────────

def test_worst_picks_alert_over_warn_over_ok():
    assert h.worst([{"status": h.OK}, {"status": h.WARN}, {"status": h.ALERT}]) == h.ALERT
    assert h.worst([{"status": h.OK}, {"status": h.UNKNOWN}]) == h.UNKNOWN


def test_main_always_returns_zero(monkeypatch, tmp_path):
    # even with everything broken, a canary must not red the workflow
    monkeypatch.setattr(h, "POST_LOG", _jsonl(tmp_path, [{"status": "posted", "ts": _iso(NOW - timedelta(days=99))}]))
    monkeypatch.setattr(h, "TOKEN_META", _json(tmp_path, {"expires_at": _iso(NOW - timedelta(days=1))}))
    monkeypatch.delenv("IG_PAUSED", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert h.main(["--dry-run"]) == 0
