"""Structural guards on the manifest's ``named_beaches`` table.

The table is asserted, never verified: every consumer (the
``dist_beach_km`` haversine grid AND the LLM prompt's AUTHORITATIVE BEACH
COORDINATES block) trusts it by construction, so a bad entry is silently
wrong in two systems at once. In Aug 2026 a contiguous run of the La
Libertad coast was found sitting 12-49 km west of the real beaches, having
been geocoded onto same-named inland features ('Caserio El Sunzal' rather
than 'Playa El Sunzal').

These are cheap structural invariants, not a gazetteer check — the live
cross-check is ``scripts/audit_named_beach_coords.py``, which is a
development tool and deliberately NOT a CI gate (it hits a third-party
endpoint and would make the suite network-dependent and flaky).
"""
from __future__ import annotations

import pytest

from pulpo.countries import active, loaded


def _beaches():
    return active().named_beaches()


def test_table_is_non_empty_and_well_formed():
    for name, lat, lng in _beaches():
        assert isinstance(name, str) and name.strip(), name
        assert isinstance(lat, float) and isinstance(lng, float), name


@pytest.mark.parametrize("manifest", loaded(), ids=lambda m: m.code)
def test_every_beach_sits_inside_its_country_bbox(manifest):
    """A beach outside the country bbox is a data-entry error, and it would
    also fail the enrichment latlong validator downstream."""
    bbox = manifest.bbox()
    (lat_lo, lat_hi) = bbox["lat"]
    (lng_lo, lng_hi) = bbox["lng"]
    for name, lat, lng in manifest.named_beaches():
        assert lat_lo <= lat <= lat_hi, (manifest.code, name, lat)
        assert lng_lo <= lng <= lng_hi, (manifest.code, name, lng)


def test_no_two_beaches_share_a_coordinate():
    """Identical coordinates mean a placeholder was committed.

    Playa El Tamarindo / Playa Maculis / Playa Torola all carried
    13.2050,-87.8420 until Aug 2026 — three distinct beaches collapsed onto
    one point, which silently degrades every haversine that resolves to it.
    """
    seen: dict[tuple[float, float], str] = {}
    dupes = []
    for name, lat, lng in _beaches():
        key = (round(lat, 4), round(lng, 4))
        if key in seen:
            dupes.append(f"{name} == {seen[key]} @ {key}")
        seen[key] = name
    assert not dupes, "duplicate beach coordinates: " + "; ".join(dupes)


def test_names_are_unique():
    names = [n for n, _, _ in _beaches()]
    dupes = {n for n in names if names.count(n) > 1}
    assert not dupes, f"duplicate beach names: {dupes}"


def test_table_is_ordered_west_to_east():
    """``docs/named-beach-reference.md`` specifies loose west-to-east order.

    Keeping it sorted makes a misplaced entry visible on inspection: the
    2026 drift showed up as El Majahual sitting west of El Sunzal, which is
    backwards on the real coast.
    """
    lngs = [lng for _, _, lng in _beaches()]
    assert lngs == sorted(lngs), "named_beaches must stay sorted west->east by lng"


@pytest.mark.parametrize(
    "name,lat,lng",
    [
        # Regression pins for the Aug 2026 correction. Each was verified
        # against multiple independent OSM features; see the audit tool and
        # the PR body for the per-entry evidence.
        ("El Tunco", 13.4926, -89.3829),
        ("El Sunzal", 13.4942, -89.3949),
        ("El Zonte", 13.4939, -89.4386),
        ("El Majahual", 13.4919, -89.3649),
        ("Bocana San Diego", 13.4710, -89.2628),
        ("Mizata", 13.5105, -89.5964),
    ],
)
def test_corrected_la_libertad_cluster_stays_corrected(name, lat, lng):
    """Pin the surf cluster so a future edit cannot silently re-drift it.

    These sit in the densest listing zone we have, and they anchor the LLM
    prompt, so regressing one of them re-contaminates newly geocoded
    listings.
    """
    entry = next((b for b in _beaches() if b[0] == name), None)
    assert entry is not None, f"{name} vanished from named_beaches"
    assert entry[1] == pytest.approx(lat, abs=1e-4), name
    assert entry[2] == pytest.approx(lng, abs=1e-4), name
