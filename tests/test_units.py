"""Verification tests for the units module — run with: python -m pytest tests/

If pytest isn't installed, run as a plain script: python tests/test_units.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pulpo.units import (
    parse_area, parse_price_usd, M2_PER_VARA2, M2_PER_MANZANA, M2_PER_ACRE,
)

def approx(a: float, b: float, tol: float = 0.5) -> bool:
    return abs(a - b) < tol

def t(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)

FAILED: list[str] = []

def main() -> int:
    print("conversion factors")
    t("1 vara² = 0.698896 m²", approx(M2_PER_VARA2, 0.698896, 1e-6))
    t("1 manzana = 6,988.96 m²", approx(M2_PER_MANZANA, 6988.96, 1e-3))
    t("1 acre = 4,046.86 m²", approx(M2_PER_ACRE, 4046.86, 1e-3))

    print("\narea parser — happy paths")
    p = parse_area("30 manzanas")
    t("'30 manzanas' -> 209,668.8 m²", p is not None and approx(p.area_m2, 209668.8))

    p = parse_area("5 mz")
    t("'5 mz' -> 34,944.8 m²", p is not None and approx(p.area_m2, 34944.8))

    p = parse_area("800 vrs²")
    t("'800 vrs²' -> 559.12 m²", p is not None and approx(p.area_m2, 559.12, 0.05))

    p = parse_area("1.5 manzanas")
    t("'1.5 manzanas' -> 10,483.44 m²", p is not None and approx(p.area_m2, 10483.44))

    p = parse_area("10,500 m²")
    t("'10,500 m²' -> 10,500 m²", p is not None and approx(p.area_m2, 10500))

    p = parse_area("Lot: 1.5 acres total")
    t("'1.5 acres' -> 6,070.29 m²", p is not None and approx(p.area_m2, 6070.29))

    p = parse_area("2,500 vrs cuadradas")
    t("'2,500 vrs cuadradas' -> 1,747.24 m²",
      p is not None and approx(p.area_m2, 1747.24))

    p = parse_area("12 hectáreas")
    t("'12 hectáreas' -> 120,000 m²", p is not None and approx(p.area_m2, 120000))

    print("\narea parser — edge cases")
    p = parse_area("Casa con 3 dormitorios")
    t("'Casa con 3 dormitorios' -> None (no unit)", p is None)

    p = parse_area("")
    t("'' -> None", p is None)

    print("\nprice parser")
    t("'$1,250,000' -> 1250000",
      approx(parse_price_usd("$1,250,000") or 0, 1250000, 0.5))
    t("'US$ 800,000' -> 800000",
      approx(parse_price_usd("US$ 800,000") or 0, 800000, 0.5))
    t("'$250k' -> 250000",
      approx(parse_price_usd("$250k") or 0, 250000, 0.5))
    t("'precio: $3,000,000 firme' -> 3000000",
      approx(parse_price_usd("precio: $3,000,000 firme") or 0, 3000000, 0.5))

    print("\nEl Cuco worked example (from architecture doc)")
    p = parse_area("30 manzanas")
    price = parse_price_usd("US$ 3,000,000")
    assert p and price
    ppm = price / p.area_m2
    t("$/m² for 30mz at $3M = $14.31", approx(ppm, 14.31, 0.01))

    print()
    if FAILED:
        print(f"FAILED: {len(FAILED)} test(s) — {FAILED}")
        return 1
    print("ALL PASSED")
    return 0

if __name__ == "__main__":
    sys.exit(main())
