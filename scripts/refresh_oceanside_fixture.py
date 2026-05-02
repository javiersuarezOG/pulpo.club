#!/usr/bin/env python3
"""
Re-pull the oceanside lot listings from the live WP REST API and save
to tests/fixtures/oceanside_lots.json.

Run this when the live listing count changes or after a scraper update
that could affect which records are returned.  Never auto-run in CI —
it makes network calls.

Usage:
    python3 scripts/refresh_oceanside_fixture.py
"""
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.scrapers.oceanside import _find_land_term_id, API_BASE  # noqa: E402
from pulpo.agents.html_crawler import make_client  # noqa: E402

FIXTURE_PATH = REPO / "tests" / "fixtures" / "oceanside_lots.json"


def main() -> None:
    client = make_client()
    try:
        time.sleep(1.5)
        land_id = _find_land_term_id(client)
        if land_id is None:
            print("ERROR: could not find land term id", file=sys.stderr)
            sys.exit(1)
        print(f"Land term id: {land_id}")

        time.sleep(1.5)
        r = client.get(
            f"{API_BASE}/rental-details",
            params={"per_page": 100, "property-type": land_id, "page": 1},
        )
        r.raise_for_status()
        recs = r.json()
        total = int(r.headers.get("X-WP-Total") or len(recs))
        print(f"X-WP-Total={total}  records in response={len(recs)}")

        FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE_PATH.write_text(
            json.dumps(recs, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Written: {FIXTURE_PATH.relative_to(REPO)}")
    finally:
        client.close()


if __name__ == "__main__":
    main()
