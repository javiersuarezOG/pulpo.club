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
