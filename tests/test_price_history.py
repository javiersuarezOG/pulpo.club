"""
Tests for automation/price_history.py — pins the FR-3 sidecar contract:

- Append-only when price actually moves
- Capped history per listing (PRICE_HISTORY_MAX_ENTRIES)
- is_repriced strictly < min(prior prices)
- First scrape leaves is_repriced at the per-scraper default
- Sidecar load is tolerant of missing/corrupt files
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.price_history import (   # noqa: E402
    track_prices,
    PRICE_HISTORY_MAX_ENTRIES,
)


class _Listing:
    """Minimal Listing-like object with attribute access."""
    def __init__(self, source: str = "goodlife", source_id: str = "GL-001",
                 price_usd: float | None = 100_000, is_repriced: bool = False):
        self.source = source
        self.source_id = source_id
        self.price_usd = price_usd
        self.is_repriced = is_repriced


# ── First-scrape semantics ─────────────────────────────────────────────

def test_first_scrape_appends_one_row(tmp_path):
    sidecar = tmp_path / "prices_history.json"
    li = _Listing(price_usd=300_000)
    track_prices([li], sidecar, "2026-05-04T12:00:00+00:00")
    saved = json.loads(sidecar.read_text())
    assert "goodlife|GL-001" in saved
    assert len(saved["goodlife|GL-001"]) == 1
    assert saved["goodlife|GL-001"][0]["price_usd"] == 300_000.0


def test_first_scrape_does_not_set_is_repriced(tmp_path):
    """No prior data → no signal → leave per-scraper value untouched."""
    sidecar = tmp_path / "prices_history.json"
    li = _Listing(price_usd=300_000, is_repriced=False)
    track_prices([li], sidecar, "2026-05-04T12:00:00+00:00")
    assert li.is_repriced is False   # per-scraper default preserved


def test_first_scrape_preserves_per_scraper_true(tmp_path):
    """If a scraper marked is_repriced=True (from old_price strikethrough),
    first scrape doesn't override it back to False."""
    sidecar = tmp_path / "prices_history.json"
    li = _Listing(price_usd=300_000, is_repriced=True)
    track_prices([li], sidecar, "2026-05-04T12:00:00+00:00")
    assert li.is_repriced is True


# ── Stable price across runs ──────────────────────────────────────────

def test_stable_price_does_not_append(tmp_path):
    """Listings whose price never moves contribute one row total."""
    sidecar = tmp_path / "prices_history.json"
    li = _Listing(price_usd=300_000)
    # Run 1
    track_prices([li], sidecar, "2026-05-04T12:00:00+00:00")
    # Run 2 (same price)
    track_prices([li], sidecar, "2026-05-05T12:00:00+00:00")
    # Run 3 (same price)
    track_prices([li], sidecar, "2026-05-06T12:00:00+00:00")
    saved = json.loads(sidecar.read_text())
    assert len(saved["goodlife|GL-001"]) == 1   # still just one row


def test_stable_price_sets_is_repriced_false(tmp_path):
    """Run 2+ with same price: prior_prices non-empty, current not less → False."""
    sidecar = tmp_path / "prices_history.json"
    li = _Listing(price_usd=300_000, is_repriced=False)
    track_prices([_Listing(price_usd=300_000)], sidecar, "2026-05-04T12:00:00+00:00")
    track_prices([li], sidecar, "2026-05-05T12:00:00+00:00")
    assert li.is_repriced is False


# ── Price drop ─────────────────────────────────────────────────────────

def test_price_drop_appends_and_marks_repriced(tmp_path):
    sidecar = tmp_path / "prices_history.json"
    li_run1 = _Listing(price_usd=300_000)
    track_prices([li_run1], sidecar, "2026-05-04T12:00:00+00:00")

    li_run2 = _Listing(price_usd=250_000)
    metrics = track_prices([li_run2], sidecar, "2026-05-05T12:00:00+00:00")

    saved = json.loads(sidecar.read_text())
    assert len(saved["goodlife|GL-001"]) == 2
    assert li_run2.is_repriced is True
    assert metrics["repriced_this_run"] == 1


def test_price_increase_does_not_mark_repriced(tmp_path):
    """is_repriced is for DROPS only — increases must not flip it."""
    sidecar = tmp_path / "prices_history.json"
    track_prices([_Listing(price_usd=300_000)],
                 sidecar, "2026-05-04T12:00:00+00:00")
    li = _Listing(price_usd=320_000)
    track_prices([li], sidecar, "2026-05-05T12:00:00+00:00")
    assert li.is_repriced is False


def test_price_drops_then_recovers(tmp_path):
    """Once a listing drops, subsequent rebound back to original keeps it
    NOT-repriced (current >= min(prior))."""
    sidecar = tmp_path / "prices_history.json"
    track_prices([_Listing(price_usd=300_000)], sidecar, "ts1")
    track_prices([_Listing(price_usd=250_000)], sidecar, "ts2")
    li = _Listing(price_usd=300_000)
    track_prices([li], sidecar, "ts3")
    # current (300k) is not < min(prior=250k, 300k) → False
    assert li.is_repriced is False


def test_price_drops_below_lowest_ever_marks_repriced(tmp_path):
    sidecar = tmp_path / "prices_history.json"
    track_prices([_Listing(price_usd=300_000)], sidecar, "ts1")
    track_prices([_Listing(price_usd=270_000)], sidecar, "ts2")
    li = _Listing(price_usd=240_000)
    track_prices([li], sidecar, "ts3")
    assert li.is_repriced is True


# ── History cap ────────────────────────────────────────────────────────

def test_history_capped_at_max_entries(tmp_path):
    """Sidecar is bounded — long-running listings get trimmed."""
    sidecar = tmp_path / "prices_history.json"
    # Push N+5 distinct prices in chronological order
    for i in range(PRICE_HISTORY_MAX_ENTRIES + 5):
        track_prices([_Listing(price_usd=1_000 - i)],
                     sidecar, f"ts{i:04d}")
    saved = json.loads(sidecar.read_text())
    assert len(saved["goodlife|GL-001"]) <= PRICE_HISTORY_MAX_ENTRIES


# ── Edge cases ─────────────────────────────────────────────────────────

def test_listings_with_no_price_are_skipped(tmp_path):
    sidecar = tmp_path / "prices_history.json"
    track_prices([_Listing(price_usd=None)], sidecar, "ts")
    if sidecar.exists():
        saved = json.loads(sidecar.read_text())
        assert "goodlife|GL-001" not in saved


def test_corrupt_sidecar_treated_as_empty(tmp_path):
    sidecar = tmp_path / "prices_history.json"
    sidecar.write_text("{ this is not json")
    li = _Listing(price_usd=100_000)
    track_prices([li], sidecar, "ts1")   # should not crash
    saved = json.loads(sidecar.read_text())
    assert "goodlife|GL-001" in saved
    assert li.is_repriced is False   # treated as first scrape


def test_dict_listings_supported(tmp_path):
    """Function accepts dicts as well as dataclass-like objects."""
    sidecar = tmp_path / "prices_history.json"
    li_dict = {"source": "remax", "source_id": "RM-001", "price_usd": 200_000,
               "is_repriced": False}
    track_prices([li_dict], sidecar, "ts1")
    saved = json.loads(sidecar.read_text())
    assert "remax|RM-001" in saved


def test_metrics_shape(tmp_path):
    sidecar = tmp_path / "prices_history.json"
    metrics = track_prices(
        [_Listing(source_id=f"GL-{i:03d}", price_usd=100_000 + i)
         for i in range(3)],
        sidecar, "ts1"
    )
    assert "tracked" in metrics
    assert "repriced_this_run" in metrics
    assert metrics["tracked"] == 3
    assert metrics["repriced_this_run"] == 0   # all first scrapes


def test_multiple_listings_in_one_call(tmp_path):
    """Several listings in one call all get tracked + sidecar persists all."""
    sidecar = tmp_path / "prices_history.json"
    listings = [
        _Listing(source_id="A", price_usd=100_000),
        _Listing(source_id="B", price_usd=200_000),
        _Listing(source_id="C", price_usd=300_000),
    ]
    track_prices(listings, sidecar, "ts1")
    saved = json.loads(sidecar.read_text())
    assert {"goodlife|A", "goodlife|B", "goodlife|C"} <= set(saved.keys())
