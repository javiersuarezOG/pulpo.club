"""IG-display unit formatters — single source of truth for the gold rule.

The gold rule for everything Pulpo posts to Instagram (poster, caption,
queue, review page): only three unit families are allowed in user-facing
strings.

  - Area:     square metres only.  "19,000 m²".  Never "1.9 ha", "11 mz",
              "211,362 m² (30 mz)".
  - Price:    USD only.  "$667,295" for < $1M, "$2.5M" for ≥ $1M (one
              decimal max).  Never colones, never "USD 455K".
  - Distance: km for ≥ 1 km ("1.4 km"), m for < 1 km ("760 m").  Never
              miles, varas, or "10 min de auto" as a stand-in.

Every ig_* module imports its formatters from here.  Tests in
tests/test_ig_units.py cover each case from the gold rule documented in
the original product brief, and a CI grep test (added in the same PR)
rejects raw `f"{x} m²"`/`.toFixed(`/`{x}/m²` patterns from ig_* code so
nobody slips a direct format past this gate.
"""
from __future__ import annotations

# Conversion constants — used to retrofit any legacy raw_size_text the
# pipeline left in non-m² units, and as reference for unit_audit().
MANZANA_M2 = 6988.96          # 1 mz (El Salvador standard)
HECTAREA_M2 = 10_000.0
VARA2_M2 = 0.698896           # 1 vara² (1 vara ≈ 0.8359 m)

# Public placeholder for missing values.  Matches the "—" used by the
# frontend formatPpm/formatSize helpers (web/app/components.jsx).
MISSING = "—"


# ── conversions (raw → m²) ─────────────────────────────────────────────

def mz_to_m2(mz: float) -> float:
    """Convert manzanas (Central American land unit) to m²."""
    return mz * MANZANA_M2


def ha_to_m2(ha: float) -> float:
    return ha * HECTAREA_M2


def vara2_to_m2(v2: float) -> float:
    return v2 * VARA2_M2


# ── internal helpers ───────────────────────────────────────────────────

def _round_area_for_display(area_m2: float) -> int:
    """Round area to a display-appropriate precision.

    Sub-10k stays exact (a 4,555 m² lot shouldn't become 4,500).  Above
    10k we drop noise digits — a 18,917 m² lot the source called "1.9 ha"
    reads as "19,000 m²", not as false-precision "18,917 m²".

      <       10,000 → nearest 1     (e.g.   4,555 → 4,555)
       10,000–99,999 → nearest 1,000 (      18,917 → 19,000)
      100,000–999,999→ nearest 10,000 (    209,669 → 210,000)
      ≥    1,000,000 → nearest 100,000 (1,243,000 → 1,200,000)
    """
    if area_m2 < 10_000:
        return int(round(area_m2))
    if area_m2 < 100_000:
        return int(round(area_m2 / 1_000) * 1_000)
    if area_m2 < 1_000_000:
        return int(round(area_m2 / 10_000) * 10_000)
    return int(round(area_m2 / 100_000) * 100_000)


def _strip_trailing_zero_decimal(s: str) -> str:
    """'2.0' → '2', '2.50' → '2.5', '2.05' → '2.05'."""
    if "." not in s:
        return s
    head, tail = s.split(".", 1)
    tail = tail.rstrip("0")
    return head if not tail else f"{head}.{tail}"


# ── formatters (the public API) ────────────────────────────────────────

def format_area_m2(area_m2: float | int | None) -> str:
    """'19,000 m²' / '4,555 m²' / '210,000 m²' / '—' if None.

    Negative / zero values render as '—' (defensive — area_m2 should never
    be negative in ranked.json, but if it is, '0 m²' is misleading and
    we'd rather show MISSING)."""
    if area_m2 is None:
        return MISSING
    try:
        val = float(area_m2)
    except (TypeError, ValueError):
        return MISSING
    if val <= 0:
        return MISSING
    rounded = _round_area_for_display(val)
    return f"{rounded:,} m²"


def format_price_usd(price: float | int | None) -> str:
    """'$667,295' for < $1M, '$2.5M' for ≥ $1M.

    Strips trailing '.0' so $1,000,000 reads '$1M' not '$1.0M'.  Sub-$1
    inputs (defensive) render as '—' since IG never advertises prices
    below the dollar."""
    if price is None:
        return MISSING
    try:
        val = float(price)
    except (TypeError, ValueError):
        return MISSING
    if val < 1:
        return MISSING
    if val < 1_000_000:
        return f"${int(round(val)):,}"
    millions = val / 1_000_000
    # One decimal max.  '%g' would drop 1.10 → 1.1 but also 1.0 → 1,
    # which is the behaviour we want here.
    formatted = f"{millions:.1f}"
    formatted = _strip_trailing_zero_decimal(formatted)
    return f"${formatted}M"


def format_distance(km: float | int | None) -> str:
    """'1.4 km' for ≥ 1 km, '760 m' for < 1 km, '—' if None.

    Sub-1 km values round to the nearest 10 m so '0.76' km → '760 m', not
    '760 m' vs '763 m' depending on floating-point noise."""
    if km is None:
        return MISSING
    try:
        val = float(km)
    except (TypeError, ValueError):
        return MISSING
    if val < 0:
        return MISSING
    if val >= 1:
        # One decimal max; drop trailing zero ('5.0 km' → '5 km').
        formatted = _strip_trailing_zero_decimal(f"{val:.1f}")
        return f"{formatted} km"
    metres = int(round(val * 1000 / 10) * 10)
    return f"{metres} m"


def format_price_per_m2(ppm: float | int | None) -> str:
    """'$35/m²', '$11.82/m²', '$130/m²', '—' if None or ≤ 0.

    Two-decimal-then-strip rule keeps salient precision for sub-$100
    values (the bargain-alert posts hinge on '$11.82' reading sharp) and
    cleans up integer values ($35.00 → $35)."""
    if ppm is None:
        return MISSING
    try:
        val = float(ppm)
    except (TypeError, ValueError):
        return MISSING
    if val <= 0:
        return MISSING
    formatted = _strip_trailing_zero_decimal(f"{val:.2f}")
    return f"${formatted}/m²"


def format_zone_delta_pct(pct: float | int | None) -> str:
    """Format a price-vs-zone percentage for IG copy.  '−93%', '+12%', '—'.

    Negative deltas (cheaper than zone) use the typographic minus '−'
    rather than ASCII hyphen so it lines up visually with the bargain
    alert posters.  Positive deltas get an explicit '+'."""
    if pct is None:
        return MISSING
    try:
        val = float(pct)
    except (TypeError, ValueError):
        return MISSING
    rounded = int(round(val))
    if rounded < 0:
        return f"−{abs(rounded)}%"
    if rounded > 0:
        return f"+{rounded}%"
    return "0%"
