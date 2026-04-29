"""
Single-command pipeline runner for automation (cron, GitHub Actions, etc.).

Runs all configured scrapers, normalizes, ranks, and writes:
    samples/ranked.csv         (committed for human review)
    web/data/ranked.json       (consumed by web/index.html dashboard)
    web/data/last_updated.json (timestamp + counts for the dashboard header)

Exit code 0 on success, 1 on failure.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repo root is on sys.path
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.scrapers import REGISTRY  # noqa: E402
from pulpo.scrapers.base import HTTPX_OK, SELECTOLAX_OK  # noqa: E402
from pulpo.normalize import normalize  # noqa: E402
from pulpo.ranker import rank  # noqa: E402
from pulpo.cli import _row, CSV_FIELDS  # noqa: E402

import csv  # noqa: E402

def main() -> int:
    offline = os.environ.get("PULPO_OFFLINE") == "1"
    limit = int(os.environ.get("PULPO_LIMIT", "30"))
    sources = (os.environ.get("PULPO_SOURCES") or ",".join(REGISTRY.keys())).split(",")

    started = datetime.now(timezone.utc)
    raw: list[dict] = []
    per_source_count: dict[str, int] = {}
    errors: list[str] = []

    # Fixture-fallback guard. BaseScraper auto-flips to fixture mode when
    # httpx or selectolax aren't importable. That's fine when PULPO_OFFLINE=1
    # is explicit, but if we expected a live run and the deps are missing
    # we'd happily serve stale fixture data while reporting offline=false in
    # last_updated.json — invisible to monitoring. Surface it loudly instead.
    fixture_fallback_active = (not offline) and not (HTTPX_OK and SELECTOLAX_OK)
    if fixture_fallback_active:
        missing = []
        if not HTTPX_OK:
            missing.append("httpx")
        if not SELECTOLAX_OK:
            missing.append("selectolax")
        msg = (
            f"deps missing ({', '.join(missing)}); BaseScraper will fall back "
            f"to fixtures despite PULPO_OFFLINE=0. Live data will NOT be fetched. "
            f"Install with `pip install -r requirements.txt` (use httpx[socks] "
            f"behind a SOCKS proxy)."
        )
        print(f"WARNING: {msg}", file=sys.stderr)
        errors.append(msg)

    for src in sources:
        src = src.strip()
        mod = REGISTRY.get(src)
        if not mod:
            errors.append(f"unknown source: {src}")
            continue
        try:
            recs = mod.crawl(limit=limit, offline=offline or None)
        except Exception as e:
            errors.append(f"{src}: {e!r}")
            continue
        per_source_count[src] = len(recs)
        for r in recs:
            r.setdefault("source", src)
            raw.append(r)

    # Normalize
    listings = []
    dropped = 0
    for r in raw:
        li = normalize(r, source=r.get("source") or "unknown")
        if li:
            listings.append(li)
        else:
            dropped += 1

    # Rank
    ranked = rank(listings)

    # Write CSV
    samples_path = REPO / "samples" / "ranked.csv"
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    with samples_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for li in ranked:
            w.writerow(_row(li))

    # Write web JSON. Two files:
    #   ranked.json        — full records, served only by /api/members behind auth
    #   ranked-public.json — broker/url/exact-price fields stripped, safe to serve statically
    web_data_dir = REPO / "web" / "data"
    web_data_dir.mkdir(parents=True, exist_ok=True)
    with (web_data_dir / "ranked.json").open("w", encoding="utf-8") as f:
        json.dump([li.to_dict() for li in ranked], f, indent=2, ensure_ascii=False, default=str)
    with (web_data_dir / "ranked-public.json").open("w", encoding="utf-8") as f:
        json.dump([li.to_public_dict() for li in ranked], f, indent=2, ensure_ascii=False, default=str)

    # Last-updated metadata
    finished = datetime.now(timezone.utc)
    meta = {
        "last_updated": finished.isoformat(),
        "started_at": started.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 2),
        "total_listings": len(ranked),
        "dropped": dropped,
        "per_source_raw": per_source_count,
        "sources": sources,
        "offline": offline,
        # True when the run advertised itself as live but BaseScraper
        # fell through to fixtures because httpx/selectolax weren't
        # importable. Distinct from `offline` (the env-var intent) so
        # monitoring can alert on the gap between intended and actual.
        "fixture_fallback_active": fixture_fallback_active,
        "errors": errors,
    }
    with (web_data_dir / "last_updated.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    # Summary line for CI logs
    print(
        f"pulpo run | {finished.isoformat()} | "
        f"{len(ranked)} listings | sources={','.join(sources)} | "
        f"errors={len(errors)} | offline={offline}"
    )
    if errors:
        print("ERRORS:")
        for e in errors:
            print(f"  - {e}")
        # Don't fail the run on partial failures — partial data is better than no data
    return 0

if __name__ == "__main__":
    sys.exit(main())
