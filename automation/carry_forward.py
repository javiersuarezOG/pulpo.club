"""Source-level carry-forward for failed scrapes.

When a source fails or zero-yields, the full-replacement ranked artifact
would otherwise drop its prior listings immediately. This module can
append yesterday's listings for failed sources at the tail of the fresh
ranked list, marked with their ledger existence status.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from automation.listing_ledger import LedgerEntry, STALE_THRESHOLD_RUNS
from pulpo.models import Listing


def listing_key(source: str, source_id: str) -> str:
    return f"{source}|{source_id}"


def load_previous_ranked_from_git(
    repo: Path,
    *,
    ref: str = "origin/main",
    path: str = "web/data/ranked.json",
) -> list[dict]:
    """Load last-known-good ranked.json from git, or [] when unavailable."""
    try:
        proc = subprocess.run(
            ["git", "show", f"{ref}:{path}"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        data = json.loads(proc.stdout)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def dict_to_listing(row: Mapping) -> Listing | None:
    """Best-effort rehydration of a ranked.json row into Listing."""
    try:
        field_names = {f.name for f in dataclasses.fields(Listing)}
        payload = {k: v for k, v in dict(row).items() if k in field_names}
        required_defaults = {
            "source": str(row.get("source") or "unknown"),
            "source_id": str(row.get("source_id") or "unknown"),
            "url": str(row.get("url") or ""),
            "scraped_at": str(row.get("scraped_at") or row.get("first_seen_at") or ""),
            "title": str(row.get("title") or "Untitled"),
        }
        for key, value in required_defaults.items():
            payload.setdefault(key, value)
        return Listing(**payload)
    except Exception:
        return None


def _ledger_status(entry: LedgerEntry | None) -> str:
    if entry is None:
        return "missing_recently"
    if entry.existence_status == "stale":
        return "stale"
    # A whole-source failure deliberately does not advance the ledger's
    # missing streak, but the product row is still stale relative to the
    # current scrape and should render with a freshness chip.
    return "missing_recently"


def merge_carry_forward(
    *,
    today: Sequence[Listing],
    yesterday_ranked: Sequence[Mapping],
    ledger: Mapping[str, LedgerEntry],
    failed_sources: Iterable[str],
) -> tuple[list[Listing], dict]:
    """Append stale-but-known listings from failed sources to fresh rows.

    Succeeded-but-shrank sources are intentionally not carried forward:
    those absences are meaningful removals.
    """
    failed = {s for s in failed_sources if s}
    present = {listing_key(li.source, li.source_id) for li in today}
    merged = list(today)
    carried: list[Listing] = []
    skipped_stale = 0

    for row in yesterday_ranked:
        source = str(row.get("source") or "")
        source_id = str(row.get("source_id") or "")
        if source not in failed or not source_id:
            continue
        key = listing_key(source, source_id)
        if key in present:
            continue
        entry = ledger.get(key)
        status = _ledger_status(entry)
        if status == "stale":
            skipped_stale += 1
            continue
        li = dict_to_listing(row)
        if li is None:
            continue
        li.existence_status = status
        if entry is not None:
            li.last_seen_at = entry.last_seen_at
            li.missing_since = entry.missing_since
        li.rank = None
        # Tail demotion: any consumer sorting by rank_score keeps fresh
        # rows above carried rows.
        li.rank_score = -1.0
        li.rank_reasons = list(li.rank_reasons or []) + ["carried_forward_failed_source"]
        carried.append(li)
        present.add(key)

    start_rank = len(merged) + 1
    for idx, li in enumerate(carried):
        li.rank = start_rank + idx
    merged.extend(carried)

    metrics = {
        "enabled": True,
        "failed_sources": sorted(failed),
        "fresh_count": len(today),
        "carried_count": len(carried),
        "skipped_stale": skipped_stale,
        "stale_threshold_runs": STALE_THRESHOLD_RUNS,
    }
    return merged, metrics


def preview_carry_forward_count(
    *,
    today: Sequence[Listing],
    yesterday_ranked: Sequence[Mapping],
    ledger: Mapping[str, LedgerEntry],
    failed_sources: Iterable[str],
) -> dict:
    _merged, metrics = merge_carry_forward(
        today=today,
        yesterday_ranked=yesterday_ranked,
        ledger=ledger,
        failed_sources=failed_sources,
    )
    metrics["enabled"] = False
    return metrics
