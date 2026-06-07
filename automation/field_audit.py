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


# PRD hard-gate fields. The product PRD's three buyer questions are
# "What is it? Where exactly? How much?" — answered by property_type,
# a usable location signal, and price.
#
# "Usable location signal" means ANY of {location_text, zone,
# municipality, department}. After normalize, well-behaved scrapers
# leave `zone` / `municipality` / `department` populated even if
# `location_text` is blank — `derived_rules.derive_master_category`
# only needs the slug, not the raw text. Earlier versions of this
# audit checked `location_text` alone and reported 0% coverage for
# Phase C sources (Santizo, Vivo Latam, CSBR, etc.) that DO carry
# a usable location after normalize. The disjunction below makes the
# audit honest about whether the listing can be placed on a shelf.
#
# property_type is intentionally NOT in TRACKED above because the
# legacy info-only audit never reported it — we keep the legacy
# table shape stable and reference the field name explicitly here.
HARD_GATE_FIELDS: tuple[str, ...] = ("property_type", "location", "price_usd")

# Per hard-gate field: list of underlying record fields that satisfy
# the gate when ANY one of them is populated. Single-element tuples
# behave the same as the field-name lookup. The "location" disjunction
# documents the rule above.
_HARD_GATE_FIELD_SOURCES: dict[str, tuple[str, ...]] = {
    "property_type": ("property_type",),
    "location":      ("location_text", "zone", "municipality", "department"),
    "price_usd":     ("price_usd",),
}

# Acceptance threshold per PRD: ≥ 85% hard-gate coverage on a 50-listing
# sample per source. Below this and the source should be flagged for
# manual review of its parse path.
ACCEPTANCE_HARD_GATE_THRESHOLD = 0.85
ACCEPTANCE_SAMPLE_SIZE = 50


def _listing_satisfies_gate(li: dict, gate: str) -> bool:
    """True iff ANY of the underlying record fields backing this gate
    is populated on the listing. The "location" gate is the only
    multi-field one today (zone OR municipality OR department OR
    location_text); the others are single-field aliases for clarity."""
    sources = _HARD_GATE_FIELD_SOURCES.get(gate, (gate,))
    for field in sources:
        value = li.get(field)
        if field == "property_type":
            if isinstance(value, str) and value.strip():
                return True
        else:
            if is_populated(value, False):
                return True
    return False


def hard_gate_pct(listings: list[dict]) -> dict[str, float]:
    """Return ``{gate: populated_ratio}`` for HARD_GATE_FIELDS over
    the given listing set. The "location" gate accepts ANY of
    location_text / zone / municipality / department; the others are
    single-field — see ``_HARD_GATE_FIELD_SOURCES``."""
    n = len(listings)
    if n == 0:
        return {f: 0.0 for f in HARD_GATE_FIELDS}
    pct: dict[str, float] = {}
    for gate in HARD_GATE_FIELDS:
        count = sum(1 for li in listings if _listing_satisfies_gate(li, gate))
        pct[gate] = round(count / n, 4)
    return pct


def _is_shelf_eligible(li: dict) -> bool:
    """True iff the listing is part of the shelf-eligible cohort the
    PRD acceptance gate cares about.

    The PRD's acceptance criterion ("each listing answers What / Where /
    How much?") is about listings that can serve a buyer. Listings
    already excluded from shelves — ``is_incomplete=True`` (the
    derive_is_incomplete pipeline already decided this listing can't
    be placed) and ``is_agricultural=True`` (tagged but not rendered) —
    should not be counted against a source's coverage, because the
    data layer has already correctly identified them as unviable.

    Without this filter the gate over-flags luxury brokers like
    oceanside whose normal pattern includes "consultar" / contact-for-
    pricing listings that the data layer already hides. Investigated
    in PR #760's first audit run (7 of 22 oceanside listings missing
    price; all 7 already ``is_incomplete=True``).
    """
    if li.get("is_incomplete") is True:
        return False
    if li.get("is_agricultural") is True:
        return False
    return True


def acceptance_check(
    all_listings: list[dict],
    *,
    threshold: float = ACCEPTANCE_HARD_GATE_THRESHOLD,
    sample_size: int = ACCEPTANCE_SAMPLE_SIZE,
    include_hidden: bool = False,
) -> tuple[int, list[dict]]:
    """Pure acceptance evaluation per PRD.

    Returns ``(exit_code, per_source_reports)``. Exit 1 when any source
    has fewer than ``threshold`` × 100% coverage on any HARD_GATE field
    within the first ``sample_size`` SHELF-ELIGIBLE listings of that
    source. Exit 0 when every source clears the gate, or when no
    listings exist (no data is not a CI failure on its own — that's
    a different signal handled upstream).

    ``include_hidden=True`` reverts to the legacy behavior of
    evaluating every listing regardless of ``is_incomplete`` /
    ``is_agricultural`` — useful for forensic audits ("why did the
    data layer exclude these?") but NOT what CI should use.

    The ``per_source_reports`` list contains one dict per source with
    ``source, n_sample, n_eligible, hard_gate_pct, failures`` where
    ``failures`` is the list of hard-gate fields that fell below the
    threshold.
    """
    by_source: dict[str, list[dict]] = defaultdict(list)
    for li in all_listings:
        if include_hidden or _is_shelf_eligible(li):
            by_source[li.get("source", "unknown")].append(li)

    reports: list[dict] = []
    failed = False
    for slug in sorted(by_source):
        listings = by_source[slug][:sample_size]
        if not listings:
            continue
        pct = hard_gate_pct(listings)
        failures = [
            field for field in HARD_GATE_FIELDS
            if pct[field] < threshold
        ]
        reports.append({
            "source": slug,
            "n_sample": len(listings),
            "hard_gate_pct": pct,
            "threshold": threshold,
            "failures": failures,
        })
        if failures:
            failed = True
    return (1 if failed else 0), reports


def print_acceptance_report(reports: list[dict]) -> None:
    """Render the acceptance test output. One block per source with
    PASS / FAIL verdict so an operator scanning the CI log can act on
    the first FAIL without reading the entire table."""
    if not reports:
        print("acceptance: no listings to evaluate")
        return
    for r in reports:
        slug = r["source"]
        n = r["n_sample"]
        verdict = "FAIL" if r["failures"] else "PASS"
        print(f"\n=== {slug} (n={n}) — acceptance: {verdict} ===")
        for field in HARD_GATE_FIELDS:
            pct = r["hard_gate_pct"][field]
            mark = "✗" if pct < r["threshold"] else "✓"
            print(f"  {mark} {field:<16} {int(pct * 100):>3}%  "
                  f"(threshold {int(r['threshold'] * 100)}%)")
        if r["failures"]:
            print(f"  → failures: {', '.join(r['failures'])}")


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


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description=(
            "Field-completeness audit. Default mode is informational "
            "(always exits 0). Pass --acceptance-test to exit 1 when "
            "any source falls below the PRD's hard-gate threshold."
        )
    )
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Path to ranked.json (defaults to web/data/ranked.json).",
    )
    parser.add_argument(
        "--acceptance-test",
        action="store_true",
        help=(
            "Acceptance mode: exits 1 when any source's hard-gate "
            "coverage falls below %g%% on its first %d listings. "
            "PRD sign-off criterion. Suppresses the legacy info-only "
            "table." % (ACCEPTANCE_HARD_GATE_THRESHOLD * 100, ACCEPTANCE_SAMPLE_SIZE)
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=ACCEPTANCE_HARD_GATE_THRESHOLD,
        help="Override the acceptance threshold (0.0-1.0). Default 0.85.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=ACCEPTANCE_SAMPLE_SIZE,
        help="Override the acceptance sample size per source. Default 50.",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help=(
            "Forensic mode: evaluate every listing including "
            "is_incomplete=True and is_agricultural=True. Default is "
            "shelf-eligible only (matches the PRD's 'serves a buyer' "
            "framing). Useful for diagnosing why the data layer "
            "excluded specific listings; not what CI should use."
        ),
    )
    args = parser.parse_args(argv)

    data_path = Path(args.path) if args.path else REPO / "web" / "data" / "ranked.json"

    if not data_path.exists():
        print(f"ranked.json not found at {data_path} — run python3 -m pulpo.cli --offline first")
        return 1

    all_listings: list[dict] = json.loads(data_path.read_text(encoding="utf-8"))

    if args.acceptance_test:
        exit_code, reports = acceptance_check(
            all_listings,
            threshold=args.threshold,
            sample_size=args.sample_size,
            include_hidden=args.include_hidden,
        )
        print_acceptance_report(reports)
        if exit_code != 0:
            failing = [r["source"] for r in reports if r["failures"]]
            print(f"\nacceptance: FAIL — sources below threshold: {', '.join(failing)}")
        else:
            print("\nacceptance: PASS — every source clears the hard-gate threshold.")
        return exit_code

    # Group by source for the legacy info-only table.
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
