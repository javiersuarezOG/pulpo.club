"""Tests for the per-post IG insights poller (automation/ig_insights.py).
All offline: the Graph API is mocked at the httpx boundary."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from automation import ig_insights


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ── read_posted / filtering ────────────────────────────────────────────

def test_read_posted_keeps_only_posted_with_media_and_ts(tmp_path, monkeypatch):
    log = tmp_path / "log.jsonl"
    rows = [
        {"status": "posted", "media_id": "m1", "ts": "2026-07-20T01:00:00+00:00", "day": 203},
        {"status": "failed", "media_id": None, "ts": "2026-07-20T02:00:00+00:00", "day": 204},
        {"status": "posted", "media_id": "m2", "ts": "bogus", "day": 205},   # unparseable ts
        {"status": "posted", "day": 206},                                     # no media_id
    ]
    log.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    monkeypatch.setattr(ig_insights, "POST_LOG", log)
    got = ig_insights.read_posted()
    assert [e["media_id"] for e in got] == ["m1"]


# ── due_polls maturity logic ───────────────────────────────────────────

def test_due_polls_fires_at_24_then_72_and_is_idempotent():
    posted = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    entry = {"media_id": "m1", "ts": _iso(posted)}

    # 12h old → nothing due
    assert ig_insights.due_polls(entry, posted + timedelta(hours=12), set()) == []
    # 25h old → 24h poll due, 72h not yet
    assert ig_insights.due_polls(entry, posted + timedelta(hours=25), set()) == [24]
    # 80h old, nothing recorded → both due
    assert ig_insights.due_polls(entry, posted + timedelta(hours=80), set()) == [24, 72]
    # 80h old but 24h already recorded → only 72h
    assert ig_insights.due_polls(entry, posted + timedelta(hours=80), {("m1", 24)}) == [72]
    # both recorded → nothing
    assert ig_insights.due_polls(entry, posted + timedelta(hours=99), {("m1", 24), ("m1", 72)}) == []


# ── Graph mock ─────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = data or {}
        self.text = text

    def json(self):
        return self._data


class _Client:
    """Records requested metrics; returns queued responses in order."""
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append(params.get("metric", ""))
        return self._responses.pop(0)

    def close(self):
        pass


def _insights_payload(**metrics):
    return {"data": [{"name": k, "values": [{"value": v}]} for k, v in metrics.items()]}


def test_fetch_parses_metric_values():
    client = _Client([_Resp(200, _insights_payload(reach=1200, saved=48, shares=12))])
    got = ig_insights.fetch_media_insights("m1", "tok", client=client)
    assert got == {"reach": 1200, "saved": 48, "shares": 12}


def test_fetch_retries_with_core_metrics_on_400():
    client = _Client([
        _Resp(400, text="metric 'views' unsupported"),           # full batch fails
        _Resp(200, _insights_payload(reach=900, saved=30)),       # core retry succeeds
    ])
    got = ig_insights.fetch_media_insights("m1", "tok", client=client)
    assert got == {"reach": 900, "saved": 30}
    assert "views" in client.calls[0] and "views" not in client.calls[1]  # retry dropped views


def test_fetch_soft_fails_to_empty_on_double_400():
    client = _Client([_Resp(400, text="err"), _Resp(400, text="err")])
    assert ig_insights.fetch_media_insights("m1", "tok", client=client) == {}


# ── run() end-to-end ───────────────────────────────────────────────────

def test_run_no_token_is_a_noop(monkeypatch):
    monkeypatch.delenv("IG_ACCESS_TOKEN", raising=False)
    assert ig_insights.run() == 0


def test_run_polls_due_posts_and_is_idempotent(tmp_path, monkeypatch):
    posted = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps(
        {"status": "posted", "media_id": "m1", "ts": _iso(posted), "day": 203, "shelf": "campaign"}
    ), encoding="utf-8")
    art = tmp_path / "insights.jsonl"
    monkeypatch.setattr(ig_insights, "POST_LOG", log)
    monkeypatch.setattr(ig_insights, "INSIGHTS_ARTIFACT", art)
    monkeypatch.setenv("IG_ACCESS_TOKEN", "tok")

    now = posted + timedelta(hours=25)  # 24h poll due, 72h not yet
    client = _Client([_Resp(200, _insights_payload(reach=1000, saved=40, shares=10))])
    n = ig_insights.run(now=now, client=client)
    assert n == 1
    rows = [json.loads(ln) for ln in art.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    assert rows[0]["media_id"] == "m1" and rows[0]["maturity_h"] == 24
    assert rows[0]["metrics"] == {"reach": 1000, "saved": 40, "shares": 10}

    # re-run at same time → idempotent, no duplicate row
    assert ig_insights.run(now=now, client=_Client([])) == 0
    rows2 = [json.loads(ln) for ln in art.read_text().splitlines() if ln.strip()]
    assert len(rows2) == 1

    # later, 72h matures → one more row
    client2 = _Client([_Resp(200, _insights_payload(reach=1500, saved=60, shares=18))])
    assert ig_insights.run(now=posted + timedelta(hours=73), client=client2) == 1
    rows3 = [json.loads(ln) for ln in art.read_text().splitlines() if ln.strip()]
    assert {r["maturity_h"] for r in rows3} == {24, 72}
