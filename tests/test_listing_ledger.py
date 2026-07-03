"""Tests for the listing existence ledger (PR-S4)."""
from __future__ import annotations

import json
from pathlib import Path

from automation.listing_ledger import (
    KNOWN_EXISTENCE_STATUSES,
    LedgerEntry,
    STALE_THRESHOLD_RUNS,
    compute_state,
    get_first_seen_at,
    load_ledger,
    save_ledger,
    stale_keys,
    update_ledger,
)


# ---------- Closed-set contract ----------

def test_known_statuses_contract():
    """Per CLAUDE.md producer-consumer rule (post-2026-06-02). Adding
    a value without consumer updates is forbidden."""
    assert KNOWN_EXISTENCE_STATUSES == frozenset({
        "confirmed_current",
        "missing_recently",
        "stale",
    })


def test_stale_threshold_anchored():
    """Tuning this is deliberate; the test failing is the guardrail."""
    assert STALE_THRESHOLD_RUNS == 3


# ---------- compute_state: first-ever observation ----------

def test_first_observation_initializes_confirmed_current():
    entry = compute_state(
        prior=None,
        is_present=True,
        source_succeeded=True,
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    assert entry.existence_status == "confirmed_current"
    assert entry.first_seen_at == "2026-06-05T00:00:00+00:00"
    assert entry.last_seen_at == "2026-06-05T00:00:00+00:00"
    assert entry.consecutive_seen_count == 1
    assert entry.missing_since is None


# ---------- compute_state: still present ----------

def test_present_increments_counter_and_updates_last_seen():
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-04T00:00:00+00:00",
        consecutive_seen_count=4,
        missing_since=None,
        existence_status="confirmed_current",
    )
    entry = compute_state(
        prior=prior,
        is_present=True,
        source_succeeded=True,
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    assert entry.first_seen_at == "2026-06-01T00:00:00+00:00"  # unchanged
    assert entry.last_seen_at == "2026-06-05T00:00:00+00:00"
    assert entry.consecutive_seen_count == 5
    assert entry.missing_since is None
    assert entry.existence_status == "confirmed_current"


def test_present_after_missing_resets_missing_since():
    """Listing came back after being missing → reset state."""
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-02T00:00:00+00:00",
        consecutive_seen_count=0,
        missing_since="2026-06-03T00:00:00+00:00",
        existence_status="missing_recently",
    )
    entry = compute_state(
        prior=prior,
        is_present=True,
        source_succeeded=True,
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    assert entry.missing_since is None
    assert entry.existence_status == "confirmed_current"
    assert entry.consecutive_seen_count == 1


# ---------- compute_state: source failed → carry state ----------

def test_source_failed_carries_state_forward():
    """If the scraper itself failed, absence is NOT meaningful."""
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-04T00:00:00+00:00",
        consecutive_seen_count=4,
        missing_since=None,
        existence_status="confirmed_current",
    )
    entry = compute_state(
        prior=prior,
        is_present=False,
        source_succeeded=False,
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    # State must be EXACTLY prior — no update.
    assert entry == prior


# ---------- compute_state: missing → missing_recently → stale ----------

def test_first_missing_flips_to_missing_recently():
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-04T00:00:00+00:00",
        consecutive_seen_count=4,
        missing_since=None,
        existence_status="confirmed_current",
    )
    entry = compute_state(
        prior=prior,
        is_present=False,
        source_succeeded=True,
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    assert entry.missing_since == "2026-06-05T00:00:00+00:00"
    assert entry.existence_status == "missing_recently"
    assert entry.consecutive_seen_count == 0
    # last_seen_at stays at the prior value (when it was last seen).
    assert entry.last_seen_at == "2026-06-04T00:00:00+00:00"


def test_missing_2_runs_still_missing_recently():
    """Day 5 missing, day 6 still missing → 2 consecutive missing,
    below the 3-run STALE threshold → still missing_recently."""
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-04T00:00:00+00:00",
        consecutive_seen_count=0,
        missing_since="2026-06-05T00:00:00+00:00",
        existence_status="missing_recently",
    )
    entry = compute_state(
        prior=prior,
        is_present=False,
        source_succeeded=True,
        tick_iso="2026-06-06T00:00:00+00:00",
    )
    # missing_since stays at the first absence.
    assert entry.missing_since == "2026-06-05T00:00:00+00:00"
    assert entry.existence_status == "missing_recently"


def test_missing_3plus_runs_flips_to_stale():
    """3 consecutive missing → stale. Ranker excludes."""
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-04T00:00:00+00:00",
        consecutive_seen_count=0,
        missing_since="2026-06-05T00:00:00+00:00",
        existence_status="missing_recently",
    )
    entry = compute_state(
        prior=prior,
        is_present=False,
        source_succeeded=True,
        tick_iso="2026-06-07T00:00:00+00:00",  # 2 days later = 3 missing runs
    )
    assert entry.existence_status == "stale"


# ---------- Persistence: load + save round-trip ----------

def test_load_ledger_missing_file_returns_empty(tmp_path: Path):
    assert load_ledger(tmp_path / "absent.json") == {}


def test_load_ledger_handles_malformed_json(tmp_path: Path):
    p = tmp_path / "ledger.json"
    p.write_text("not json {")
    assert load_ledger(p) == {}


def test_load_ledger_migrates_old_schema(tmp_path: Path):
    """Backwards-compat: old format was {key: iso_string}. Must migrate
    to LedgerEntry without losing first_seen_at."""
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({
        "remax|RM123": "2026-06-01T00:00:00+00:00",
        "nexo|NX456": "2026-06-02T00:00:00+00:00",
    }))
    ledger = load_ledger(p)
    assert "remax|RM123" in ledger
    entry = ledger["remax|RM123"]
    assert entry.first_seen_at == "2026-06-01T00:00:00+00:00"
    assert entry.last_seen_at == "2026-06-01T00:00:00+00:00"  # default to first
    assert entry.existence_status == "confirmed_current"


def test_load_ledger_loads_new_schema(tmp_path: Path):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({
        "remax|RM123": {
            "first_seen_at": "2026-06-01T00:00:00+00:00",
            "last_seen_at": "2026-06-04T00:00:00+00:00",
            "consecutive_seen_count": 4,
            "missing_since": None,
            "existence_status": "confirmed_current",
        },
    }))
    ledger = load_ledger(p)
    entry = ledger["remax|RM123"]
    assert entry.consecutive_seen_count == 4
    assert entry.last_seen_at == "2026-06-04T00:00:00+00:00"


def test_save_then_load_roundtrip(tmp_path: Path):
    p = tmp_path / "ledger.json"
    ledger = {
        "remax|RM123": LedgerEntry(
            first_seen_at="2026-06-01T00:00:00+00:00",
            last_seen_at="2026-06-05T00:00:00+00:00",
            consecutive_seen_count=5,
            missing_since=None,
            existence_status="confirmed_current",
        ),
    }
    save_ledger(ledger, p)
    loaded = load_ledger(p)
    assert loaded == ledger


def test_save_ledger_is_atomic(tmp_path: Path):
    """Atomic write via temp file + rename. After save, no .tmp leftover."""
    p = tmp_path / "ledger.json"
    save_ledger({"x|1": LedgerEntry("t", "t", 1, None, "confirmed_current")}, p)
    assert p.exists()
    assert not (tmp_path / "ledger.json.tmp").exists()


# ---------- update_ledger: bulk update from one nightly ----------

def test_update_ledger_marks_new_listings_as_first_seen(tmp_path: Path):
    ledger: dict[str, LedgerEntry] = {}
    new = update_ledger(
        ledger=ledger,
        present_keys_by_source={"remax": {"RM1", "RM2"}, "nexo": {"NX1"}},
        succeeded_sources={"remax", "nexo"},
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    assert "remax|RM1" in new
    assert "remax|RM2" in new
    assert "nexo|NX1" in new
    assert all(v.existence_status == "confirmed_current" for v in new.values())


def test_update_ledger_marks_dropped_listings_as_missing(tmp_path: Path):
    """A listing in the ledger but not in this nightly's present set
    AND its source succeeded → missing_recently."""
    ledger = {
        "remax|RM1": LedgerEntry(
            first_seen_at="2026-06-01T00:00:00+00:00",
            last_seen_at="2026-06-04T00:00:00+00:00",
            consecutive_seen_count=4,
            missing_since=None,
            existence_status="confirmed_current",
        ),
    }
    new = update_ledger(
        ledger=ledger,
        present_keys_by_source={"remax": set()},  # remax succeeded but yielded 0
        succeeded_sources={"remax"},
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    assert new["remax|RM1"].existence_status == "missing_recently"


def test_update_ledger_preserves_state_when_source_failed():
    """Source failed → no state change for that source's listings."""
    ledger = {
        "remax|RM1": LedgerEntry(
            first_seen_at="2026-06-01T00:00:00+00:00",
            last_seen_at="2026-06-04T00:00:00+00:00",
            consecutive_seen_count=4,
            missing_since=None,
            existence_status="confirmed_current",
        ),
    }
    new = update_ledger(
        ledger=ledger,
        present_keys_by_source={},  # nothing for remax
        succeeded_sources=set(),  # remax NOT in succeeded set
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    # No change — scraper failed, not the listing.
    assert new["remax|RM1"] == ledger["remax|RM1"]


def test_update_ledger_does_not_mutate_input():
    """Pure function: caller's dict must not be modified in place."""
    original = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-04T00:00:00+00:00",
        consecutive_seen_count=4,
        missing_since=None,
        existence_status="confirmed_current",
    )
    ledger = {"remax|RM1": original}
    update_ledger(
        ledger=ledger,
        present_keys_by_source={"remax": {"RM1"}},
        succeeded_sources={"remax"},
        tick_iso="2026-06-05T00:00:00+00:00",
    )
    # Original is unchanged.
    assert ledger["remax|RM1"] is original


# ---------- Read-side helpers ----------

def test_get_first_seen_at_returns_value():
    ledger = {
        "remax|RM1": LedgerEntry(
            first_seen_at="2026-06-01T00:00:00+00:00",
            last_seen_at="2026-06-05T00:00:00+00:00",
            consecutive_seen_count=5,
            missing_since=None,
            existence_status="confirmed_current",
        ),
    }
    assert get_first_seen_at(ledger, "remax|RM1") == "2026-06-01T00:00:00+00:00"


def test_get_first_seen_at_missing_key_returns_none():
    assert get_first_seen_at({}, "missing|key") is None


def test_stale_keys_filters_correctly():
    ledger = {
        "a|1": LedgerEntry("t", "t", 1, None, "confirmed_current"),
        "b|2": LedgerEntry("t", "t", 0, "t2", "missing_recently"),
        "c|3": LedgerEntry("t", "t", 0, "t2", "stale"),
        "d|4": LedgerEntry("t", "t", 0, "t2", "stale"),
    }
    assert stale_keys(ledger) == {"c|3", "d|4"}


# ---------- Plan 012: removal_reason / removal_detected_at ----------

def test_known_removal_reasons_contract():
    """Closed set per CLAUDE.md producer-consumer rule. Producer:
    automation/sold_probe.py; consumers: the [sold_probe] nightly
    summary, the sold_probe_completed PostHog event, run.py's is_sold
    stamping."""
    from automation.listing_ledger import KNOWN_REMOVAL_REASONS
    assert KNOWN_REMOVAL_REASONS == frozenset({"sold", "delisted", "unknown"})


def test_removal_reason_literals_in_sold_probe_are_in_closed_set():
    """Grep-based producer contract (pytest port of the pattern in
    tests/api/email_type_contract.test.js): every removal-reason string
    literal the producer module can classify into must be a member of
    KNOWN_REMOVAL_REASONS. A producer-only edit (new literal, no
    allowlist entry) fails here — that is the guardrail working.
    The forward-compat direction (allowlist entry with no producer yet)
    is deliberately allowed."""
    import re as _re
    from automation.listing_ledger import KNOWN_REMOVAL_REASONS

    producer = Path(__file__).resolve().parent.parent / "automation" / "sold_probe.py"
    src = producer.read_text(encoding="utf-8")
    # classify_page returns + LLM-state literals: quoted strings in
    # `return "x"` statements and the documented state set. "active" is
    # the non-removal sentinel and is exempt by definition.
    returned = set(_re.findall(r'return\s+"([a-z_]+)"', src))
    returned.discard("active")
    unknown_literals = returned - KNOWN_REMOVAL_REASONS
    assert not unknown_literals, (
        f"automation/sold_probe.py returns removal reason(s) "
        f"{sorted(unknown_literals)} not present in "
        f"KNOWN_REMOVAL_REASONS — add them to the closed set in "
        f"automation/listing_ledger.py in the SAME PR (see CLAUDE.md "
        f"producer-consumer rule, precedent PR #522)."
    )


def test_ledger_round_trip_with_removal_reason(tmp_path: Path):
    path = tmp_path / "ledger.json"
    entry = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-05T00:00:00+00:00",
        consecutive_seen_count=0,
        missing_since="2026-06-06T00:00:00+00:00",
        existence_status="missing_recently",
        removal_reason="sold",
        removal_detected_at="2026-06-08T00:00:00+00:00",
    )
    save_ledger({"src|1": entry}, path)
    loaded = load_ledger(path)
    assert loaded["src|1"] == entry


def test_old_schema_entry_loads_with_none_removal_fields(tmp_path: Path):
    """Pre-012 dict rows (no removal keys) and ancient string rows both
    load with removal fields defaulted to None — the established
    migration pattern."""
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({
        "src|old-dict": {
            "first_seen_at": "2026-06-01T00:00:00+00:00",
            "last_seen_at": "2026-06-05T00:00:00+00:00",
            "consecutive_seen_count": 3,
            "missing_since": None,
            "existence_status": "confirmed_current",
        },
        "src|old-string": "2026-05-01T00:00:00+00:00",
    }), encoding="utf-8")
    loaded = load_ledger(path)
    assert loaded["src|old-dict"].removal_reason is None
    assert loaded["src|old-dict"].removal_detected_at is None
    assert loaded["src|old-string"].removal_reason is None


def test_reappearing_listing_clears_removal_reason():
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-05T00:00:00+00:00",
        consecutive_seen_count=0,
        missing_since="2026-06-06T00:00:00+00:00",
        existence_status="missing_recently",
        removal_reason="sold",
        removal_detected_at="2026-06-08T00:00:00+00:00",
    )
    entry = compute_state(
        prior=prior,
        is_present=True,
        source_succeeded=True,
        tick_iso="2026-06-09T00:00:00+00:00",
    )
    assert entry.existence_status == "confirmed_current"
    assert entry.removal_reason is None
    assert entry.removal_detected_at is None


def test_still_missing_listing_preserves_removal_reason():
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-05T00:00:00+00:00",
        consecutive_seen_count=0,
        missing_since="2026-06-06T00:00:00+00:00",
        existence_status="missing_recently",
        removal_reason="delisted",
        removal_detected_at="2026-06-07T00:00:00+00:00",
    )
    entry = compute_state(
        prior=prior,
        is_present=False,
        source_succeeded=True,
        tick_iso="2026-06-09T00:00:00+00:00",
    )
    assert entry.removal_reason == "delisted"
    assert entry.removal_detected_at == "2026-06-07T00:00:00+00:00"


def test_failed_source_carry_forward_preserves_removal_reason():
    prior = LedgerEntry(
        first_seen_at="2026-06-01T00:00:00+00:00",
        last_seen_at="2026-06-05T00:00:00+00:00",
        consecutive_seen_count=0,
        missing_since="2026-06-06T00:00:00+00:00",
        existence_status="missing_recently",
        removal_reason="sold",
        removal_detected_at="2026-06-07T00:00:00+00:00",
    )
    entry = compute_state(
        prior=prior,
        is_present=False,
        source_succeeded=False,
        tick_iso="2026-06-09T00:00:00+00:00",
    )
    assert entry == prior
