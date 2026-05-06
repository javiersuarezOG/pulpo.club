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
        "coastal_only": False,
        "pill_bg":   "#E1F5EE",
        "pill_text": "#085041",
        "title_canonical_template": "Raw Land · {zone}",
    },
    "house": {
        "label":     "Beach house",
        "label_es":  "Casa de playa",
        "coastal_only": True,
        "pill_bg":   "#FAECE7",
        "pill_text": "#712B13",
        "title_canonical_template": "Beach House · {zone}",
    },
    "condo": {
        "label":     "Beach condo",
        "label_es":  "Apartamento de playa",
        "coastal_only": True,
        "pill_bg":   "#FAEEDA",
        "pill_text": "#633806",
        "title_canonical_template": "Beach Condo · {zone}",
    },
}

COASTAL_ZONES: frozenset[str] = frozenset({
    "el-tunco", "el-sunzal", "el-zonte", "san-diego", "mizata",
    "el-cuco", "las-flores", "punta-mango", "el-espino", "conchagua",
    "jiquilisco", "tamanique", "costa-del-sol", "atami",
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

# Beachfront-keyword fallback: a house/condo with no resolved coastal zone
# but title/description containing one of these terms passes the coastal
# filter. Kept conservative on purpose — false positives here let inland
# built listings through.
BEACHFRONT_KEYWORDS: list[str] = [
    r"\bfrente\s+al\s+mar\b",
    r"\bbeach[- ]?front\b",
    r"\bocean[- ]?front\b",
    r"\bvista\s+al\s+mar\b",
    r"\boceanfront\b",
    r"\bplaya\b",
]


def label_for(ptype: str, *, lang: str = "en") -> str:
    """Public accessor — returns label or label_es. Falls back to land."""
    cfg = PROPERTY_TYPES.get(ptype) or PROPERTY_TYPES["land"]
    return cfg["label_es" if lang == "es" else "label"]


def is_known_type(ptype: str) -> bool:
    return ptype in PROPERTY_TYPES
