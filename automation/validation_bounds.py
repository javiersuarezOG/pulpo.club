"""
Numeric bounds for listing validation.

DROP bounds: hard structural failures — the record is certainly corrupt.
FLAG bounds: suspicious but possible — kept for human review.

Edit these constants to tune thresholds; don't touch validation.py rules.
Reasoning for initial values is documented inline.
"""

# ── price_usd ──────────────────────────────────────────────────────────
# El Salvador raw land below $1k with area is almost certainly a parser
# error (stray number parsed as price). Above $100M is impossible for a
# single parcel. Flag band: $5k–$20M covers genuine edge cases like tiny
# lots in dollar towns and large coastal farms.
PRICE_DROP_MIN = 1_000.0
PRICE_DROP_MAX = 100_000_000.0
PRICE_FLAG_MIN = 5_000.0
PRICE_FLAG_MAX = 20_000_000.0

# ── area_m2 ────────────────────────────────────────────────────────────
# Below 50m² is a parking space, not land. Above 10M m² (~1430 manzanas)
# doesn't exist as a single parcel in El Salvador. Flag: 100m²–1M m²
# (1M m² ≈ 143 manzanas; Jiquilisco example at 1.05M is real, flag-not-drop).
AREA_DROP_MIN = 50.0
AREA_DROP_MAX = 10_000_000.0
AREA_FLAG_MIN = 100.0
AREA_FLAG_MAX = 1_000_000.0

# ── price_per_m2 ───────────────────────────────────────────────────────
# Below $0.50/m² is either a parser error or a unit mismatch (the
# Guatemala $0.45/m² case). Above $10k/m² doesn't exist for raw land.
# Flag: $1–$5k catches the suspicious-but-possible fringe.
PPM_DROP_MIN = 0.5
PPM_DROP_MAX = 10_000.0
PPM_FLAG_MIN = 1.0
PPM_FLAG_MAX = 5_000.0

# ── days_listed ────────────────────────────────────────────────────────
DAYS_DROP_MIN = 0
DAYS_DROP_MAX = 3_650    # 10 years — listing that old is stale data
DAYS_FLAG_MAX = 1_825    # 5 years

# ── photos_count ───────────────────────────────────────────────────────
PHOTOS_DROP_MIN = 0      # negative is impossible
PHOTOS_DROP_MAX = 100    # no broker uploads 100+ photos for one lot

# ── Cross-attribute ────────────────────────────────────────────────────
# Allow 10% tolerance when comparing stored vs. computed $/m².
# A mismatch > 10% means either the price or area field is wrong.
PPM_CONSISTENCY_TOLERANCE = 0.10

# 1 manzana = 6,989 m²; flag if title says manzanas but area is under 1 mz
MANZANA_M2 = 6_989.0

# Coastal zones where very large parcels are suspicious (200k m² = ~28 manzanas)
COASTAL_ZONES = frozenset({
    "el-tunco", "el-sunzal", "el-zonte", "san-diego", "mizata",
    "el-cuco", "las-flores", "punta-mango", "el-espino", "conchagua",
    "jiquilisco",
})
COASTAL_LARGE_AREA_M2 = 200_000.0

# Stale + photoless: old listing with zero photos is likely dead inventory
STALE_PHOTOLESS_DAYS = 730


# ── Per-type bounds (PRD: BOUNDS_BY_TYPE) ──────────────────────────────
# Bounds keyed by property_type. Each entry: (drop_min, drop_max, flag_min, flag_max).
# Land bounds = the flat constants above (no behaviour change for the 815
# production land listings). House + condo bounds defined per the original
# property-types redesign spec; calibrated against current bienesraices +
# goodlife data so no current listing is incorrectly dropped.
#
# Rule semantics (in validation.py::_rule_type_bounds):
#   value < drop_min OR value > drop_max  →  DROP   (record is corrupt)
#   value < flag_min OR value > flag_max  →  FLAG   (suspicious-but-possible)
#   field absent on listing               →  skip   (don't fault on missing data)
#
# Adding a new type here is enough — _rule_type_bounds reads this dict
# directly. No code change needed.
BOUNDS_BY_TYPE: dict[str, dict[str, tuple[float, float, float, float]]] = {
    "land": {
        "price_usd":      (PRICE_DROP_MIN, PRICE_DROP_MAX, PRICE_FLAG_MIN, PRICE_FLAG_MAX),
        "area_m2":        (AREA_DROP_MIN,  AREA_DROP_MAX,  AREA_FLAG_MIN,  AREA_FLAG_MAX),
        "price_per_m2":   (PPM_DROP_MIN,   PPM_DROP_MAX,   PPM_FLAG_MIN,   PPM_FLAG_MAX),
    },
    "house": {
        # Sale prices: under $50k for a beach house in El Salvador is
        # parser error or distress. Over $10M is luxury-villa territory
        # (real but worth flagging). Flag: $100k–$5M is the working band.
        "price_usd":      (50_000,    10_000_000,    100_000,    5_000_000),
        # Built area: <50 m² isn't a livable house. >2000 m² is a small
        # hotel. Flag band keeps mainstream homes (80–1000 m²) silent.
        "built_area_m2":  (50,        2_000,         80,         1_000),
        # Lot area (the area_m2 field for a house = the lot the house is on):
        # <100 m² is implausibly small. >50,000 m² is an estate.
        "area_m2":        (100,       50_000,        200,        10_000),
        # Bedrooms: 0 means studio (rare in beach houses, drop). 15+ is
        # a hotel or data error. Flag at 11+ catches multi-family compounds.
        "bedrooms":       (1,         15,            1,          10),
        # Bathrooms: 0.5 (a single half-bath house) is implausible.
        "bathrooms":      (0.5,       15,            1,          10),
    },
    "condo": {
        # Condos run cheaper than detached houses; under $30k is parser
        # error. Above $5M is rare luxury (flag, don't drop).
        "price_usd":      (30_000,    5_000_000,     70_000,     2_000_000),
        # Built area: <30 m² isn't a livable unit. >1000 m² is penthouse
        # territory and worth a flag.
        "built_area_m2":  (30,        1_000,         50,         500),
        # Bedrooms: 0 = studio (legitimate for condos, unlike houses).
        "bedrooms":       (0,         10,            0,          6),
        # HOA: $0 is fine (some buildings have no HOA). $5k+/month is
        # a parser error or a very high-end rental conflated with a sale.
        "hoa_fee_usd_monthly": (0,    5_000,         0,          2_000),
    },
}
