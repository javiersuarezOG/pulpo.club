"""Single source of truth for property-type metadata.

Read by:
  - pulpo/scrapers/_type_classifier.py (keywords, place-name exclusions)
  - automation/run.py (label / template / pill colour for last_updated.json)
  - web/assets/index.js (label / pill colour, mirrored — kept in sync via tests)

When adding a new type, every consumer above must be checked. The shape is
deliberately small so future per-type bounds + ranker config can extend it
without coupling.
"""
from __future__ import annotations

PROPERTY_TYPES: dict[str, dict] = {
    "land": {
        "label":     "Land",
        "label_es":  "Terreno",
        "vacation_only": False,
        "pill_bg":   "#E1F5EE",
        "pill_text": "#085041",
        "title_canonical_template": "Raw Land · {zone}",
    },
    "house": {
        # Labels stay "Beach house"/"Casa de playa" today — Coatepeque +
        # Ilopango lake inventory is small (~4 unique listings as of
        # 2026-05-08 recon) and the marketing surface is still beach-
        # focused. Revisit when lake inventory crosses ~20 listings; the
        # right answer at that point is probably zone-conditional labels
        # ("Lake House · Coatepeque" vs "Beach House · El Tunco") rather
        # than a generic "Vacation House" downgrade. Tracked in CLAUDE.md.
        "label":     "Beach house",
        "label_es":  "Casa de playa",
        "vacation_only": True,
        "pill_bg":   "#FAECE7",
        "pill_text": "#712B13",
        "title_canonical_template": "Beach House · {zone}",
    },
    "condo": {
        "label":     "Beach condo",
        "label_es":  "Apartamento de playa",
        "vacation_only": True,
        "pill_bg":   "#FAEEDA",
        "pill_text": "#633806",
        "title_canonical_template": "Beach Condo · {zone}",
    },
}

# Geographic gate for `vacation_only` property types (house + condo).
# House/condo listings outside these zones — without a waterfront keyword
# in title/description — are dropped at parse time as "inland built".
# Land has no such filter (inland lots are valid inventory).
#
# Renamed from COASTAL_ZONES (2026-05-08) to broaden semantics from "ocean
# coast" to "vacation/waterfront destinations". Two lake additions
# (`lago-coatepeque`, `lago-ilopango`) join the original 14 ocean-coast
# zones. Lakes match the same buyer profile (vacation/second-home) and
# field shape (bedrooms, bathrooms, built area), so the existing per-type
# ranker + zone-median pipelines fold them in without further changes.
#
# Note: `automation/validation_bounds.py` keeps a separate (and
# narrower) COASTAL_ZONES set — that one drives a coastal-specific
# fraud-detection rule (very-large-parcel suspicion in supply-limited
# beach zones). Lake parcels can legitimately be large, so that set
# stays strictly ocean-coast.
VACATION_ZONES: frozenset[str] = frozenset({
    # Ocean coast
    "el-tunco", "el-sunzal", "el-zonte", "san-diego", "mizata",
    "el-cuco", "las-flores", "punta-mango", "el-espino", "conchagua",
    "jiquilisco", "tamanique", "costa-del-sol", "atami",
    # Lake (added 2026-05-08; see live recon in commit message)
    "lago-coatepeque", "lago-ilopango",
})

# Type keyword regex map — used by the multi-signal classifier.
# Word-boundary matching only; never substring `in` checks. The patterns are
# raw strings; the classifier compiles + applies them with re.IGNORECASE.
TYPE_KEYWORDS: dict[str, list[str]] = {
    "land":  [r"\bterrenos?\b", r"\blotes?\b", r"\blots?\b", r"\bland\b",
              r"\bfincas?\b", r"\bparcelas?\b", r"\btierra\b", r"\branchos?\b",
              r"\bhaciendas?\b"],
    "house": [r"\bcasas?\b", r"\bhouses?\b", r"\bvillas?\b",
              r"\bresidenc[ai]s?\b", r"\bchalets?\b",
              r"\bbeach[- ]?house\b"],
    "condo": [r"\bapartamentos?\b", r"\bapartments?\b",
              r"\bcondominios?\b", r"\bcondominiums?\b", r"\bcondos?\b",
              r"\bdepartamentos?\b", r"\bdepas?\b", r"\blofts?\b"],
}

# Place-name exclusion list — when a type keyword appears as part of these
# named developments / municipalities, do NOT count it as a type signal.
# El Salvador real estate uses "Villa X" extensively as a development name
# (Villa Bosque, Villa Tuscania, San José Villanueva). 7/8 word-boundary
# `\bvillas?\b` matches in current goodlife data are place names, not villa
# structures — hence the strict exclusion list applied before keyword scoring.
PLACE_NAME_EXCLUSIONS: list[str] = [
    r"\bvilla\s+(bosque|tuscania|esmeralda|las\s+delicias|de\s+apaneca|de\s+luxe|nueva)\b",
    r"\bvillas?\s+de\s+\w+",
    r"\bvillanueva\b",
    r"\bbah[ií]a\s+villas?\b",
]

# Waterfront-keyword fallback: a house/condo with no resolved vacation
# zone but title/description containing one of these terms passes the
# geographic filter. Kept conservative on purpose — false positives
# here let inland built listings through.
#
# Renamed from BEACHFRONT_KEYWORDS (2026-05-08) — added 4 lake terms
# alongside the original 6 beach terms. The semantic is "this listing
# is on the water (ocean or lake)"; specific waterbody is incidental.
WATERFRONT_KEYWORDS: list[str] = [
    # Ocean / beach
    r"\bfrente\s+al\s+mar\b",
    r"\bbeach[- ]?front\b",
    r"\bocean[- ]?front\b",
    r"\bvista\s+al\s+mar\b",
    r"\boceanfront\b",
    r"\bplaya\b",
    # Lake (Coatepeque, Ilopango — added 2026-05-08)
    r"\bfrente\s+al\s+lago\b",
    r"\bvista\s+al\s+lago\b",
    r"\borillas?\s+del\s+lago\b",
    r"\blakefront\b",
]


def label_for(ptype: str, *, lang: str = "en") -> str:
    """Public accessor — returns label or label_es. Falls back to land."""
    cfg = PROPERTY_TYPES.get(ptype) or PROPERTY_TYPES["land"]
    return cfg["label_es" if lang == "es" else "label"]


def is_known_type(ptype: str) -> bool:
    return ptype in PROPERTY_TYPES
