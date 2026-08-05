"""Read supply-side goal metrics from the git history of web/data.

The nightly pipeline commits its outputs to main, so `git log` over
`web/data/*.json` IS the time-series database — no extra infra. This
script walks the last N days of commits touching the relevant data file
and emits a JSON series per requested metric, plus guardrail evaluation
for a goal's supply-source guardrails (posthog guardrails are handled by
scripts/goal_metrics.py; mixed goals run both readers).

Series extractors (add here, reference by name in a goal-spec):
  listing_total           last_updated.json  -> total_listings
  listing_dropped         last_updated.json  -> dropped
  nightly_duration_s      last_updated.json  -> duration_seconds
  hero_with_local_pct     photo_contract.json -> with_local_path/ranked_total*100
  hero_local_missing_rate photo_contract.json -> missing_rate
  sources_green_pct       kpi_dashboard.json -> % green among non-paused sources
  visible_total           kpi_dashboard.json -> kpi.total_visible_listings

Usage:
  python3 scripts/goal_supply_metrics.py --goal image-quality
  python3 scripts/goal_supply_metrics.py --series listing_total --days 14
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from goal_registry import REPO_ROOT, load_spec  # noqa: E402


def _extract_listing_total(doc: dict) -> float | None:
    return doc.get("total_listings")


def _extract_listing_dropped(doc: dict) -> float | None:
    return doc.get("dropped")


def _extract_nightly_duration(doc: dict) -> float | None:
    return doc.get("duration_seconds")


def _extract_hero_with_local_pct(doc: dict) -> float | None:
    total = doc.get("ranked_total")
    with_local = doc.get("with_local_path")
    if not total or with_local is None:
        return None
    return round(100.0 * with_local / total, 2)


def _extract_hero_missing_rate(doc: dict) -> float | None:
    return doc.get("missing_rate")


def _extract_sources_green_pct(doc: dict) -> float | None:
    coverage = (doc.get("kpi") or {}).get("per_source_coverage") or {}
    considered = [s for s in coverage.values() if s.get("status") != "paused"]
    if not considered:
        return None
    green = sum(1 for s in considered if s.get("status") == "green")
    return round(100.0 * green / len(considered), 2)


def _extract_visible_total(doc: dict) -> float | None:
    return (doc.get("kpi") or {}).get("total_visible_listings")


# series name -> (data file relative to repo root, extractor)
SERIES: dict = {
    "listing_total": ("web/data/last_updated.json", _extract_listing_total),
    "listing_dropped": ("web/data/last_updated.json", _extract_listing_dropped),
    "nightly_duration_s": ("web/data/last_updated.json", _extract_nightly_duration),
    "hero_with_local_pct": ("web/data/photo_contract.json", _extract_hero_with_local_pct),
    "hero_local_missing_rate": ("web/data/photo_contract.json", _extract_hero_missing_rate),
    "sources_green_pct": ("web/data/kpi_dashboard.json", _extract_sources_green_pct),
    "visible_total": ("web/data/kpi_dashboard.json", _extract_visible_total),
}


def _git(*argv: str) -> str:
    result = subprocess.run(
        ["git", *argv],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(argv)} failed:\n{result.stderr.strip()}")
    return result.stdout


def _commits_touching(path: str, days: int) -> list[tuple[str, str]]:
    """[(sha, iso-committer-date)] newest first for commits touching path."""
    raw = _git(
        "log", f"--since={days}.days", "--format=%H|%cI", "--", path
    ).strip()
    if not raw:
        return []
    pairs: list[tuple[str, str]] = []
    for line in raw.splitlines():
        sha, _, ts = line.partition("|")
        pairs.append((sha, ts))
    return pairs


def series_points(name: str, days: int) -> list[dict]:
    """[{ts, value}] oldest-first over the git history window, including
    the current working-tree state as the newest point."""
    path, extract = SERIES[name]
    points: list[dict] = []
    for sha, ts in _commits_touching(path, days):
        try:
            doc = json.loads(_git("show", f"{sha}:{path}"))
        except SystemExit:
            continue  # file absent at that commit
        except json.JSONDecodeError:
            continue
        value = extract(doc)
        if value is not None:
            points.append({"ts": ts, "value": value, "sha": sha[:12]})
    points.reverse()
    # Working tree may be ahead of the last commit (mid-run); append if parseable.
    live = REPO_ROOT / path
    if live.exists():
        try:
            value = extract(json.loads(live.read_text(encoding="utf-8")))
            if value is not None and (not points or points[-1]["value"] != value):
                points.append(
                    {"ts": datetime.now(timezone.utc).isoformat(), "value": value, "sha": "worktree"}
                )
        except (json.JSONDecodeError, OSError):
            pass
    return points


def guardrail_pass(op: str, value: float | None, threshold: float) -> bool | None:
    if value is None:
        return None
    return value <= threshold if op == "<=" else value >= threshold


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--goal", help="goal name under goals/")
    group.add_argument("--series", choices=sorted(SERIES), help="single series")
    parser.add_argument("--days", type=int, default=14, help="history window (default 14)")
    args = parser.parse_args()

    out: dict = {"measured_at": datetime.now(timezone.utc).isoformat(), "window_days": args.days}

    if args.series:
        pts = series_points(args.series, args.days)
        out["series"] = {args.series: pts}
        out["metric"] = {
            "value": pts[-1]["value"] if pts else None,
            "sample_n": len(pts),
        }
        print(json.dumps(out, indent=2))
        return 0

    spec = load_spec(args.goal)
    out["goal"] = args.goal
    metric = spec["metric"]
    skipped: list[str] = []
    series_out: dict = {}

    if metric["source"] == "supply":
        for name in metric["series"]:
            if name not in SERIES:
                raise SystemExit(f"unknown series {name!r} — add an extractor to {__file__}")
            series_out[name] = series_points(name, args.days)
        primary = metric["series"][0]
        pts = series_out[primary]
        out["metric"] = {
            "primary_series": primary,
            "value": pts[-1]["value"] if pts else None,
            "sample_n": len(pts),
        }
    else:
        out["note"] = (
            "metric.source is not supply — objective comes from "
            "scripts/goal_metrics.py; only supply guardrails run here"
        )

    guardrails: list[dict] = []
    for g in spec.get("guardrails", []):
        if g.get("source") != "supply":
            skipped.append(g["name"])
            continue
        name = g["series"]
        if name not in SERIES:
            raise SystemExit(f"unknown guardrail series {name!r}")
        pts = series_out.get(name) or series_points(name, args.days)
        series_out.setdefault(name, pts)
        value = pts[-1]["value"] if pts else None
        guardrails.append(
            {
                "name": g["name"],
                "series": name,
                "value": value,
                "op": g["op"],
                "threshold": g["threshold"],
                "pass": guardrail_pass(g["op"], value, g["threshold"]),
            }
        )

    out["series"] = series_out
    out["guardrails"] = guardrails
    out["skipped"] = skipped
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
