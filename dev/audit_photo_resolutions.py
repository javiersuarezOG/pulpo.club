#!/usr/bin/env python3
"""Audit per-source photo resolutions (Phase 4 O1, PR-A scaffolding).

Two modes:

  --mode dump (default in PR-A)
    For each fixture ID, fetch the first photo_url and print the
    long-side dimension as observed today. No upgrade applied. The
    output guides PR-B's per-site `full_res.rules` authoring.

  --mode upgrade (the PR-B acceptance gate)
    Re-apply pulpo.scrapers._photo_url_upgrade.upgrade_photo_urls to
    each fixture's URLs, print before/after/delta, and exit 0 when
    >= 7 of the 9 fixtures have after_long_side >= 1920 (1 otherwise).

The 9 fixture source_ids are hard-coded below. Source of truth lives
in the sibling repo:

    pulpo-social/test_images/may-15-17-rejected/GRADES.md

Sebastian populates the list when PR-B opens. Until then the dump
defaults to the first N listings with photos from
web/data/ranked.json so the script still produces actionable output.

This script reads the *first 8 KB* of each image — Pillow can read
JPEG dimensions from the SOF marker without the full file, keeping
the bandwidth budget tiny.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

# Source of truth: pulpo-social/test_images/may-15-17-rejected/GRADES.md
# (sibling repo, not in this tree). Operator pastes the 9 IDs here once.
# Format: "<source>__<source_id>" matching the pipeline's join key.
FIXTURE_IDS: list[str] = [
    # TODO(PR-B): paste 9 IDs from pulpo-social GRADES.md
]

# Acceptance gate (PR-B): at least this many fixtures must reach >= 1920px
# after upgrade. 7/9 is the spec's pass threshold.
ACCEPT_MIN_AFTER_LONG_SIDE_PX = 1920
ACCEPT_PASS_COUNT = 7


def _peek_long_side(url: str, timeout_s: float = 5.0) -> Optional[int]:
    """Fetch the first 8 KB of a JPEG/PNG and decode its dimensions.

    Returns max(width, height) or None on any failure (network, decode,
    Pillow not installed). Range-request is best-effort; servers that
    ignore Range return the full file — still bounded by the read.
    """
    try:
        from PIL import Image
    except ImportError:
        print("[audit] Pillow not installed; cannot peek dimensions", file=sys.stderr)
        return None
    try:
        import httpx
    except ImportError:
        print("[audit] httpx not installed; cannot fetch URL", file=sys.stderr)
        return None
    try:
        with httpx.stream(
            "GET",
            url,
            headers={"Range": "bytes=0-8191"},
            timeout=timeout_s,
            follow_redirects=True,
        ) as r:
            r.raise_for_status()
            buf = io.BytesIO()
            total = 0
            for chunk in r.iter_bytes(chunk_size=4096):
                buf.write(chunk)
                total += len(chunk)
                if total >= 8192:
                    break
            buf.seek(0)
            try:
                img = Image.open(buf)
                w, h = img.size
            except Exception:
                # Some servers ignore Range for small files; refetch in full.
                with httpx.stream("GET", url, timeout=timeout_s, follow_redirects=True) as r2:
                    r2.raise_for_status()
                    full = io.BytesIO(r2.read())
                img = Image.open(full)
                w, h = img.size
            return max(int(w), int(h))
    except Exception as e:
        print(f"[audit] {url[:80]}…  fetch/decode failed: {e}", file=sys.stderr)
        return None


def _load_ranked() -> list[dict]:
    """Read web/data/ranked.json as the URL source. Falls back to []."""
    p = REPO_ROOT / "web" / "data" / "ranked.json"
    if not p.exists():
        print(f"[audit] missing {p}", file=sys.stderr)
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[audit] failed to parse ranked.json: {e}", file=sys.stderr)
        return []
    return data if isinstance(data, list) else data.get("listings") or []


def _join_key(li: dict) -> str:
    return f"{li.get('source')}__{li.get('source_id')}"


def _resolve_fixtures(ranked: list[dict]) -> list[dict]:
    """Return the subset of ranked listings matching FIXTURE_IDS.

    When FIXTURE_IDS is empty (PR-A scaffolding state), fall back to the
    first 9 ranked listings that have at least one photo_url.
    """
    if FIXTURE_IDS:
        by_key = {_join_key(li): li for li in ranked}
        missing = [fid for fid in FIXTURE_IDS if fid not in by_key]
        if missing:
            print(
                f"[audit] {len(missing)} fixture IDs not present in ranked.json: "
                f"{missing}",
                file=sys.stderr,
            )
        return [by_key[fid] for fid in FIXTURE_IDS if fid in by_key]
    # Fallback: first 9 with photos
    out: list[dict] = []
    for li in ranked:
        if li.get("photo_urls"):
            out.append(li)
            if len(out) >= 9:
                break
    return out


def _first_photo(li: dict) -> Optional[str]:
    urls = li.get("photo_urls") or []
    return urls[0] if urls else None


def _print_row(label: str, before: Optional[int], after: Optional[int] = None) -> None:
    if after is None:
        before_s = str(before) if before is not None else "—"
        print(f"  {label:<42} {before_s:>6}")
    else:
        before_s = str(before) if before is not None else "—"
        after_s = str(after) if after is not None else "—"
        delta = (
            f"{(after - before):+d}"
            if (before is not None and after is not None)
            else "—"
        )
        print(f"  {label:<42} {before_s:>6}  →  {after_s:>6}  {delta:>+6}")


def cmd_dump(fixtures: list[dict]) -> int:
    print(f"[audit] mode=dump  fixtures={len(fixtures)}")
    print(f"  {'source__id':<42} {'long_side':>6}")
    for li in fixtures:
        key = _join_key(li)
        url = _first_photo(li)
        if not url:
            _print_row(key, None)
            continue
        before = _peek_long_side(url)
        _print_row(key, before)
    return 0


def cmd_upgrade(fixtures: list[dict]) -> int:
    from pulpo.scrapers._photo_url_upgrade import upgrade_photo_urls

    print(f"[audit] mode=upgrade  fixtures={len(fixtures)}")
    print(f"  {'source__id':<42} {'before':>6}  →  {'after':>6}  {'delta':>6}")
    pass_count = 0
    for li in fixtures:
        key = _join_key(li)
        urls = li.get("photo_urls") or []
        if not urls:
            _print_row(key, None)
            continue
        before = _peek_long_side(urls[0])
        upgraded = upgrade_photo_urls(li.get("source") or "", urls)
        after = _peek_long_side(upgraded[0]) if upgraded else None
        _print_row(key, before, after)
        if after is not None and after >= ACCEPT_MIN_AFTER_LONG_SIDE_PX:
            pass_count += 1
    print(
        f"[audit] pass={pass_count}/{len(fixtures)} "
        f"(gate: >= {ACCEPT_PASS_COUNT} at long_side >= {ACCEPT_MIN_AFTER_LONG_SIDE_PX}px)"
    )
    return 0 if pass_count >= ACCEPT_PASS_COUNT else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--mode",
        choices=("dump", "upgrade"),
        default=os.environ.get("PULPO_AUDIT_MODE", "dump"),
        help="dump = read current dimensions; upgrade = apply transforms + gate",
    )
    args = parser.parse_args()

    ranked = _load_ranked()
    if not ranked:
        print("[audit] no ranked listings found — populate web/data/ranked.json first")
        return 1
    fixtures = _resolve_fixtures(ranked)
    if not fixtures:
        print("[audit] no fixtures resolved (FIXTURE_IDS empty AND no listings with photos)")
        return 1

    if args.mode == "dump":
        return cmd_dump(fixtures)
    return cmd_upgrade(fixtures)


if __name__ == "__main__":
    sys.exit(main())
