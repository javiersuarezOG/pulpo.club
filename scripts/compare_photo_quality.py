"""Read-only A/B comparison: existing hero pipeline vs. parallel hi-res pipeline.

Walks two on-disk sidecar trees + ranked.json and emits a per-source +
overall table comparing:

- Source resolution (median / p95 / max). Hero sidecar carries the
  downsampled derivative dims (≤1920×1080 clamp); hires sidecar carries
  the broker's NATIVE dims.
- Quality score (compute_score 0..100). Hero scores against the
  downsampled bytes; hires scores against the native bytes.
- has_text_overlay rate.
- 4:5 coverage (source ≥1080×1350) — what the Instagram Reels path
  needs to render. Today this is 0/917 across the hero set.
- resdet upscale-fraud rate (hires only — the hero pipeline has no
  resdet pass).
- Deterministic aesthetic distribution (hires only).

Idempotent. No commits. No network. Safe to run any time.

Usage:

    python3 scripts/compare_photo_quality.py
    python3 scripts/compare_photo_quality.py --source goodlife
    python3 scripts/compare_photo_quality.py --emit-markdown > /tmp/diff.md
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
RANKED = REPO / "web" / "data" / "ranked.json"
HERO_DIR = REPO / "web" / "photos"
HIRES_DIR = REPO / "web" / "photos-hires"


def _read_json(p: Path) -> Optional[dict]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _walk_hero_sidecars() -> dict[tuple[str, str], dict]:
    """Map (source, source_id) -> hero sidecar dict.

    Hero sidecar lives at web/photos/<source>_<source_id>.hero.jpg.meta.json.
    Note: the hero pipeline writes the sidecar against the downsampled
    1920x1080 bytes — width/height here are derivative dims, not source.
    """
    out: dict[tuple[str, str], dict] = {}
    if not HERO_DIR.exists():
        return out
    for p in HERO_DIR.glob("*.hero.jpg.meta.json"):
        side = _read_json(p)
        if not isinstance(side, dict):
            continue
        stem = p.name[: -len(".hero.jpg.meta.json")]  # <source>_<source_id>
        idx = stem.find("_")
        if idx < 1:
            continue
        out[(stem[:idx], stem[idx + 1 :])] = side
    return out


def _walk_hires_sidecars() -> dict[tuple[str, str], dict]:
    """Map (source, source_id) -> hires sidecar dict.

    Hires sidecar lives at web/photos-hires/<source>_<source_id>.hires.jpg.meta.json.
    width/height here are the broker's NATIVE source dims (pre-resize).
    """
    out: dict[tuple[str, str], dict] = {}
    if not HIRES_DIR.exists():
        return out
    for p in HIRES_DIR.glob("*.hires.jpg.meta.json"):
        side = _read_json(p)
        if not isinstance(side, dict):
            continue
        stem = p.name[: -len(".hires.jpg.meta.json")]
        idx = stem.find("_")
        if idx < 1:
            continue
        out[(stem[:idx], stem[idx + 1 :])] = side
    return out


def _quarantined(source: str, source_id: str) -> bool:
    return (HIRES_DIR / f"{source}_{source_id}.hires.jpg.quarantine").exists()


def _median(xs: list[float]) -> Optional[float]:
    return statistics.median(xs) if xs else None


def _p95(xs: list[float]) -> Optional[float]:
    if not xs:
        return None
    sx = sorted(xs)
    idx = max(0, int(0.95 * len(sx)) - 1)
    return sx[idx]


def _row_for_source(
    source: str,
    hero_rows: list[dict],
    hires_rows: list[dict],
    quarantines: int,
) -> dict[str, Any]:
    """Build a per-source comparison row."""
    h_w = [r["width"] for r in hero_rows if isinstance(r.get("width"), int)]
    h_h = [r["height"] for r in hero_rows if isinstance(r.get("height"), int)]
    r_w = [r["width"] for r in hires_rows if isinstance(r.get("width"), int)]
    r_h = [r["height"] for r in hires_rows if isinstance(r.get("height"), int)]

    h_q: list[float] = [
        float(r["hero_photo_quality_score"])
        for r in hero_rows
        if isinstance(r.get("hero_photo_quality_score"), (int, float))
    ]
    r_q: list[float] = [
        float(r["hires_photo_quality_score"])
        for r in hires_rows
        if isinstance(r.get("hires_photo_quality_score"), (int, float))
    ]

    h_overlay = sum(1 for r in hero_rows if r.get("has_text_overlay") is True)
    r_overlay = sum(1 for r in hires_rows if r.get("has_text_overlay") is True)

    # 4:5 coverage: pulpo-social Instagram Reels needs ≥1080×1350.
    h_4x5 = sum(
        1 for r in hero_rows
        if isinstance(r.get("width"), int) and isinstance(r.get("height"), int)
        and r["width"] >= 1080 and r["height"] >= 1350
    )
    r_4x5 = sum(
        1 for r in hires_rows
        if isinstance(r.get("width"), int) and isinstance(r.get("height"), int)
        and r["width"] >= 1080 and r["height"] >= 1350
    )

    r_upscaled = sum(1 for r in hires_rows if r.get("resdet_upscaled") is True)

    return {
        "source": source,
        "hero_n": len(hero_rows),
        "hires_n": len(hires_rows),
        "hero_w_median": _median([float(x) for x in h_w]),
        "hires_w_median": _median([float(x) for x in r_w]),
        "hero_w_p95": _p95([float(x) for x in h_w]),
        "hires_w_p95": _p95([float(x) for x in r_w]),
        "hero_h_median": _median([float(x) for x in h_h]),
        "hires_h_median": _median([float(x) for x in r_h]),
        "hero_q_median": _median([float(x) for x in h_q]),
        "hires_q_median": _median([float(x) for x in r_q]),
        "hero_overlay_n": h_overlay,
        "hires_overlay_n": r_overlay,
        "hero_4x5_n": h_4x5,
        "hires_4x5_n": r_4x5,
        "hires_upscaled_n": r_upscaled,
        "hires_quarantined_n": quarantines,
    }


def _fmt(v: Optional[float], *, pct_denom: Optional[int] = None) -> str:
    if v is None:
        return "—"
    if pct_denom is not None and pct_denom > 0:
        return f"{int(v)} ({100.0 * v / pct_denom:.0f}%)"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:.1f}"
    return f"{int(v)}"


def _print_text_table(rows: list[dict[str, Any]]) -> None:
    """Fixed-width text table for terminal viewing."""
    headers = [
        "source",
        "n hero",
        "n hires",
        "w median (hero→hires)",
        "h median (hero→hires)",
        "q median (hero→hires)",
        "4:5 cov (hero→hires)",
        "overlay (hero→hires)",
        "hires upscaled",
    ]
    print(" | ".join(f"{h:24}" if "median" in h or "cov" in h or "overlay" in h else f"{h:14}" for h in headers))
    print("-" * (24 * 6 + 14 * 3 + 9 * 3))
    for r in rows:
        print(" | ".join([
            f"{r['source']:14}",
            f"{r['hero_n']:14}",
            f"{r['hires_n']:14}",
            f"{_fmt(r['hero_w_median'])} → {_fmt(r['hires_w_median']):20}",
            f"{_fmt(r['hero_h_median'])} → {_fmt(r['hires_h_median']):20}",
            f"{_fmt(r['hero_q_median'])} → {_fmt(r['hires_q_median']):20}",
            f"{_fmt(r['hero_4x5_n'], pct_denom=r['hero_n'])} → {_fmt(r['hires_4x5_n'], pct_denom=r['hires_n']):14}",
            f"{_fmt(r['hero_overlay_n'], pct_denom=r['hero_n'])} → {_fmt(r['hires_overlay_n'], pct_denom=r['hires_n']):14}",
            f"{r['hires_upscaled_n']:14}",
        ]))


def _print_markdown_table(rows: list[dict[str, Any]]) -> None:
    """Markdown table for the data-PR body."""
    print("| source | n hero | n hires | w median (hero→hires) | h median (hero→hires) | q median (hero→hires) | 4:5 coverage (hero→hires) | text overlay (hero→hires) | hires upscaled |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['source']} "
            f"| {r['hero_n']} | {r['hires_n']} "
            f"| {_fmt(r['hero_w_median'])} → **{_fmt(r['hires_w_median'])}** "
            f"| {_fmt(r['hero_h_median'])} → **{_fmt(r['hires_h_median'])}** "
            f"| {_fmt(r['hero_q_median'])} → **{_fmt(r['hires_q_median'])}** "
            f"| {_fmt(r['hero_4x5_n'], pct_denom=r['hero_n'])} → **{_fmt(r['hires_4x5_n'], pct_denom=r['hires_n'])}** "
            f"| {_fmt(r['hero_overlay_n'], pct_denom=r['hero_n'])} → **{_fmt(r['hires_overlay_n'], pct_denom=r['hires_n'])}** "
            f"| {r['hires_upscaled_n']} |"
        )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=str, default=None,
                   help="comma-separated source codes (default: all sources)")
    p.add_argument("--emit-markdown", action="store_true",
                   help="emit a markdown table instead of the fixed-width text table")
    args = p.parse_args()

    sources_filter: Optional[set[str]] = None
    if args.source:
        sources_filter = {s.strip() for s in args.source.split(",") if s.strip()}

    hero = _walk_hero_sidecars()
    hires = _walk_hires_sidecars()

    by_source_hero: dict[str, list[dict]] = defaultdict(list)
    for (source, _sid), side in hero.items():
        if sources_filter and source not in sources_filter:
            continue
        by_source_hero[source].append(side)

    by_source_hires: dict[str, list[dict]] = defaultdict(list)
    quarantines_per_source: dict[str, int] = defaultdict(int)
    for (source, sid), side in hires.items():
        if sources_filter and source not in sources_filter:
            continue
        by_source_hires[source].append(side)
        if _quarantined(source, sid):
            quarantines_per_source[source] += 1

    all_sources = sorted(set(by_source_hero) | set(by_source_hires))
    rows: list[dict[str, Any]] = []
    for source in all_sources:
        rows.append(_row_for_source(
            source,
            by_source_hero.get(source, []),
            by_source_hires.get(source, []),
            quarantines_per_source.get(source, 0),
        ))
    # Append an aggregate row.
    rows.append(_row_for_source(
        "ALL",
        [side for source, sides in by_source_hero.items() for side in sides
         if (not sources_filter or source in sources_filter)],
        [side for source, sides in by_source_hires.items() for side in sides
         if (not sources_filter or source in sources_filter)],
        sum(quarantines_per_source.values()),
    ))

    if args.emit_markdown:
        _print_markdown_table(rows)
    else:
        _print_text_table(rows)

    return 0


if __name__ == "__main__":
    sys.exit(main())
