from __future__ import annotations

from automation.carry_forward import load_previous_ranked_from_git, merge_carry_forward
from automation.listing_ledger import LedgerEntry
from pulpo.models import Listing


def _listing(source: str, source_id: str, rank: int, score: float = 90.0) -> Listing:
    return Listing(
        source=source,
        source_id=source_id,
        url=f"https://example.test/{source_id}",
        scraped_at="2026-06-08T00:00:00+00:00",
        title=f"Listing {source_id}",
        rank=rank,
        rank_score=score,
        existence_status="confirmed_current",
    )


def _row(source: str, source_id: str) -> dict:
    return _listing(source, source_id, 1).to_dict()


def _entry(status: str = "confirmed_current") -> LedgerEntry:
    return LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-07T00:00:00+00:00",
        consecutive_seen_count=4,
        missing_since=None,
        existence_status=status,
    )


def test_failed_source_listings_are_carried_at_tail_as_missing_recently():
    fresh = [_listing("good", "1", 1, 95.0)]
    merged, metrics = merge_carry_forward(
        today=fresh,
        yesterday_ranked=[_row("vivolatam", "v1")],
        ledger={"vivolatam|v1": _entry("confirmed_current")},
        failed_sources={"vivolatam"},
    )

    assert metrics["carried_count"] == 1
    assert [li.source_id for li in merged] == ["1", "v1"]
    carried = merged[-1]
    assert carried.existence_status == "missing_recently"
    assert carried.last_seen_at == "2026-06-07T00:00:00+00:00"
    assert carried.rank == 2
    assert carried.rank_score == -1.0
    assert "carried_forward_failed_source" in carried.rank_reasons


def test_succeeded_but_shrank_source_is_not_carried():
    fresh: list[Listing] = []
    merged, metrics = merge_carry_forward(
        today=fresh,
        yesterday_ranked=[_row("vivolatam", "v1")],
        ledger={"vivolatam|v1": _entry("confirmed_current")},
        failed_sources=set(),
    )
    assert merged == []
    assert metrics["carried_count"] == 0


def test_stale_ledger_entries_are_dropped():
    merged, metrics = merge_carry_forward(
        today=[],
        yesterday_ranked=[_row("vivolatam", "v1")],
        ledger={"vivolatam|v1": _entry("stale")},
        failed_sources={"vivolatam"},
    )
    assert merged == []
    assert metrics["skipped_stale"] == 1


def test_carry_forward_preserves_fresh_rank_invariant():
    fresh = [_listing("good", "1", 1, 99.0), _listing("good", "2", 2, 88.0)]
    merged, _metrics = merge_carry_forward(
        today=fresh,
        yesterday_ranked=[_row("vivolatam", "v1"), _row("vivolatam", "v2")],
        ledger={"vivolatam|v1": _entry(), "vivolatam|v2": _entry()},
        failed_sources={"vivolatam"},
    )

    fresh_ranks = [li.rank for li in merged if li.existence_status == "confirmed_current"]
    stale_ranks = [li.rank for li in merged if li.existence_status == "missing_recently"]
    assert max(fresh_ranks) < min(stale_ranks)
    assert all((li.rank_score or 0) >= 0 for li in merged[:2])
    assert all(li.rank_score == -1.0 for li in merged[2:])


def test_load_previous_ranked_from_git_missing_ref_is_empty(tmp_path):
    assert load_previous_ranked_from_git(tmp_path) == []
