"""Tests for automation/ig_priors.py — cross-surface (website) priors.

Synthetic, deterministic, offline. Covers intent weighting, the listing→
category/zone join, the cold-start (MIN_LISTINGS) guard, normalization,
the PostHog soft-fail, and run() writing the artifact.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_priors import (   # noqa: E402
    MIN_LISTINGS,
    build_priors,
    fetch_listing_intent,
)


def _index(n, color, zone, prefix):
    return {f"{prefix}{i}": {"color_key": color, "zone": zone} for i in range(n)}


def _intent(n, clicks, paywall, prefix):
    return {f"{prefix}{i}": {"clicks": clicks, "paywall_hits": paywall} for i in range(n)}


# ── intent weighting + trust ───────────────────────────────────────────

def test_paywall_intent_outweighs_clicks():
    idx = {**_index(MIN_LISTINGS, "casas_playa", "z1", "a"),
           **_index(MIN_LISTINGS, "terrenos_lago", "z2", "b")}
    # A: paywall hits only; B: the same COUNT of plain clicks
    intent = {**_intent(MIN_LISTINGS, 0, 2, "a"),
              **_intent(MIN_LISTINGS, 2, 0, "b")}
    p = build_priors(intent, idx)
    cats = p["categories"]
    assert cats["casas_playa"]["trusted"] and cats["terrenos_lago"]["trusted"]
    assert cats["casas_playa"]["weight"] > cats["terrenos_lago"]["weight"]
    assert p["leaders"]["category"] == "casas_playa"


def test_untrusted_below_min_listings_is_neutral():
    idx = _index(MIN_LISTINGS - 1, "apartamentos", "z9", "c")
    intent = _intent(MIN_LISTINGS - 1, 5, 5, "c")
    p = build_priors(intent, idx)
    e = p["categories"]["apartamentos"]
    assert e["trusted"] is False
    assert e["weight"] == 1.0
    assert p["leaders"]["category"] is None


def test_weight_clamped_to_range():
    # one wildly hot category, one cold — weights clamp to [0.5, 2.0]
    idx = {**_index(MIN_LISTINGS, "casas_playa", "z1", "h"),
           **_index(MIN_LISTINGS, "terrenos_lago", "z2", "l")}
    intent = {**_intent(MIN_LISTINGS, 0, 100, "h"),   # huge
              **_intent(MIN_LISTINGS, 1, 0, "l")}      # tiny
    p = build_priors(intent, idx)
    # hot ratio approaches the 2.0 cap; cold clamps to the 0.5 floor
    assert p["categories"]["casas_playa"]["weight"] > 1.9
    assert p["categories"]["terrenos_lago"]["weight"] == 0.5


def test_listings_without_index_entry_are_skipped():
    idx = _index(MIN_LISTINGS, "casas_lago", "z1", "a")   # only 'a*' known
    intent = {**_intent(MIN_LISTINGS, 1, 1, "a"),
              "ghost__1": {"clicks": 99, "paywall_hits": 99}}   # not in index
    p = build_priors(intent, idx)
    assert p["n_listings_with_signal"] == MIN_LISTINGS   # ghost skipped


def test_zone_priors_aggregate_independently():
    idx = _index(MIN_LISTINGS, "casas_playa", "la-libertad", "a")
    intent = _intent(MIN_LISTINGS, 0, 3, "a")
    p = build_priors(intent, idx)
    assert p["zones"]["la-libertad"]["trusted"] is True
    assert p["zones"]["la-libertad"]["n_listings"] == MIN_LISTINGS


# ── PostHog reader soft-fail ───────────────────────────────────────────

def test_fetch_listing_intent_maps_rows():
    # inject the query fn (no shared-module monkeypatch → immune to test order)
    rows = [{"lid": "remax__1", "clicks": 4, "paywall_hits": 2},
            {"lid": "", "clicks": 9, "paywall_hits": 9}]   # blank lid ignored
    got = fetch_listing_intent(query_fn=lambda *a, **k: rows)
    assert got == {"remax__1": {"clicks": 4, "paywall_hits": 2}}


def test_fetch_listing_intent_softfails_to_empty():
    assert fetch_listing_intent(query_fn=lambda *a, **k: None) == {}   # no key


# ── run(): writes the artifact ─────────────────────────────────────────

def test_run_writes_priors(tmp_path, monkeypatch):
    import automation.ig_priors as P
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([
        {"source": "a", "source_id": str(i), "property_type": "house",
         "dist_beach_km": 0.5, "zone": "la-libertad"} for i in range(MIN_LISTINGS)
    ]))
    out = tmp_path / "ig_priors.json"
    monkeypatch.setattr(P, "RANKED_PATH", ranked)
    monkeypatch.setattr(P, "PRIORS_ARTIFACT", out)
    # patch the module's OWN function (not the shared _pq module) so this is
    # immune to test-order pollution under pytest-randomly.
    monkeypatch.setattr(P, "fetch_listing_intent",
                        lambda **k: {f"a__{i}": {"clicks": 1, "paywall_hits": 3}
                                     for i in range(MIN_LISTINGS)})
    # call P.run (same module object as the patches) — the top-level-imported
    # run() can belong to a second import identity under pytest, so patching P
    # wouldn't reach it (the double-import gotcha).
    n = P.run()
    assert n == MIN_LISTINGS
    board = json.loads(out.read_text())
    # coastal house → casas_playa should be present + trusted
    assert board["categories"]["casas_playa"]["trusted"] is True
