"""Tests for the alert-only social-floor canary script.

Covers the pure helpers (`passes_quality_gate`, `sort_by_rank`,
`is_contract_eligible`, `compute_metrics`, `verdict_for`,
`build_slack_message`) and the CLI integration (file reads, --json,
--dry-run, SLACK_WEBHOOK_URL absence, exit codes).

The gate + sort replicate api/social/listings.js::passesQualityGate and
its rank_score-desc sort; the eligibility criterion replicates
web/tests/contracts/social-api.test.ts::findEligibleListingId. These
tests pin the replication clause-by-clause so a drift in the Python
mirror is caught even when the JS side hasn't changed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

# Import as a module — the script's `if __name__ == "__main__"` guard
# makes this safe.
import check_social_floor as csf  # type: ignore[import-not-found]  # noqa: E402


def _listing(**overrides) -> dict:
    """A listing that passes the quality gate AND the contract criterion
    by default; tests knock out one field at a time."""
    base = {
        "source": "remax",
        "source_id": "x1",
        "hero_photo_path": "photos/remax_x1.jpg",
        "price_usd": 150_000,
        "data_quality_score": 0.9,
        "has_text_overlay": None,
        "has_marketing_overlay": None,
        "hero_photo_quality_score": 80,
        "rank_score": 0.5,
        "hires_available": True,
        "hires_width": 1920,
        "hires_height": 1440,
    }
    base.update(overrides)
    return base


def _write_ranked(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "ranked.json"
    path.write_text(json.dumps(rows))
    return path


# ── passes_quality_gate: each clause of the JS gate ──────────────────

def test_gate_passes_fully_populated_listing():
    assert csf.passes_quality_gate(_listing()) is True


def test_gate_rejects_missing_hero_photo():
    assert csf.passes_quality_gate(_listing(hero_photo_path=None)) is False
    # JS `!row.hero_photo_path` is a falsy check — empty string also rejects.
    assert csf.passes_quality_gate(_listing(hero_photo_path="")) is False


def test_gate_rejects_null_price():
    assert csf.passes_quality_gate(_listing(price_usd=None)) is False


def test_gate_rejects_low_data_quality_score():
    assert csf.passes_quality_gate(_listing(data_quality_score=0.49)) is False
    assert csf.passes_quality_gate(_listing(data_quality_score=0.5)) is True
    # JS `(row.data_quality_score ?? 0) < 0.5` — null coalesces to 0 → reject.
    assert csf.passes_quality_gate(_listing(data_quality_score=None)) is False


def test_gate_rejects_explicit_text_overlay_only():
    assert csf.passes_quality_gate(_listing(has_text_overlay=True)) is False
    # Soft signal: null and False both pass.
    assert csf.passes_quality_gate(_listing(has_text_overlay=False)) is True
    assert csf.passes_quality_gate(_listing(has_text_overlay=None)) is True


def test_gate_rejects_explicit_marketing_overlay_only():
    assert csf.passes_quality_gate(_listing(has_marketing_overlay=True)) is False
    assert csf.passes_quality_gate(_listing(has_marketing_overlay=False)) is True
    assert csf.passes_quality_gate(_listing(has_marketing_overlay=None)) is True


def test_gate_hero_photo_quality_score_threshold():
    assert csf.passes_quality_gate(_listing(hero_photo_quality_score=49)) is False
    assert csf.passes_quality_gate(_listing(hero_photo_quality_score=50)) is True
    # JS `!= null` guard — null tolerated.
    assert csf.passes_quality_gate(_listing(hero_photo_quality_score=None)) is True


# ── sort_by_rank: mirrors the sort=rank branch ───────────────────────

def test_sort_orders_rank_score_descending():
    rows = [
        _listing(source_id="a", rank_score=0.1),
        _listing(source_id="b", rank_score=0.9),
        _listing(source_id="c", rank_score=0.5),
    ]
    out = csf.sort_by_rank(rows)
    assert [row["source_id"] for row in out] == ["b", "c", "a"]


def test_sort_drops_non_numeric_rank_score():
    """JS filters on `typeof row.rank_score === "number"` before sorting —
    null/missing/string rows never reach the response."""
    rows = [
        _listing(source_id="a", rank_score=None),
        _listing(source_id="b", rank_score="0.9"),
        _listing(source_id="c", rank_score=0.5),
        _listing(source_id="d", rank_score=True),  # bool is not a JS number here
    ]
    out = csf.sort_by_rank(rows)
    assert [row["source_id"] for row in out] == ["c"]


def test_sort_missing_rank_score_key_dropped():
    row = _listing(source_id="a")
    del row["rank_score"]
    assert csf.sort_by_rank([row]) == []


# ── is_contract_eligible: the contract test's criterion ──────────────

def test_eligible_when_dims_clear_and_available_true():
    assert csf.is_contract_eligible(_listing(hires_width=1080, hires_height=1350)) is True


def test_eligible_tolerates_null_hires_available():
    """The JS reads `hires_available !== false` — None/missing tolerated."""
    assert csf.is_contract_eligible(_listing(hires_available=None)) is True
    row = _listing()
    del row["hires_available"]
    assert csf.is_contract_eligible(row) is True


def test_not_eligible_when_hires_available_false():
    assert csf.is_contract_eligible(_listing(hires_available=False)) is False


def test_not_eligible_below_width_or_height():
    assert csf.is_contract_eligible(_listing(hires_width=1079)) is False
    assert csf.is_contract_eligible(_listing(hires_height=1349)) is False


def test_not_eligible_when_dims_null():
    """JS `hires_width ?? 0` — null dims coalesce to 0 → ineligible."""
    assert csf.is_contract_eligible(_listing(hires_width=None)) is False
    assert csf.is_contract_eligible(_listing(hires_height=None)) is False


# ── compute_metrics ──────────────────────────────────────────────────

def test_metrics_counts_eligible_in_top50_only():
    """Eligible listing at index 116 of the sorted order (the live
    incident shape) must NOT count toward eligible_in_top50 but must
    set first_eligible_index."""
    rows = [
        _listing(source_id=f"filler{i}", rank_score=1000 - i, hires_width=640, hires_height=480)
        for i in range(116)
    ]
    rows.append(_listing(source_id="deep", rank_score=1.0))  # eligible, ranks 117th
    m = csf.compute_metrics(rows)
    assert m["eligible_in_top50"] == 0
    assert m["first_eligible_index"] == 116
    assert m["gate_passers"] == 117


def test_metrics_first_eligible_index_none_when_no_eligible():
    rows = [_listing(source_id="a", hires_width=100, hires_height=100)]
    m = csf.compute_metrics(rows)
    assert m["eligible_in_top50"] == 0
    assert m["first_eligible_index"] is None


def test_metrics_hires_available_distribution():
    rows = [
        _listing(source_id="t", rank_score=3, hires_available=True),
        _listing(source_id="f", rank_score=2, hires_available=False),
        _listing(source_id="n", rank_score=1, hires_available=None),
    ]
    m = csf.compute_metrics(rows)
    assert m["hires_available_top50"] == {"true": 1, "false": 1, "null": 1}


def test_metrics_gate_filters_before_ranking():
    """A gate-failing listing with a huge rank_score must not occupy a
    top-50 slot."""
    rows = [
        _listing(source_id="gated", rank_score=99.0, price_usd=None),  # fails gate
        _listing(source_id="ok", rank_score=1.0),
    ]
    m = csf.compute_metrics(rows)
    assert m["gate_passers"] == 1
    assert m["eligible_in_top50"] == 1
    assert m["first_eligible_index"] == 0


def test_metrics_empty_input():
    m = csf.compute_metrics([])
    assert m["eligible_in_top50"] == 0
    assert m["first_eligible_index"] is None
    assert m["gate_passers"] == 0


# ── verdict_for: the three bands ─────────────────────────────────────

def test_verdict_critical_at_zero():
    assert csf.verdict_for(0) == "CRITICAL"


def test_verdict_warn_in_thin_band():
    assert csf.verdict_for(1) == "WARN"
    assert csf.verdict_for(2) == "WARN"


def test_verdict_ok_at_three_or_more():
    assert csf.verdict_for(3) == "OK"
    assert csf.verdict_for(50) == "OK"


# ── build_slack_message ──────────────────────────────────────────────

def _metrics(n: int, first=None) -> dict:
    return {
        "total_listings": 100,
        "gate_passers": 80,
        "ranked_with_score": 80,
        "eligible_in_top50": n,
        "first_eligible_index": first,
        "hires_available_top50": {"true": 2, "false": 3, "null": 45},
        "target_w": 1080,
        "target_h": 1350,
    }


def test_slack_message_critical_names_consumers():
    msg = csf.build_slack_message(_metrics(0, 116), "CRITICAL",
                                  "https://github.com/x/y/actions/runs/42")
    assert "CRITICAL" in msg
    assert "Instagram" in msg
    assert "first_eligible_index=116" in msg
    assert "actions/runs/42" in msg
    assert "NOT blocked" in msg


def test_slack_message_warn_mentions_count():
    msg = csf.build_slack_message(_metrics(2, 7), "WARN", None)
    assert "2" in msg
    assert "first_eligible_index=7" in msg
    assert "actions/runs" not in msg


def test_slack_message_handles_no_eligible_index():
    msg = csf.build_slack_message(_metrics(0, None), "CRITICAL", None)
    assert "first_eligible_index=none" in msg


# ── main() integration ───────────────────────────────────────────────

def test_main_ok_exits_zero(tmp_path, capsys, monkeypatch):
    rows = [_listing(source_id=f"row{i}", rank_score=float(i)) for i in range(5)]
    _write_ranked(tmp_path, rows)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csf.main(["--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "OK" in out
    assert "eligible_in_top50=5" in out


def test_main_critical_exits_one_and_skips_post_without_webhook(tmp_path, capsys, monkeypatch):
    rows = [_listing(source_id="a", hires_width=100, hires_height=100)]
    _write_ranked(tmp_path, rows)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csf.main(["--data-dir", str(tmp_path)])
    assert rc == 1
    out = capsys.readouterr().out
    assert "CRITICAL" in out
    assert "skipping POST" in out


def test_main_warn_exits_zero(tmp_path, capsys, monkeypatch):
    rows = [
        _listing(source_id="ok", rank_score=2.0),
        _listing(source_id="small", rank_score=1.0, hires_width=100),
    ]
    _write_ranked(tmp_path, rows)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csf.main(["--data-dir", str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARN" in out


def test_main_json_flag_prints_machine_readable(tmp_path, capsys, monkeypatch):
    rows = [_listing(source_id="a")]
    _write_ranked(tmp_path, rows)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csf.main(["--data-dir", str(tmp_path), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out[: out.rindex("}") + 1])
    assert parsed["eligible_in_top50"] == 1
    assert parsed["verdict"] == "WARN"


def test_main_dry_run_prints_alert_without_posting(tmp_path, capsys, monkeypatch):
    rows = [_listing(source_id="a", hires_available=False)]
    _write_ranked(tmp_path, rows)
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/should-not-post")
    rc = csf.main(["--data-dir", str(tmp_path), "--dry-run",
                   "--run-url", "https://github.com/x/y/actions/runs/9"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "not posting" in out
    assert "actions/runs/9" in out


def test_main_missing_ranked_json_exits_one(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csf.main(["--data-dir", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "cannot read" in err


def test_main_non_list_ranked_json_exits_one(tmp_path, capsys, monkeypatch):
    (tmp_path / "ranked.json").write_text('{"not": "a list"}')
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    rc = csf.main(["--data-dir", str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "not a list" in err
