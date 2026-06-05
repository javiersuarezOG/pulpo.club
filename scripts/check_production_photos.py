#!/usr/bin/env python3
"""Production photo HEAD-check canary — PR-S0c.

Reads ``web/data/ranked.json``, takes the top-N listings by rank, and
HEAD-probes each one's ``hero_photo_path`` against ``pulpo.club`` (or
a configured base URL). Fails with exit 1 if any returns non-2xx —
treated as a P0 production-canary failure by the watchdog Slack
alerter.

Why this exists
---------------
PR #645's `enforce_photo_contract` nulls stale hero paths at commit
time (LOCAL — checks files exist in `web/photos/`). That catches the
"path written but file absent" case at the source. This canary catches
the OTHER case: the file is on disk locally AND committed to main, but
the deployed Vercel build is missing it (build artifact pruned, CDN
purge issue, /api/img broker fallback silently 4xx-ing).

Production-side check is the only reliable proof that what users see
is what we think we shipped.

Usage
-----
    python3 scripts/check_production_photos.py             # top 100 against pulpo.club
    python3 scripts/check_production_photos.py --top 50    # tighter scope
    python3 scripts/check_production_photos.py --base https://preview.example.com

CI consumer: the watchdog workflow or a dedicated cron can invoke
this; non-zero exit → Slack page via the existing alert step.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RANKED = REPO_ROOT / "web" / "data" / "ranked.json"
DEFAULT_BASE = "https://pulpo.club"


def head_check(url: str, timeout: float = 8.0) -> tuple[int | None, str | None]:
    """Return (status_code, error). On any exception, status is None
    and error names the exception class."""
    req = urllib.request.Request(url, method="HEAD", headers={
        "User-Agent": "PulpoProdPhotoCanary/1.0 (+https://pulpo.club)",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, None
    except urllib.error.HTTPError as e:
        # urlopen raises on 4xx/5xx; capture the status.
        return e.code, None
    except Exception as e:  # noqa: BLE001
        return None, f"{e.__class__.__name__}: {e}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ranked",
        type=Path,
        default=DEFAULT_RANKED,
        help="Path to ranked.json.",
    )
    parser.add_argument(
        "--base",
        default=DEFAULT_BASE,
        help=(
            "Base URL to probe against (default https://pulpo.club). "
            "Use a Vercel preview URL for pre-merge testing."
        ),
    )
    parser.add_argument(
        "--top",
        type=int,
        default=100,
        help="Number of top-ranked listings to probe (default 100).",
    )
    parser.add_argument(
        "--throttle-ms",
        type=int,
        default=50,
        help="Sleep between probes (default 50ms) to avoid CDN rate limits.",
    )
    parser.add_argument(
        "--fail-threshold",
        type=int,
        default=1,
        help=(
            "Exit 1 if >= this many photos return non-2xx. Default 1 "
            "(any 4xx in the top-100 is a real LCP regression)."
        ),
    )
    args = parser.parse_args()

    if not args.ranked.exists():
        print(f"error: ranked.json not found at {args.ranked}", file=sys.stderr)
        return 2

    data = json.loads(args.ranked.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("error: ranked.json is not a list", file=sys.stderr)
        return 2

    # Listings are pre-sorted by rank in ranked.json.
    sample = data[: args.top]
    print(f"Probing top {len(sample)} listings against {args.base}")
    print(f"{'rank':<6} {'status':<8} {'source':<22} url")
    print("-" * 100)

    failures: list[tuple[int, str, str, str]] = []
    for idx, listing in enumerate(sample):
        if not isinstance(listing, dict):
            continue
        hero_path = listing.get("hero_photo_path")
        if not hero_path:
            print(f"{idx:<6} {'SKIP':<8} {listing.get('source','?'):<22} (no hero_photo_path)")
            continue
        # hero_photo_path is `/photos/<file>.jpg`. Join with base.
        url = urllib.parse.urljoin(args.base.rstrip("/") + "/", hero_path.lstrip("/"))
        status, error = head_check(url)
        source = listing.get("source", "?")
        if error or (status is not None and not 200 <= status < 300):
            status_str = error or f"HTTP {status}"
            print(f"{idx:<6} {status_str:<8} {source:<22} {url}")
            failures.append((idx, source, url, status_str))
        else:
            print(f"{idx:<6} {status:<8} {source:<22} {url}")
        if args.throttle_ms > 0:
            time.sleep(args.throttle_ms / 1000.0)

    print()
    print(f"Probed: {len(sample)}, failures: {len(failures)}")
    if failures:
        print("\nFailures:")
        for idx, source, url, status_str in failures:
            print(f"  rank={idx} source={source} status={status_str} url={url}")

    if len(failures) >= args.fail_threshold:
        print(
            f"\n[prod_photos] CANARY FAILED: "
            f"{len(failures)} of top-{len(sample)} returned non-2xx",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
