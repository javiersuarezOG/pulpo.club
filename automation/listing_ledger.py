"""Listing existence ledger — PR-S4.

Extends the existing ``web/data/listings_history.json`` (which only
tracked ``first_seen_at`` per (source, source_id)) with the full set
of existence-state fields needed to answer "is this listing still
live?":

  - ``first_seen_at``        ISO-8601 of the listing's first nightly
  - ``last_seen_at``         ISO-8601 of the most recent nightly that
                             scraped this source AND found this listing
  - ``consecutive_seen_count`` how many consecutive nightlies in a row
                             the listing has been present
  - ``missing_since``        ISO-8601 of the first nightly where the
                             listing was absent (None if currently
                             present)
  - ``existence_status``     ``confirmed_current | missing_recently |
                             stale``

Backwards compatibility
-----------------------
The on-disk schema was historically ``{key: iso_string}``. The new
schema is ``{key: dict_with_above_fields}``. ``load_ledger`` migrates
plain-string entries to the new dict on read; new writes use the new
schema. Existing callers reading ``first_seen_at`` from the file
directly should switch to ``get_first_seen_at(ledger, key)``.

Per CLAUDE.md producer-consumer rule (post-2026-06-02):
``KNOWN_EXISTENCE_STATUSES`` is the closed set. Consumer = the ranker
(skips ``stale``) + the operator dashboard tile + a "new this week"
UI surface.

Scraper-failure handling
------------------------
A listing being absent ONE nightly may mean the scraper failed, not
the listing was un-published. ``compute_state`` takes a
``source_succeeded`` flag: if False, the listing's state is preserved
(no missing_since update). Only when a scraper successfully returned
results AND a specific listing isn't in those results do we count it
as missing.
"""
from __future__ import annotations

import dataclasses
import json
import typing as t
from pathlib import Path


# ---------- Constants ----------

KNOWN_EXISTENCE_STATUSES: frozenset[str] = frozenset({
    "confirmed_current",
    "missing_recently",
    "stale",
})
"""Closed set per CLAUDE.md producer-consumer rule (post-2026-06-02).
Contract test: ``tests/test_listing_ledger.py::test_known_statuses_contract``.
Consumer: ranker filters ``stale``; operator dashboard PR-S7 reads the
distribution; "new this week" UI checks ``first_seen_at + 7d``."""

# A listing missing for >= STALE_THRESHOLD consecutive nightlies flips
# to ``stale`` (ranker excludes). Less than this is ``missing_recently``
# (still in ranked.json but UI/ranker may de-emphasise).
STALE_THRESHOLD_RUNS = 3

# PR-S4b: write to a PARALLEL file rather than overwriting the
# pre-existing ``listings_history.json``. The old file has a
# stable {key: iso_string} contract that other code paths (and
# tests/test_first_seen.py) depend on. The ledger lives at a new
# path with the richer schema; both files coexist until a future
# migration deprecates listings_history.json.
DEFAULT_LEDGER_PATH = Path("web/data/listings_ledger.json")


# ---------- Data model ----------

@dataclasses.dataclass(frozen=True)
class LedgerEntry:
    """One row in the ledger keyed by ``source|source_id``."""

    first_seen_at: str
    last_seen_at: str
    consecutive_seen_count: int
    missing_since: str | None
    existence_status: str

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "LedgerEntry":
        return cls(
            first_seen_at=d["first_seen_at"],
            last_seen_at=d.get("last_seen_at") or d["first_seen_at"],
            consecutive_seen_count=int(d.get("consecutive_seen_count", 1)),
            missing_since=d.get("missing_since"),
            existence_status=d.get("existence_status", "confirmed_current"),
        )


# ---------- Migration: load old or new format ----------

def load_ledger(path: Path) -> dict[str, LedgerEntry]:
    """Read the ledger JSON. Migrates plain-string entries (old schema:
    ``{key: iso_string}``) to the new dict schema in memory. The on-disk
    file isn't rewritten here — caller does that via ``save_ledger``."""
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, LedgerEntry] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            # Old schema — value is the first_seen_at ISO string.
            out[key] = LedgerEntry(
                first_seen_at=value,
                last_seen_at=value,
                consecutive_seen_count=1,
                missing_since=None,
                existence_status="confirmed_current",
            )
        elif isinstance(value, dict):
            try:
                out[key] = LedgerEntry.from_dict(value)
            except (KeyError, TypeError):
                continue
    return out


def save_ledger(ledger: dict[str, LedgerEntry], path: Path) -> None:
    """Write the ledger JSON. Atomically via a temp file + rename so
    a crash mid-write doesn't corrupt the file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {k: v.to_dict() for k, v in ledger.items()}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------- Per-listing state computation ----------

def compute_state(
    *,
    prior: LedgerEntry | None,
    is_present: bool,
    source_succeeded: bool,
    tick_iso: str,
) -> LedgerEntry:
    """Pure function: given a prior ledger entry (or None for never-seen)
    and the current nightly's observation, return the new entry.

    Args:
        prior: the previous nightly's entry, or None for a listing
            being seen for the first time.
        is_present: did the listing appear in this nightly's scrape?
        source_succeeded: did the scraper for this source run
            successfully? When False, ``is_present=False`` is NOT
            interpreted as missing — the listing's state is carried
            forward unchanged (the scraper failed, not the listing).
        tick_iso: ISO-8601 timestamp for this tick.

    Returns:
        The new ledger entry.
    """
    # First-ever observation: must be present (otherwise we wouldn't
    # have a key for it). Initialize.
    if prior is None:
        return LedgerEntry(
            first_seen_at=tick_iso,
            last_seen_at=tick_iso,
            consecutive_seen_count=1,
            missing_since=None,
            existence_status="confirmed_current",
        )

    if is_present:
        # Listing is back. Reset missing tracker.
        return LedgerEntry(
            first_seen_at=prior.first_seen_at,
            last_seen_at=tick_iso,
            consecutive_seen_count=prior.consecutive_seen_count + 1,
            missing_since=None,
            existence_status="confirmed_current",
        )

    # Listing is absent.
    if not source_succeeded:
        # Scraper failed; carry state forward unchanged. The listing
        # might be fine — we just don't know this tick.
        return prior

    # Source succeeded but this listing wasn't in results → genuinely
    # missing this tick.
    new_missing_since = prior.missing_since or tick_iso
    # How many consecutive nightlies has it been missing?
    # Reset the seen counter; the new field is implicit via the
    # delta tick_iso → missing_since.
    missing_streak = _count_consecutive_runs_since(new_missing_since, tick_iso)
    if missing_streak >= STALE_THRESHOLD_RUNS:
        status = "stale"
    else:
        status = "missing_recently"
    return LedgerEntry(
        first_seen_at=prior.first_seen_at,
        last_seen_at=prior.last_seen_at,
        consecutive_seen_count=0,
        missing_since=new_missing_since,
        existence_status=status,
    )


def _count_consecutive_runs_since(missing_since_iso: str, tick_iso: str) -> int:
    """Approximate consecutive-nightly count from ISO timestamps.

    A real implementation might walk a per-source ticks log; for the
    JSON-files-in-git architecture we approximate from elapsed days.
    A 24h-cadence nightly: 1 day apart = 1 missing run, etc. Rounds
    down to be conservative (don't prematurely flip to stale)."""
    import datetime as dt
    try:
        ms = dt.datetime.fromisoformat(missing_since_iso.replace("Z", "+00:00"))
        tk = dt.datetime.fromisoformat(tick_iso.replace("Z", "+00:00"))
        delta = (tk - ms).total_seconds() / 86400.0
        # +1 because the missing_since tick is itself a missing run.
        return max(1, int(delta) + 1)
    except (ValueError, TypeError):
        return 1


# ---------- Bulk update from a nightly's listings ----------

def update_ledger(
    *,
    ledger: dict[str, LedgerEntry],
    present_keys_by_source: t.Mapping[str, set[str]],
    succeeded_sources: t.AbstractSet[str],
    tick_iso: str,
) -> dict[str, LedgerEntry]:
    """Apply one nightly's worth of observations to the ledger.

    Args:
        ledger: in-memory ledger (from ``load_ledger``).
        present_keys_by_source: ``{source: set of source_ids}`` —
            listings that appeared in this nightly per source.
        succeeded_sources: set of source slugs whose scraper completed
            successfully (regardless of yield). Used to decide whether
            "absence" is genuine missing or scraper-failure.
        tick_iso: ISO-8601 for this nightly.

    Returns:
        A new ledger dict (the input is not mutated).
    """
    out: dict[str, LedgerEntry] = {}

    # Build the universe of (source, source_id) keys we care about:
    # everything in the ledger + everything newly present.
    all_keys: set[str] = set(ledger.keys())
    for source, source_ids in present_keys_by_source.items():
        for sid in source_ids:
            all_keys.add(f"{source}|{sid}")

    for key in all_keys:
        try:
            source = key.split("|", 1)[0]
        except IndexError:
            continue
        prior = ledger.get(key)
        is_present = key in {
            f"{source}|{sid}"
            for sid in present_keys_by_source.get(source, set())
        }
        succeeded = source in succeeded_sources
        new_entry = compute_state(
            prior=prior,
            is_present=is_present,
            source_succeeded=succeeded,
            tick_iso=tick_iso,
        )
        out[key] = new_entry
    return out


# ---------- Read-side helpers ----------

def get_first_seen_at(ledger: dict[str, LedgerEntry], key: str) -> str | None:
    """Backwards-compat: returns the first_seen_at for a key, or None."""
    entry = ledger.get(key)
    return entry.first_seen_at if entry else None


def stale_keys(ledger: dict[str, LedgerEntry]) -> set[str]:
    """Convenience: return all keys whose existence_status is 'stale'.
    Ranker uses this to exclude."""
    return {k for k, v in ledger.items() if v.existence_status == "stale"}
