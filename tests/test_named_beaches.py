"""Sanity tests for automation/distance_fields.NAMED_BEACHES.

The audit flagged this: NAMED_BEACHES is the single source of truth that
feeds both the dist_beach_km haversine grid AND the LLM enrichment
prompt's authoritative beach-coordinate block. A swapped sign or
fat-fingered digit there silently shifts coordinates by hundreds of
kilometres — and worse, the LLM happily anchors new listings to the bad
coords, propagating the error onto every coastal scrape.

The tests below are cheap regression-prevention. They don't replace
human review of an entry, but they fail loudly on the failure modes
that are easy to make and hard to spot:

  - lat/lng outside El Salvador's bounding box (typo / sign flip)
  - duplicate beach NAME (copy-paste lazy)
  - non-numeric coordinates (string in the tuple, etc.)

We DO allow duplicate coordinates because the table intentionally pins
multiple named bays at the same anchor (e.g. Playa Maculís sits inside
the Tamarindo bay block).
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.distance_fields import (   # noqa: E402
    COASTLINE_POINTS,
    NAMED_BEACHES,
)

# El Salvador bounding box, padded ~0.1° (~11 km) at every edge so a
# slightly-offshore reef anchor isn't a false alarm. Real-world ES is
# roughly:  lat 13.15–14.45, lng -90.13 to -87.69.
ES_LAT_MIN, ES_LAT_MAX = 13.05, 14.55
ES_LNG_MIN, ES_LNG_MAX = -90.25, -87.55


def test_named_beaches_has_entries():
    """If someone empties the list by accident the haversine grid quietly
    starts returning the default unscored value — every coastal listing
    would suddenly report dist_beach_km = None. Fail loudly instead."""
    assert len(NAMED_BEACHES) >= 20, (
        f"NAMED_BEACHES has only {len(NAMED_BEACHES)} entries — well below "
        "the ~35 baseline. Did a refactor accidentally truncate the tuple?"
    )


def test_every_entry_is_well_formed():
    """Each row is (name: str, lat: float, lng: float). A string in the
    coord slot raises later when haversine does arithmetic; catch it here."""
    for entry in NAMED_BEACHES:
        assert len(entry) == 3, f"malformed entry: {entry!r}"
        name, lat, lng = entry
        assert isinstance(name, str) and name, f"bad name: {entry!r}"
        assert isinstance(lat, (int, float)), f"non-numeric lat: {entry!r}"
        assert isinstance(lng, (int, float)), f"non-numeric lng: {entry!r}"


def test_every_beach_is_inside_el_salvador_bbox():
    """The most likely typo class: someone fat-fingers a coordinate and
    a Playa El Cuco beach ends up in the Atlantic, or a sign flip sends
    El Tunco to the eastern Pacific. Either case off-anchors the listing
    by hundreds of km and would silently propagate through dist_beach_km
    + the LLM prompt anchor table."""
    out_of_bounds: list[str] = []
    for name, lat, lng in NAMED_BEACHES:
        if not (ES_LAT_MIN <= lat <= ES_LAT_MAX):
            out_of_bounds.append(
                f"{name}: lat={lat} outside [{ES_LAT_MIN}, {ES_LAT_MAX}]"
            )
        if not (ES_LNG_MIN <= lng <= ES_LNG_MAX):
            out_of_bounds.append(
                f"{name}: lng={lng} outside [{ES_LNG_MIN}, {ES_LNG_MAX}]"
            )
    assert not out_of_bounds, (
        "NAMED_BEACHES entries outside the El Salvador bounding box "
        "(suggests a typo / sign flip):\n  " + "\n  ".join(out_of_bounds)
    )


def test_no_duplicate_beach_names():
    """Two rows sharing a name are an accidental copy-paste — one would
    silently win in any name-keyed lookup. Coordinate duplication IS
    allowed (multiple named bays at the same anchor — see the Tamarindo
    block) and is intentional, so we only police names here."""
    names = [n for n, _, _ in NAMED_BEACHES]
    seen: set[str] = set()
    dupes: list[str] = []
    for n in names:
        if n in seen:
            dupes.append(n)
        seen.add(n)
    assert not dupes, f"duplicate beach names in NAMED_BEACHES: {dupes}"


def test_coastline_points_alias_matches_named_beaches():
    """COASTLINE_POINTS is a backward-compat alias derived from
    NAMED_BEACHES. Length + coordinate alignment must stay locked so a
    future edit doesn't accidentally drop one of the two consumers."""
    assert len(COASTLINE_POINTS) == len(NAMED_BEACHES)
    for (_, lat, lng), (alias_lat, alias_lng) in zip(
        NAMED_BEACHES, COASTLINE_POINTS,
    ):
        assert (lat, lng) == (alias_lat, alias_lng)
