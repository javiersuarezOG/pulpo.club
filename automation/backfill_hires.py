"""One-off retroactive hi-res photo backfill.

Companion to ``automation/repick_heroes.py`` (PR #292) — picture-flow only,
no scrape/enrichment/ranker. Where ``repick_heroes.py`` re-runs the existing
hero picker (1920×1080 derivative), this script populates the PARALLEL
hi-res derivative pipeline: ``web/photos-hires/<source>_<id>.hires.jpg``
preserving native broker resolution.

Reuses production helpers (single source of truth):

    _download_hires_photos  (automation/run.py:754)
        — fetch native bytes via httpx, transform_hires_url() per source,
          dim gate ≥1080×1080, resdet upscale-fraud detection, sidecar write.

The script then writes only the ``hires_*`` fields onto each listing in
``web/data/ranked.json`` — atomic temp+rename. Disjoint from the ``hero_*``
field namespace so it cannot clobber Stage A's repick output.

Usage:

    python automation/backfill_hires.py                              # dry-run
    python automation/backfill_hires.py --execute                    # write
    python automation/backfill_hires.py --execute --limit 20         # first 20
    python automation/backfill_hires.py --execute --source goodlife  # filter

Environment (consumed by ``_download_hires_photos``):

    PULPO_HIRES_ENABLED          set to "1" by the workflow wrapper
    PULPO_HIRES_SOURCES          allowlist (comma-separated source codes)
    PULPO_HIRES_BUDGET_S         wall budget; default 1500 (pipeline) / 10800 (backfill)
    PULPO_HIRES_LIMIT            also exposed; --limit takes precedence here
    PULPO_HIRES_SHADOW           informational; flagged in metrics row
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# Reuse production helpers — same semantics as the nightly hi-res step.
from automation.run import (  # noqa: E402  -- sys.path manipulation above
    _download_hires_photos,
)
from pulpo.models import Listing  # noqa: E402

DEFAULT_INPUT = REPO / "web" / "data" / "ranked.json"

# Fields the hi-res step writes onto each Listing. We persist ONLY these
# back to ranked.json — the rest of the listing dict (text enrichment,
# geocoding, ranker output, etc.) stays untouched.
HIRES_FIELDS = (
    "hires_available",
    "hires_eligible",
    "hires_width",
    "hires_height",
    "hires_photo_quality_score",
    "hires_resdet_upscaled",
    "hires_quarantined",
)


def _filter_listings(
    data: list[dict],
    *,
    limit: Optional[int],
    sources: Optional[set[str]],
) -> list[dict]:
    out = data
    if sources:
        out = [li for li in out if li.get("source") in sources]
    if limit is not None and limit > 0:
        out = out[:limit]
    return out


def _dict_to_listing(d: dict) -> Listing:
    """Rehydrate a Listing from a ranked.json row. Only the fields the
    hi-res step needs (``source``, ``source_id``, ``photo_urls``,
    ``rank_score`` for ordering) — defaults cover the rest."""
    return Listing(
        source=d.get("source") or "",
        source_id=d.get("source_id") or "",
        url=d.get("url") or "",
        scraped_at=d.get("scraped_at") or "",
        title=d.get("title") or "",
        photo_urls=list(d.get("photo_urls") or []),
        rank_score=d.get("rank_score"),
    )


def _atomic_write_json(path: Path, data) -> None:
    """Temp-file + rename so a partial write can't corrupt the file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    p = argparse.ArgumentParser(description="One-off retroactive hi-res photo backfill")
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                   help=f"ranked.json path (default {DEFAULT_INPUT})")
    p.add_argument("--execute", action="store_true",
                   help="actually call the hi-res step + write hires_* fields back to "
                        "ranked.json. Without this flag the run is a dry-run that "
                        "only reports the scope it would have processed.")
    p.add_argument("--limit", type=int, default=None,
                   help="operate on first N listings (after --source filter)")
    p.add_argument("--source", type=str, default=None,
                   help="comma-separated source codes (e.g. remax,goodlife) — filter listings")
    args = p.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found", file=sys.stderr)
        return 1

    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        print("ERROR: ranked.json is empty or not a list", file=sys.stderr)
        return 1

    sources = None
    if args.source:
        sources = {s.strip() for s in args.source.split(",") if s.strip()}

    targets = _filter_listings(data, limit=args.limit, sources=sources)
    n_targets = len(targets)
    if n_targets == 0:
        print("[backfill-hires] no listings matched filter — nothing to do")
        return 0

    from automation._config import env_bool, env_str
    enabled = env_bool("PULPO_HIRES_ENABLED", False)
    sources_env = env_str("PULPO_HIRES_SOURCES", "")
    print(f"[backfill-hires] mode={'execute' if args.execute else 'dry-run'} "
          f"listings={n_targets} PULPO_HIRES_ENABLED={enabled} "
          f"PULPO_HIRES_SOURCES='{sources_env}'")

    if not args.execute:
        print("[backfill-hires] dry-run — no network, no writes. "
              "Re-invoke with --execute to act.")
        return 0
    if not enabled:
        print("ERROR: PULPO_HIRES_ENABLED is not set — refusing to no-op silently. "
              "Export PULPO_HIRES_ENABLED=1 and rerun.", file=sys.stderr)
        return 1

    # Rehydrate Listing objects so _download_hires_photos can mutate them.
    listings = [_dict_to_listing(li) for li in targets]
    # Build index of source+id → ranked.json row dict for back-write.
    index: dict[tuple[str, str], dict] = {
        (li.get("source") or "", li.get("source_id") or ""): li for li in targets
    }

    t0 = time.monotonic()
    summary = _download_hires_photos(listings, REPO)
    elapsed = time.monotonic() - t0

    # Persist hires_* fields back onto matching ranked.json rows.
    n_persisted = 0
    for li in listings:
        row = index.get((li.source, li.source_id))
        if row is None:
            continue
        any_set = False
        for f in HIRES_FIELDS:
            v = getattr(li, f, None)
            # Don't write None over an existing value (re-run of a partial
            # backfill that already wrote some fields). The hires-step
            # idempotency relies on the sidecar; we mirror that here.
            if v is None:
                continue
            row[f] = v
            any_set = True
        if any_set:
            n_persisted += 1

    _atomic_write_json(args.input, data)

    print(f"[backfill-hires] done elapsed={elapsed:.0f}s "
          f"persisted_rows={n_persisted}/{n_targets} summary={summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
