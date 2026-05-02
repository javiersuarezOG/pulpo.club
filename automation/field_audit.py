#!/usr/bin/env python3
"""
Field-completeness audit — which fields are populated per source?

Loads web/data/ranked.json and reports, per source, how often each
tracked field has a real value.

Tracked fields and their completeness definition:
  - Numeric / string fields: non-null AND non-empty-string counts as populated.
  - Boolean flags (is_beachfront, has_paved_access, has_water, has_power,
    is_repriced): only True counts as populated. False is indistinguishable
    from "the broker didn't mention it" with our current normalize logic,
    so counting False would inflate the numbers misleadingly.

Always exits 0 — this is informational, not a gate.

Usage:
    python3 automation/field_audit.py                  # reads ranked.json
    python3 automation/field_audit.py path/to/alt.json # custom file
"""
from __future__ import annotations
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Fields to audit, in display order.
# Tuples of (field_name, is_boolean_flag)
TRACKED: list[tuple[str, bool]] = [
    # Hard fields
    ("price_usd",       False),
    ("area_m2",         False),
    # Location
    ("zone",            False),
    ("municipality",    False),
    ("department",      False),
    ("location_text",   False),
    ("lat",             False),
    ("lng",             False),
    # Quality flags (boolean — only True counts)
    ("is_beachfront",   True),
    ("has_paved_access",True),
    ("has_water",       True),
    ("has_power",       True),
    # Lifecycle
    ("is_repriced",     True),
    ("days_listed",     False),
    ("photos_count",    False),
    # Broker
    ("broker_name",     False),
    ("broker_phone",    False),
    ("broker_email",    False),
    # Content
    ("title",           False),
    ("description",     False),
]

FIELD_NAMES = [f for f, _ in TRACKED]


def is_populated(value, is_bool_flag: bool) -> bool:
    if is_bool_flag:
        return value is True
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float)):
        return True  # 0 is a valid value (e.g. photos_count=0 means "none" but is present)
    return bool(value)


def compute_completeness(listings: list[dict]) -> dict[str, dict]:
    """Return {field: {"count": int, "pct": float}} for a group of listings."""
    n = len(listings)
    if n == 0:
        return {f: {"count": 0, "pct": 0.0} for f, _ in TRACKED}
    result = {}
    for field, is_bool in TRACKED:
        count = sum(1 for li in listings if is_populated(li.get(field), is_bool))
        result[field] = {"count": count, "pct": round(count / n, 4)}
    return result


def print_source_table(slug: str, listings: list[dict]) -> None:
    n = len(listings)
    print(f"\n=== {slug} ({n} listing{'s' if n != 1 else ''}) ===")
    if n == 0:
        print("  no listings")
        return

    stats = compute_completeness(listings)
    col_w = max(len(f) for f in FIELD_NAMES) + 2

    print(f"  {'field':<{col_w}} {'pop%':>5}   {'count':>5}")
    print(f"  {'-'*col_w} {'-----':>5}   {'-----':>5}")
    for field, _ in TRACKED:
        s = stats[field]
        pct_str = f"{int(s['pct'] * 100)}%"
        print(f"  {field:<{col_w}} {pct_str:>5}   {s['count']:>5}")

    # Weakest 3 by populated %
    sorted_fields = sorted(FIELD_NAMES, key=lambda f: stats[f]["pct"])
    weakest = [f"{f} ({int(stats[f]['pct']*100)}%)" for f in sorted_fields[:3]]
    print(f"\n  weakest 3: {', '.join(weakest)}")


def build_completeness_block(all_listings: list[dict]) -> dict:
    """Build the field_completeness dict for last_updated.json."""
    by_source: dict[str, list[dict]] = defaultdict(list)
    for li in all_listings:
        by_source[li.get("source", "unknown")].append(li)

    block = {}
    for slug, listings in sorted(by_source.items()):
        stats = compute_completeness(listings)
        block[slug] = {
            "n_listings": len(listings),
            "fields": {f: round(stats[f]["pct"], 2) for f in FIELD_NAMES},
        }
    return block


def main() -> int:
    data_path = (
        Path(sys.argv[1]) if len(sys.argv) > 1
        else REPO / "web" / "data" / "ranked.json"
    )

    if not data_path.exists():
        print(f"ranked.json not found at {data_path} — run python3 -m pulpo.cli --offline first")
        return 1

    all_listings: list[dict] = json.loads(data_path.read_text(encoding="utf-8"))

    # Group by source
    by_source: dict[str, list[dict]] = defaultdict(list)
    for li in all_listings:
        by_source[li.get("source", "unknown")].append(li)

    # Per-source tables
    for slug in sorted(by_source):
        print_source_table(slug, by_source[slug])

    # Cross-source aggregate
    if len(by_source) > 1:
        print(f"\n=== ALL SOURCES ({len(all_listings)} listings total) ===")
        total_stats = compute_completeness(all_listings)
        sorted_agg = sorted(FIELD_NAMES, key=lambda f: total_stats[f]["pct"])
        print("  cross-source weakest 5 (calibration targets):")
        for f in sorted_agg[:5]:
            s = total_stats[f]
            print(f"    {f:<22} {int(s['pct']*100):>3}%  ({s['count']}/{len(all_listings)})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
