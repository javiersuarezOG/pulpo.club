"""
Salvadoran area-unit conversion + parsing.

Listings come in with messy units. This module turns:
   "30 manzanas"  ->  area_m2 = 209,668.8
   "2,500 vrs²"   ->  area_m2 = 1,747.24
   "1.5 acres"    ->  area_m2 = 6,070.29
   "10,500 m2"    ->  area_m2 = 10,500
   "Lot: 800 yd²" ->  area_m2 = 668.90

All canonical storage is in m². Display units derive at render time.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

# ---------- Canonical conversion factors (to m²) ----------
M2_PER_VARA2 = 0.698896          # 1 vara² (SV) = 0.698896 m²
M2_PER_MANZANA = 6_988.96        # 1 manzana    = 10,000 vrs² = 6,988.96 m²
M2_PER_ACRE = 4_046.86           # 1 acre       = 4,046.86 m²
M2_PER_HECTARE = 10_000.0
M2_PER_YARD2 = 0.836127

# ---------- Unit aliases (lowercased) ----------
# Order matters: longer/more-specific patterns first.
_UNIT_ALIASES: list[tuple[str, str]] = [
    # manzanas
    (r"\bmanzanas?\b", "MZ"),
    (r"\bmzs?\b", "MZ"),
    (r"\bmz\.?\b", "MZ"),
    # varas² (Salvadoran)
    (r"\bvaras?\s*cuadradas?\b", "V2"),
    (r"\bvrs?\s*cuadradas?\b", "V2"),
    (r"\bvaras?[\s\-]*2\b", "V2"),
    (r"\bvrs?2\b", "V2"),
    (r"\bvrs?\s*²\b", "V2"),
    (r"\bv2\b", "V2"),
    (r"\bvr²\b", "V2"),
    (r"\bvr2\b", "V2"),
    (r"\bv²\b", "V2"),
    # acres
    (r"\bacres?\b", "AC"),
    # hectares
    (r"\bhect[aá]reas?\b", "HA"),
    (r"\bhas?\b", "HA"),
    # yards²
    (r"\byardas?\s*cuadradas?\b", "YD2"),
    (r"\byd2\b", "YD2"),
    (r"\byd²\b", "YD2"),
    # meters² — must be LAST because m2 is the most generic substring
    (r"\bmetros?\s*cuadrados?\b", "M2"),
    (r"\bm2\b", "M2"),
    (r"\bm²\b", "M2"),
    (r"\bsq\.?\s*m\.?\b", "M2"),
    (r"\bmts?2\b", "M2"),
    (r"\bmts?\s*²\b", "M2"),
]

# Number with optional thousands separator and optional decimal
_NUMBER_RE = re.compile(
    r"(\d{1,3}(?:[,\.\s]\d{3})*(?:[\.,]\d+)?|\d+(?:[\.,]\d+)?)"
)

@dataclass
class ParsedArea:
    value: float          # numeric quantity in original unit
    unit: str             # one of M2 / V2 / MZ / AC / HA / YD2
    area_m2: float        # canonical
    raw: str              # original substring matched

def _to_float(num_str: str) -> Optional[float]:
    """Handles '1,234.56', '1.234,56', '12 345', '0.5'."""
    s = num_str.replace(" ", "")
    if "," in s and "." in s:
        # Decide which is decimal: whichever appears LAST is decimal
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        # Could be either thousands separator or decimal.
        # If the part after the last comma has 1-2 digits, treat as decimal.
        tail = s.split(",")[-1]
        if 1 <= len(tail) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None

def _normalize_units_text(text: str) -> str:
    """Replace fancy unit phrases with stable tokens like __MZ__ for matching."""
    out = text.lower()
    for pattern, code in _UNIT_ALIASES:
        out = re.sub(pattern, f"__{code}__", out)
    return out

def to_m2(value: float, unit: str) -> float:
    """Convert a quantity in `unit` to m²."""
    unit = unit.upper()
    if unit == "M2":
        return value
    if unit == "V2":
        return value * M2_PER_VARA2
    if unit == "MZ":
        return value * M2_PER_MANZANA
    if unit == "AC":
        return value * M2_PER_ACRE
    if unit == "HA":
        return value * M2_PER_HECTARE
    if unit == "YD2":
        return value * M2_PER_YARD2
    raise ValueError(f"unknown unit {unit!r}")

def parse_area(text: str) -> Optional[ParsedArea]:
    """
    Best-effort area parser. Looks for first '<number> <unit>' pair in `text`.
    Returns None if no recognizable pair found.
    """
    if not text:
        return None
    norm = _normalize_units_text(text)
    # Find first occurrence: number followed (after optional space/punct) by __XX__
    m = re.search(
        r"(\d{1,3}(?:[,\.\s]\d{3})*(?:[\.,]\d+)?|\d+(?:[\.,]\d+)?)"
        r"\s*(?:de\s+)?__([A-Z0-9]+)__",
        norm,
    )
    if not m:
        return None
    num = _to_float(m.group(1))
    unit = m.group(2)
    if num is None:
        return None
    try:
        m2 = to_m2(num, unit)
    except ValueError:
        return None
    return ParsedArea(value=num, unit=unit, area_m2=m2, raw=m.group(0))

# ---------- Display helpers ----------
def m2_to_manzanas(m2: float) -> float:
    return m2 / M2_PER_MANZANA

def m2_to_varas2(m2: float) -> float:
    return m2 / M2_PER_VARA2

def m2_to_acres(m2: float) -> float:
    return m2 / M2_PER_ACRE

def m2_to_hectares(m2: float) -> float:
    return m2 / M2_PER_HECTARE

def fmt_area(m2: float) -> str:
    """Pick the most readable unit for a given m² value."""
    if m2 >= 50_000:
        return f"{m2_to_manzanas(m2):,.2f} manzanas ({m2_to_acres(m2):,.1f} acres)"
    if m2 >= 6_988:
        return f"{m2_to_manzanas(m2):,.2f} manzanas ({m2:,.0f} m²)"
    return f"{m2:,.0f} m² ({m2_to_varas2(m2):,.0f} vrs²)"


# ---------- Price parsing ----------
_PRICE_RE = re.compile(
    r"(?:US\$|USD|\$)\s*"
    r"(\d{1,3}(?:[,\.\s]\d{3})*(?:[\.,]\d+)?|\d+(?:[\.,]\d+)?)"
    r"\s*(k|m|mil|millones?|million)?",
    re.IGNORECASE,
)

def parse_price_usd(text: str) -> Optional[float]:
    """Extract USD price. Handles $1.5M, $250k, $1,250,000, US$ 800,000."""
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        # try plain number with no $ prefix
        nm = re.search(r"\d{1,3}(?:[,\.\s]\d{3})+(?:[\.,]\d+)?", text)
        if not nm:
            return None
        v = _to_float(nm.group(0))
        return v
    base = _to_float(m.group(1))
    if base is None:
        return None
    suf = (m.group(2) or "").lower()
    if suf in ("k",):
        base *= 1_000
    elif suf in ("m", "mil",):
        # ambiguous: "mil" in spanish = thousand, "m" usually = million
        # We treat "mil" as thousand and "m" as million.
        base *= 1_000_000 if suf == "m" else 1_000
    elif suf in ("millones", "millon", "million"):
        base *= 1_000_000
    return base
