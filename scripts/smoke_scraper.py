#!/usr/bin/env python3
"""Single-source live smoke runner — PR-S1.5.

Invoke ONE scraper against its live source and print a diagnostic
report: how many candidates returned, sample listings, validation
drop reasons, wall-clock duration. Used by humans before/after
touching a scraper file (PR-S2 follow-ups, new-source onboarding,
post-incident diagnosis) to avoid the 60-min nightly turnaround.

Usage:
    python3 scripts/smoke_scraper.py nexo                  # default limit 50
    python3 scripts/smoke_scraper.py encuentra24 --limit 200
    python3 scripts/smoke_scraper.py elagente --offline    # use fixtures
    python3 scripts/smoke_scraper.py all --limit 10        # all sources, tiny

Output:
- Stdout: per-source summary with counts + sample
- No persistent state (this is a diagnostic, not a recorded run).

This is the FAST diagnostic surface. For recorded runs that contribute
to the source_coverage_history, use the nightly. For URL-only health,
use the PR-D1 sentinel.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def source_lifecycle(slug: str) -> str:
    """Return source lifecycle; defaults to active for legacy metadata."""
    try:
        from pulpo.scrapers._metadata import SCRAPER_METADATA
        value = SCRAPER_METADATA.get(slug, {}).get("lifecycle")
        if isinstance(value, str) and value:
            return value
    except Exception:
        pass
    return "active"


def smoke_one(
    slug: str,
    limit: int,
    offline: bool,
    allow_empty: bool = False,
) -> dict:
    """Run one scraper, return a summary dict.

    Returns:
        {
          "slug": str,
          "ok": bool,
          "duration_s": float,
          "raw_count": int,
          "error": str | None,
          "sample": [{title, price_usd, url, property_type, source_id}, ...],
        }
    """
    start = time.monotonic()
    try:
        # Lazy import so smoke_one("agentiz") works once that scraper
        # exists in Phase C drafts.
        import importlib
        mod = importlib.import_module(f"pulpo.scrapers.{slug}")
        if not hasattr(mod, "crawl"):
            return {
                "slug": slug,
                "ok": False,
                "duration_s": time.monotonic() - start,
                "raw_count": 0,
                "lifecycle": source_lifecycle(slug),
                "error": f"module {slug!r} has no crawl() function",
                "sample": [],
            }
        listings = mod.crawl(limit=limit, offline=offline)
        if listings is None:
            listings = []
        lifecycle = source_lifecycle(slug)
        sample = []
        for li in listings[:5]:
            if isinstance(li, dict):
                sample.append({
                    "title": (li.get("title") or "")[:60],
                    "price_usd": li.get("price_usd"),
                    "url": li.get("url"),
                    "property_type": li.get("property_type"),
                    "source_id": li.get("source_id"),
                })
        raw_count = len(listings)
        zero_is_failure = (
            raw_count == 0
            and not allow_empty
            and lifecycle == "active"
        )
        return {
            "slug": slug,
            "ok": not zero_is_failure,
            "duration_s": time.monotonic() - start,
            "raw_count": raw_count,
            "lifecycle": lifecycle,
            "error": (
                "active source returned zero listings; pass --allow-empty "
                "only for an expected empty smoke"
                if zero_is_failure else None
            ),
            "sample": sample,
        }
    except Exception as e:  # noqa: BLE001 — diagnostic, don't crash
        return {
            "slug": slug,
            "ok": False,
            "duration_s": time.monotonic() - start,
            "raw_count": 0,
            "lifecycle": source_lifecycle(slug),
            "error": f"{e.__class__.__name__}: {e}\n{traceback.format_exc()[-600:]}",
            "sample": [],
        }


def discover_all_sources() -> list[str]:
    """Walk pulpo/scrapers/*.py for slugs (excludes _-prefixed)."""
    out = []
    scrapers_dir = REPO_ROOT / "pulpo" / "scrapers"
    for f in sorted(scrapers_dir.glob("*.py")):
        if f.name.startswith("_") or f.name == "__init__.py":
            continue
        out.append(f.stem)
    return out


def print_report(result: dict) -> None:
    """Compact per-source report."""
    ok_str = "OK" if result["ok"] else "ERR"
    print(f"\n=== {result['slug']:<22} {ok_str} ({result['duration_s']:.1f}s) ===")
    print(f"  raw_count: {result['raw_count']}")
    if result.get("lifecycle"):
        print(f"  lifecycle: {result['lifecycle']}")
    if result["error"]:
        # Only first 3 lines + last line of traceback.
        err_lines = result["error"].splitlines()
        head = err_lines[0] if err_lines else "(no error msg)"
        print(f"  error: {head}")
        if len(err_lines) > 1:
            print(f"  ... full traceback truncated ({len(err_lines)} lines)")
    if result["sample"]:
        print("  sample (first 5):")
        for s in result["sample"]:
            price = f"${s['price_usd']:,.0f}" if s.get("price_usd") else "$?"
            ptype = s.get("property_type") or "?"
            title = s.get("title") or "(no title)"
            print(f"    [{ptype:<6}] {price:<10} {title}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        help="Scraper slug (e.g. 'nexo'), or 'all' for every registered source.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Listings cap per source (default 50; pick small for live runs).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Use offline fixtures instead of hitting the live source.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON to stdout (one object per source).",
    )
    parser.add_argument(
        "--allow-empty",
        action="store_true",
        help="Treat zero listings as OK for expected-empty diagnostics.",
    )
    args = parser.parse_args()

    if args.source == "all":
        slugs = discover_all_sources()
    else:
        slugs = [args.source]

    results = []
    for slug in slugs:
        result = smoke_one(
            slug,
            limit=args.limit,
            offline=args.offline,
            allow_empty=args.allow_empty,
        )
        results.append(result)
        if not args.json:
            print_report(result)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        # Aggregate summary at the bottom for 'all' mode.
        print()
        print("=" * 60)
        ok_count = sum(1 for r in results if r["ok"])
        total_raw = sum(r["raw_count"] for r in results)
        print(f"smoke summary: {ok_count}/{len(results)} ok, total_raw={total_raw}")
        if len(results) > 1:
            # Per-source one-liner.
            for r in sorted(results, key=lambda x: -x["raw_count"]):
                status = "ok " if r["ok"] else "ERR"
                print(f"  {status} {r['slug']:<22} raw={r['raw_count']:<5} {r['duration_s']:.1f}s")

    # Exit non-zero if any source errored — CI hook.
    if any(not r["ok"] for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
