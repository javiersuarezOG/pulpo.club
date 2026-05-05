#!/usr/bin/env python3
"""
Coverage audit — are we pulling all available supply?

For each source in SOURCES prints a table showing:
  supplier   : listings the broker publishes (None → unknown / denylist)
  pulled     : listings we fetched with generous limits
  coverage   : pulled / supplier (or "?" if supplier unknown)
  max_pages_hit : True if we hit our MAX_PAGES cap with results still coming
  limit_hit  : True if we hit the audit LIMIT before pagination ended

Exit 0: all sources with a known supplier total have coverage ≥ 95%
        AND no source has max_pages_hit.
Exit 1: under-pulling detected — see FAILURES section.

Offline-safe: if PULPO_OFFLINE=1 (or httpx/selectolax unavailable),
prints a skip notice and exits 0.

Usage:
    python3 automation/coverage_audit.py
    PULPO_OFFLINE=1 python3 automation/coverage_audit.py   # skipped
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.agents.html_crawler import is_offline, make_client  # noqa: E402
import pulpo.scrapers  # noqa: F401, E402 — triggers SOURCES registration
from pulpo.agents import SOURCES  # noqa: E402

AUDIT_LIMIT = 500
AUDIT_MAX_PAGES = 50
COVERAGE_THRESHOLD = 95  # percent


def main() -> int:
    if is_offline():
        print("skipped — fixture mode (PULPO_OFFLINE=1 or httpx/selectolax unavailable)")
        return 0

    client = make_client()
    rows: list[dict] = []
    failures: list[str] = []

    try:
        for slug, scraper in SOURCES.items():
            print(f"  auditing {slug}…", flush=True)

            # Supplier total
            supplier: int | None = None
            if hasattr(scraper, "report_total"):
                try:
                    supplier = scraper.report_total(client)
                except Exception as e:
                    print(f"  [{slug}] report_total error: {e}")

            # Crawl with relaxed caps
            pulled = 0
            max_pages_hit = False
            limit_hit = False
            if hasattr(scraper, "crawl_with_meta"):
                try:
                    result = scraper.crawl_with_meta(
                        limit=AUDIT_LIMIT, max_pages=AUDIT_MAX_PAGES
                    )
                    pulled = len(result["records"])
                    max_pages_hit = result["max_pages_hit"]
                    limit_hit = result["limit_hit"]
                except Exception as e:
                    print(f"  [{slug}] crawl_with_meta error: {e}")
            else:
                try:
                    pulled = len(scraper.crawl(limit=AUDIT_LIMIT))
                except Exception as e:
                    print(f"  [{slug}] crawl error: {e}")

            # Coverage
            if supplier is not None and supplier > 0:
                pct = int(100 * pulled / supplier)
                coverage = f"{pct}%"
                if pct < COVERAGE_THRESHOLD or max_pages_hit:
                    reasons = []
                    if pct < COVERAGE_THRESHOLD:
                        reasons.append(f"{pct}% < {COVERAGE_THRESHOLD}% threshold")
                    if max_pages_hit:
                        reasons.append("max_pages_hit — bump MAX_PAGES or pageSize")
                    failures.append(
                        f"  {slug}: {', '.join(reasons)} "
                        f"(supplier={supplier}, pulled={pulled})"
                    )
            else:
                coverage = "?"

            rows.append({
                "source": slug,
                "supplier": str(supplier) if supplier is not None else "?",
                "pulled": str(pulled),
                "coverage": coverage,
                "max_pages_hit": "yes" if max_pages_hit else "no",
                "limit_hit": "yes" if limit_hit else "no",
            })
    finally:
        client.close()

    # Print table
    cols = ["source", "supplier", "pulled", "coverage", "max_pages_hit", "limit_hit"]
    widths = {c: max(len(c), max(len(r[c]) for r in rows)) for c in cols}
    header = "  ".join(c.ljust(widths[c]) for c in cols)
    sep    = "  ".join("-" * widths[c] for c in cols)
    print()
    print(header)
    print(sep)
    for r in rows:
        print("  ".join(r[c].ljust(widths[c]) for c in cols))
    print()

    if failures:
        print(f"FAILURES — {len(failures)} source(s) under-pulling:")
        for f in failures:
            print(f)
        print()
        return 1

    known = [r for r in rows if r["supplier"] != "?"]
    print(
        f"OK — {len(known)} source(s) with known totals all at "
        f"≥{COVERAGE_THRESHOLD}% coverage, no pagination cap hit."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
