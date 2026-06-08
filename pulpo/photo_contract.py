"""Card photo-path contract canary (PRD P1-2).

Audit 2026-06-02: 884 of 959 ranked rows pointed at a `hero_photo_path`
whose root file did not exist (most files had been pruned to
`web/photos/_archive/<date>/` while the ranked record kept the stale
path). Production fired tens of `/photos/*.jpg` 404s per page load on
`/` and `/browse`.

This module enforces a simple invariant before ranked output is written:

    For every listing with `hero_photo_path` set, the file
    `web/photos/<basename>` must exist on disk.

Listings whose file is missing get `hero_photo_path = None` (the UI's
`Photo` component already falls back gracefully — better a clean
fallback than a 404). Stats are written to
`web/data/photo_contract.json` (consumed by `/api/nightly/health`) and
per-listing events to `web/data/photo_contract_log.jsonl` (append-only
audit trail).

Top-shelf coverage thresholds (browseable top-50, hero top-10) are
computed but not enforced — the caller decides whether to fail nightly
based on the returned stats.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from automation.country_sidecars import write_json_sidecar


CONTRACT_FILENAME = "photo_contract.json"
LOG_FILENAME = "photo_contract_log.jsonl"

# PRD P1-2 thresholds. Top-50 browseable must be ≥95% present; first
# viewport of every home shelf ≥90%; top-10 hero candidates 100%.
TOP_BROWSE_N = 50
TOP_HERO_N = 10
GLOBAL_MISSING_RATE_THRESHOLD = 0.05  # >5% missing fails the canary
TOP_BROWSE_COVERAGE_THRESHOLD = 0.95
TOP_HERO_COVERAGE_THRESHOLD = 1.0


@dataclass
class PhotoContractStats:
    """Summary stats written to `photo_contract.json`."""

    ranked_total: int = 0
    with_local_path: int = 0
    local_path_exists: int = 0
    local_path_missing: int = 0
    nulled: int = 0
    top_browse_n: int = TOP_BROWSE_N
    top_browse_present: int = 0
    top_browse_missing: int = 0
    top_hero_n: int = TOP_HERO_N
    top_hero_present: int = 0
    top_hero_missing: int = 0
    examples_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        missing_rate = (
            self.local_path_missing / self.with_local_path
            if self.with_local_path else 0.0
        )
        top_browse_coverage = (
            self.top_browse_present / max(1, self.top_browse_n)
        )
        top_hero_coverage = (
            self.top_hero_present / max(1, self.top_hero_n)
        )
        return {
            "ranked_total": self.ranked_total,
            "with_local_path": self.with_local_path,
            "local_path_exists": self.local_path_exists,
            "local_path_missing": self.local_path_missing,
            "missing_rate": round(missing_rate, 4),
            "nulled": self.nulled,
            "top_browse": {
                "n": self.top_browse_n,
                "present": self.top_browse_present,
                "missing": self.top_browse_missing,
                "coverage": round(top_browse_coverage, 4),
            },
            "top_hero": {
                "n": self.top_hero_n,
                "present": self.top_hero_present,
                "missing": self.top_hero_missing,
                "coverage": round(top_hero_coverage, 4),
            },
            "examples_missing": self.examples_missing[:10],
            "thresholds": {
                "global_missing_rate": GLOBAL_MISSING_RATE_THRESHOLD,
                "top_browse_coverage": TOP_BROWSE_COVERAGE_THRESHOLD,
                "top_hero_coverage": TOP_HERO_COVERAGE_THRESHOLD,
            },
            "evaluated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }

    def fails_threshold(self) -> list[str]:
        """Return a list of human-readable threshold violations.

        Empty list = canary green. Caller is the one that decides
        whether to fail nightly; this just centralises the rules.
        """
        out: list[str] = []
        if self.with_local_path:
            rate = self.local_path_missing / self.with_local_path
            if rate > GLOBAL_MISSING_RATE_THRESHOLD:
                out.append(
                    f"global missing rate {rate * 100:.2f}% > "
                    f"{GLOBAL_MISSING_RATE_THRESHOLD * 100:.0f}% threshold"
                )
        if self.top_browse_n:
            coverage = self.top_browse_present / self.top_browse_n
            if coverage < TOP_BROWSE_COVERAGE_THRESHOLD:
                out.append(
                    f"top-{self.top_browse_n} browseable coverage "
                    f"{coverage * 100:.1f}% < "
                    f"{TOP_BROWSE_COVERAGE_THRESHOLD * 100:.0f}% threshold"
                )
        if self.top_hero_n:
            coverage = self.top_hero_present / self.top_hero_n
            if coverage < TOP_HERO_COVERAGE_THRESHOLD:
                out.append(
                    f"top-{self.top_hero_n} hero coverage "
                    f"{coverage * 100:.1f}% < "
                    f"{TOP_HERO_COVERAGE_THRESHOLD * 100:.0f}% threshold"
                )
        return out


def _root_file_for(hero_photo_path: str, photos_dir: Path) -> Path:
    """`/photos/<file>.jpg` → `<photos_dir>/<file>.jpg`.

    The `hero_photo_path` is written by `automation/run._download_hero_photos`
    as `f"/photos/{fname}"`. Strip the leading `/photos/` so a future
    contract change (subdirectories, archive paths) is one edit here.
    """
    basename = hero_photo_path.split("/")[-1]
    return photos_dir / basename


def enforce_photo_contract(
    listings: Iterable,
    photos_dir: Path,
    data_dir: Path | None = None,
    *,
    write_sidecars: bool = True,
) -> PhotoContractStats:
    """Walk listings, null out hero_photo_path that doesn't resolve, return stats.

    Args:
        listings: iterable of Listing-like objects with `.hero_photo_path`
                  attribute. Mutated in place — missing paths become None.
        photos_dir: directory holding root photo files (typically
                   `<repo>/web/photos`).
        data_dir: optional dir to write `photo_contract.json` and
                  `photo_contract_log.jsonl`. Default: parent's `data`.
        write_sidecars: when False, skip the disk writes (useful for tests
                  that only want the in-memory mutation + stats).

    Returns:
        PhotoContractStats — also written to `photo_contract.json` when
        `write_sidecars=True`.
    """
    listings_list = list(listings)
    # When the catalogue is smaller than the configured top-shelf
    # window (typical only in fixtures + brand-new countries), clamp
    # the denominator so the coverage rule doesn't always trip.
    effective_top_browse = min(TOP_BROWSE_N, len(listings_list)) or TOP_BROWSE_N
    effective_top_hero = min(TOP_HERO_N, len(listings_list)) or TOP_HERO_N
    stats = PhotoContractStats(
        ranked_total=len(listings_list),
        top_browse_n=effective_top_browse,
        top_hero_n=effective_top_hero,
    )

    log_path = None
    if write_sidecars:
        if data_dir is None:
            data_dir = photos_dir.parent / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        log_path = data_dir / LOG_FILENAME
        # Append-only — never truncate so we keep the audit trail across
        # nightlies. Each row carries `nightly_run_at` so consumers can
        # bucket by run.
        log_handle = log_path.open("a", encoding="utf-8")
    else:
        log_handle = None

    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    for idx, li in enumerate(listings_list):
        path = getattr(li, "hero_photo_path", None)
        if not path:
            continue
        stats.with_local_path += 1
        root = _root_file_for(path, photos_dir)
        if root.exists():
            stats.local_path_exists += 1
            if idx < stats.top_browse_n:
                stats.top_browse_present += 1
            if idx < stats.top_hero_n:
                stats.top_hero_present += 1
        else:
            stats.local_path_missing += 1
            if idx < stats.top_browse_n:
                stats.top_browse_missing += 1
            if idx < stats.top_hero_n:
                stats.top_hero_missing += 1
            # Audit trail BEFORE the in-place null so the log records
            # the original path the listing pointed at.
            source_id = getattr(li, "source_id", None) or "?"
            source = getattr(li, "source", None) or "?"
            if len(stats.examples_missing) < 20:
                stats.examples_missing.append(f"{source}_{source_id} {path}")
            if log_handle is not None:
                log_handle.write(json.dumps({
                    "ts": now_iso,
                    "source": source,
                    "source_id": source_id,
                    "rank_index": idx,
                    "hero_photo_path": path,
                    "missing_root": str(root),
                }) + "\n")
            li.hero_photo_path = None
            stats.nulled += 1

    if log_handle is not None:
        log_handle.close()

    if write_sidecars and data_dir is not None:
        out = data_dir / CONTRACT_FILENAME
        write_json_sidecar(out, stats.to_dict(), indent=2, sort_keys=False)

    return stats
