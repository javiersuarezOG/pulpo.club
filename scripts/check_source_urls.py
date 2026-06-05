#!/usr/bin/env python3
"""URL drift sentinel CLI — PR-D1.

Usage:
    python3 scripts/check_source_urls.py                  # probe all registered sources
    python3 scripts/check_source_urls.py --source nexo    # probe one source only
    python3 scripts/check_source_urls.py --fail-on-drift  # exit 1 if any non-ok

Output goes to stdout (human-readable) AND to
``web/data/url_drift/<source>.json`` (machine-readable, git-tracked).

Slack alerting + cron execution live in
``.github/workflows/pulpo-url-drift.yml``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DRIFT_DIR = REPO_ROOT / "web" / "data" / "url_drift"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        help="Probe one source only (slug, e.g. 'nexo'). Default: all.",
    )
    parser.add_argument(
        "--drift-dir",
        type=Path,
        default=DEFAULT_DRIFT_DIR,
        help=f"Directory for per-source state JSONs (default: {DEFAULT_DRIFT_DIR}).",
    )
    parser.add_argument(
        "--timeout-s",
        type=float,
        default=10.0,
        help="HEAD probe timeout (default 10s).",
    )
    parser.add_argument(
        "--fail-on-drift",
        action="store_true",
        help=(
            "Exit 1 if any source has a non-ok drift state. CI uses this to "
            "fail the cron job (which triggers the Slack-on-failure step)."
        ),
    )
    args = parser.parse_args()

    # Lazy imports so `--help` works without dragging the registry.
    from automation.url_drift_sentinel import (
        classify, load_baseline, probe_url, write_state,
    )
    from pulpo.scrapers._metadata import SCRAPER_METADATA

    metadata = SCRAPER_METADATA
    if args.source:
        if args.source not in metadata:
            print(
                f"error: source {args.source!r} not in SCRAPER_METADATA; "
                f"available: {sorted(metadata.keys())}",
                file=sys.stderr,
            )
            return 2
        metadata = {args.source: metadata[args.source]}

    any_drift = False
    rows = []
    for source, meta in sorted(metadata.items()):
        url = meta.get("health_probe_url")
        if not url:
            rows.append((source, "skipped", "no health_probe_url", 0))
            continue
        baseline = load_baseline(source, args.drift_dir)
        probe = probe_url(source, url, timeout_s=args.timeout_s)
        classified = classify(probe, baseline)
        write_state(classified, args.drift_dir)
        if classified.drift_state != "ok":
            any_drift = True
        rows.append((
            source,
            classified.drift_state,
            classified.reason,
            probe.duration_ms,
        ))

    # Print a compact table.
    print(f"{'source':<22} {'state':<16} {'duration':<10} reason")
    print("-" * 80)
    for source, state, reason, duration_ms in rows:
        print(f"{source:<22} {state:<16} {duration_ms:>4}ms     {reason}")

    print(f"\nWrote per-source state to {args.drift_dir}/")
    if any_drift:
        print("\n[url_drift] at least one source has a non-ok drift state — see table above.")
        if args.fail_on_drift:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
