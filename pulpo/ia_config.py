"""
Pulpo Information Architecture — single source of truth.

The new homepage + browse rewrite organizes listings around two axes:

    master_category × subcategory
    ──────────────────────────────
    beach × {homes, condos, land}
    lake  × {homes, condos, land}

Plus a four-tag discovery layer:

    {top_rated, under_250k, gated, waterfront}

Every UI surface (homepage category grid, browse filter chips, newsletter
template, detail page breadcrumb) reads from this module. The TypeScript
mirror at ``web/app/config/ia.ts`` re-exports identical literals so the
frontend narrows correctly.

Threshold rationale:

- ``TOP_RATED_MIN_RANK_SCORE = 70`` — matches Q5 of the rewrite plan
  (4.0★ in the star bins, ≈ top quartile of the catalog). The featured-
  listing elite pool uses 75; the discovery tag is looser so users can
  see a meaningful "top rated" shelf when they click the pill.

- ``UNDER_250K_USD = 250_000`` — Salvadoran median land-asset listing
  is in the $80k–$300k band; $250k cleaves the catalog roughly in half.

- ``BEACH_PROXIMITY_KM = 5`` — `dist_beach_km` haversine to the nearest
  named beach. Wider than the on-foot ``walk_to_beach`` tier (≈ 1km) so
  buyers shopping for "in the neighborhood" listings still land in the
  beach master-category.

Tile copy is bilingual at write-time (Q1 of the rewrite plan); the
TypeScript mirror reads the same dicts so a single edit propagates.
"""
from __future__ import annotations
from typing import Literal


# ── Master + subcategory enums ────────────────────────────────────────

MasterCategory = Literal["beach", "lake"]
Subcategory    = Literal["homes", "condos", "land"]
DiscoveryTag   = Literal["top_rated", "under_250k", "gated", "waterfront"]

MASTER_CATEGORIES: tuple[MasterCategory, ...] = ("beach", "lake")
SUBCATEGORIES:     tuple[Subcategory, ...]    = ("homes", "condos", "land")
DISCOVERY_TAGS:    tuple[DiscoveryTag, ...]   = (
    "top_rated", "under_250k", "gated", "waterfront",
)


# ── Thresholds (also consumed by derive_discovery_tags) ───────────────

TOP_RATED_MIN_RANK_SCORE: float = 70.0
UNDER_250K_USD:           float = 250_000.0
BEACH_PROXIMITY_KM:       float = 5.0


# ── Star rating bins ──────────────────────────────────────────────────
#
# rank_score (0..100) → star rating in 0.5 increments capped at 5.0.
# Bins per Q5 of the rewrite plan; half-stars sit at the midpoint of
# each whole-star band. The 5-star band has no half-step (the cap is
# 5.0 — there's no 5.5).
#
# Lookup is descending: first threshold met wins. Keep this list
# sorted by threshold descending so the lookup remains O(N) with a
# tiny N.

STAR_BINS: tuple[tuple[float, float], ...] = (
    (85.0, 5.0),
    (78.0, 4.5),
    (70.0, 4.0),
    (60.0, 3.5),
    (50.0, 3.0),
    (38.0, 2.5),
    (25.0, 2.0),
    (13.0, 1.5),
    (1.0,  1.0),
)


# ── Beach vs. lake zone-slug rule ─────────────────────────────────────

# A zone slug starting with this prefix is treated as a lake property.
# Current matches: "lago-coatepeque", "lago-ilopango". When normalize.py
# adds more lake zones, the prefix rule continues to work without an
# enum update here.
LAKE_ZONE_SLUG_PREFIX: str = "lago-"


# ── Bilingual tile copy (homepage category grid) ──────────────────────
#
# Keyed by (master_category, subcategory). Each value is a {en, es}
# dict; the TypeScript mirror reads the same keys. Edit copy here, not
# in the React component — the component is locale-agnostic.

TILE_COPY: dict[tuple[MasterCategory, Subcategory], dict[str, str]] = {
    ("beach", "homes"): {
        "en": "Move-in-ready houses on the Pacific coast.",
        "es": "Casas listas para habitar en la costa del Pacífico.",
    },
    ("beach", "condos"): {
        "en": "Apartments within walking distance of surf.",
        "es": "Apartamentos a pasos del surf.",
    },
    ("beach", "land"): {
        "en": "Buildable plots near the ocean.",
        "es": "Terrenos para construir cerca del mar.",
    },
    ("lake", "homes"): {
        "en": "Houses on Coatepeque, Ilopango, Suchitlán.",
        "es": "Casas en Coatepeque, Ilopango, Suchitlán.",
    },
    ("lake", "condos"): {
        "en": "Waterfront apartments and shared developments.",
        "es": "Apartamentos junto al lago y desarrollos compartidos.",
    },
    ("lake", "land"): {
        "en": "Plots with direct access or lake views.",
        "es": "Terrenos con acceso directo o vista al lago.",
    },
}


# ── Discovery pill copy ───────────────────────────────────────────────

DISCOVERY_PILL_LABELS: dict[DiscoveryTag, dict[str, str]] = {
    "top_rated":  {"en": "Top rated",   "es": "Mejor valorados"},
    "under_250k": {"en": "Under $250K", "es": "Menos de $250K"},
    "gated":      {"en": "Gated",       "es": "Privado / cerrado"},
    "waterfront": {"en": "Waterfront",  "es": "Frente al agua"},
}


# Section headers on the homepage category grid.
MASTER_CATEGORY_LABELS: dict[MasterCategory, dict[str, str]] = {
    "beach": {"en": "Beach properties", "es": "Propiedades de playa"},
    "lake":  {"en": "Lake properties",  "es": "Propiedades de lago"},
}

# Subcategory labels (tile title above the description).
SUBCATEGORY_LABELS: dict[Subcategory, dict[str, str]] = {
    "homes":  {"en": "Homes",  "es": "Casas"},
    "condos": {"en": "Condos", "es": "Condominios"},
    "land":   {"en": "Land",   "es": "Terrenos"},
}
