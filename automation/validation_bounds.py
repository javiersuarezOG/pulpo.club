"""
Numeric bounds for listing validation.

DROP bounds: hard structural failures — the record is certainly corrupt.
FLAG bounds: suspicious but possible — kept for human review.

Edit these constants to tune thresholds; don't touch validation.py rules.
Reasoning for initial values is documented inline.
"""
from pulpo.countries import active as _active_country

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

# Coastal zones where very large parcels are suspicious (200k m² = ~28 manzanas).
#
# PR-MC-1c — source of truth moved into pulpo/countries/<cc>.json
# under the ``coastal_zones`` key. Strict-ocean subset of vacation
# zones; lakes are excluded because lake parcels can legitimately be
# large.
COASTAL_ZONES: frozenset[str] = _active_country().coastal_zones()
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
# Adding a new type or tuning bounds = edit pulpo/countries/<cc>.json
# under ``validation_bounds.<ptype>.<field>``. The per-country shape is
# {ptype: {field: (drop_min, drop_max, flag_min, flag_max)}}.
#
# PR-MC-1c — source of truth moved into the country manifest. The
# per-field comments above (e.g. "<50k for a beach house in El
# Salvador is parser error or distress") still document the SV
# calibration; the numbers themselves are read from sv.json.
BOUNDS_BY_TYPE: dict[str, dict[str, tuple[float, float, float, float]]] = (
    _active_country().validation_bounds()
)
