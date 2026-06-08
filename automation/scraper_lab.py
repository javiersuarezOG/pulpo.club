"""Scraper Lab — PR-FB-1 of docs/SCRAPER-FEEDBACK-CYCLE-PRD.md.

Single-source fast-path harness: fetch → finalize → validate → dedup →
rank for one scraper, in under two minutes, without touching the
nightly pipeline. Lets a developer iterate on a scraper without waiting
for the 7-hour nightly soak.

Public surface:

    lab_run(slug, *, limit, offline, with_validate, with_dedup,
            with_rank, write_dir=None) -> LabResult

The CLI front door at `pulpo.cli scraper-lab` is a thin argparse
wrapper around this function. `scripts/smoke_scraper.py` continues to
exist for the fetch-only path that pre-dates this module.

LLM enrichment, photo downloads, and `web/data/` mutations are
out-of-scope: this is a dev tool, not a pipeline phase. PostHog stays
quiet for the same reason.
"""
from __future__ import annotations

import importlib
import json
import time
import traceback
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from pulpo.models import Listing
from pulpo.normalize import normalize
from pulpo.ranker import rank
from pulpo.scrapers.lib.dedup_hasher import listing_fingerprint
from automation.validation import validate


@dataclass
class LabResult:
    slug: str
    duration_s: float
    ok: bool
    error: Optional[str] = None
    raw_count: int = 0
    normalized_count: int = 0
    validation: dict[str, int] = field(default_factory=lambda: {"pass": 0, "flag": 0, "drop": 0})
    dedup: dict[str, int] = field(default_factory=lambda: {"kept": 0, "duplicate": 0})
    ranked_count: int = 0
    failures: dict[str, int] = field(default_factory=dict)
    top_ranked: list[dict] = field(default_factory=list)
    raw_sample: list[dict] = field(default_factory=list)
    write_dir: Optional[str] = None

    def to_json(self) -> dict:
        return asdict(self)


def _load_scraper_module(slug: str):
    """Import the scraper module by slug, returning the module or None."""
    try:
        return importlib.import_module(f"pulpo.scrapers.{slug}")
    except ModuleNotFoundError:
        return None


def _fetch_raw(slug: str, limit: int, offline: bool) -> list[dict]:
    mod = _load_scraper_module(slug)
    if mod is None:
        raise RuntimeError(f"no scraper module 'pulpo.scrapers.{slug}'")
    if not hasattr(mod, "crawl"):
        raise RuntimeError(f"module pulpo.scrapers.{slug} has no crawl()")
    listings = mod.crawl(limit=limit, offline=offline or None)
    return list(listings or [])


def _normalize_records(raw: list[dict], slug: str) -> tuple[list[Listing], int]:
    """Normalize raw records into Listings. Drops anything normalize() rejects."""
    out: list[Listing] = []
    dropped = 0
    for r in raw:
        r.setdefault("source", slug)
        li = normalize(r, source=r.get("source") or slug)
        if li is None:
            dropped += 1
            continue
        out.append(li)
    return out, dropped


def _validate_records(
    listings: list[Listing], failures: dict[str, int]
) -> tuple[list[Listing], dict[str, int]]:
    """Run validation, count dispositions, accumulate per-reason failures.

    Listings whose disposition is DROP are excluded from the returned
    list (matches `phase_validate` behavior in `automation/run.py`).
    FLAGGED listings flow through with their warnings attached.
    """
    counts = {"pass": 0, "flag": 0, "drop": 0}
    kept: list[Listing] = []
    for li in listings:
        d = li.to_dict()
        result = validate(d)
        disp = result.disposition.lower()
        counts[disp] = counts.get(disp, 0) + 1
        if result.disposition == "DROP":
            for reason in result.reasons:
                failures[reason] = failures.get(reason, 0) + 1
            continue
        if result.disposition == "FLAG":
            li.validation_status = "FLAG"
            li.validation_warnings = list(result.reasons)
        kept.append(li)
    return kept, counts


def _dedup_records(
    listings: list[Listing],
) -> tuple[list[Listing], int]:
    """Drop records whose fingerprint already appeared.

    The nightly uses a richer cross-source dedup in
    `automation/run.py`; for a single-source dry-run this is sufficient
    to surface accidental in-source duplicates.
    """
    seen: set[str] = set()
    kept: list[Listing] = []
    duplicates = 0
    for li in listings:
        fp = listing_fingerprint(li)
        if fp in seen:
            duplicates += 1
            continue
        seen.add(fp)
        kept.append(li)
    return kept, duplicates


def _raw_sample(raw: list[dict], n: int = 5) -> list[dict]:
    sample = []
    for r in raw[:n]:
        if not isinstance(r, dict):
            continue
        sample.append({
            "title": (r.get("title") or "")[:80],
            "price_usd": r.get("price_usd"),
            "url": r.get("url"),
            "property_type": r.get("property_type"),
            "source_id": r.get("source_id"),
        })
    return sample


def _top_ranked(ranked: list[Listing], n: int = 10) -> list[dict]:
    return [
        {
            "rank": li.rank,
            "rank_score": round(li.rank_score, 1) if li.rank_score is not None else None,
            "title": (li.title or "")[:80],
            "price_usd": li.price_usd,
            "zone": li.zone,
            "url": li.url,
        }
        for li in ranked[:n]
    ]


def _write_outputs(
    write_dir: Path,
    raw: list[dict],
    normalized: list[Listing],
    failures: dict[str, int],
    ranked: list[Listing],
) -> None:
    write_dir.mkdir(parents=True, exist_ok=True)
    with (write_dir / "raw.jsonl").open("w", encoding="utf-8") as f:
        for r in raw:
            f.write(json.dumps(r, default=str) + "\n")
    with (write_dir / "normalized.jsonl").open("w", encoding="utf-8") as f:
        for li in normalized:
            f.write(json.dumps(li.to_dict(), default=str) + "\n")
    with (write_dir / "failures.jsonl").open("w", encoding="utf-8") as f:
        for reason, count in sorted(failures.items()):
            f.write(json.dumps({"reason": reason, "count": count}) + "\n")
    with (write_dir / "ranked.json").open("w", encoding="utf-8") as f:
        json.dump([li.to_dict() for li in ranked], f, indent=2, default=str)


def lab_run(
    slug: str,
    *,
    limit: int = 25,
    offline: bool = False,
    with_validate: bool = True,
    with_dedup: bool = True,
    with_rank: bool = True,
    write_dir: Optional[Path] = None,
) -> LabResult:
    """Run one scraper through fetch → normalize → validate → dedup → rank.

    No LLM, no photo download, no `web/data/` mutation, no PostHog.
    """
    started = time.monotonic()
    failures: dict[str, int] = {}

    try:
        raw = _fetch_raw(slug, limit, offline)
    except Exception as e:  # noqa: BLE001 — dev tool, surface error
        return LabResult(
            slug=slug,
            duration_s=time.monotonic() - started,
            ok=False,
            error=f"{e.__class__.__name__}: {e}\n{traceback.format_exc()[-600:]}",
        )

    normalized, dropped_in_normalize = _normalize_records(raw, slug)
    if dropped_in_normalize:
        failures["dropped_in_normalize"] = dropped_in_normalize

    validation_counts = {"pass": len(normalized), "flag": 0, "drop": 0}
    listings_after_validate = normalized
    if with_validate:
        listings_after_validate, validation_counts = _validate_records(
            normalized, failures
        )

    dedup_counts = {"kept": len(listings_after_validate), "duplicate": 0}
    listings_after_dedup = listings_after_validate
    if with_dedup:
        listings_after_dedup, dup_count = _dedup_records(listings_after_validate)
        dedup_counts = {"kept": len(listings_after_dedup), "duplicate": dup_count}

    ranked: list[Listing] = []
    if with_rank and listings_after_dedup:
        ranked = rank(listings_after_dedup)

    if write_dir is not None:
        _write_outputs(write_dir, raw, normalized, failures, ranked)

    return LabResult(
        slug=slug,
        duration_s=time.monotonic() - started,
        ok=True,
        raw_count=len(raw),
        normalized_count=len(normalized),
        validation=validation_counts,
        dedup=dedup_counts,
        ranked_count=len(ranked),
        failures=failures,
        top_ranked=_top_ranked(ranked),
        raw_sample=_raw_sample(raw),
        write_dir=str(write_dir) if write_dir is not None else None,
    )


def render_human_report(result: LabResult) -> str:
    """Per-PRD stdout shape. Returns one string for the caller to print."""
    lines = [
        f"source: {result.slug}",
    ]
    if not result.ok:
        lines.append("status: ERR")
        lines.append(f"duration: {result.duration_s:.1f}s")
        if result.error:
            first = result.error.splitlines()[0] if result.error else ""
            lines.append(f"error: {first}")
        return "\n".join(lines)
    lines.extend([
        f"fetched: {result.raw_count}",
        f"normalized: {result.normalized_count}",
        f"validated: pass={result.validation['pass']} "
        f"flag={result.validation['flag']} drop={result.validation['drop']}",
        f"dedup_kept: {result.dedup['kept']} "
        f"(duplicates dropped: {result.dedup['duplicate']})",
        f"ranked: {result.ranked_count}",
    ])
    if result.failures:
        lines.append("failures:")
        for reason, count in sorted(result.failures.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"  {reason}: {count}")
    if result.top_ranked:
        lines.append("top ranked:")
        for r in result.top_ranked[:5]:
            price = f"${r['price_usd']:,.0f}" if r.get('price_usd') else "$?"
            lines.append(
                f"  #{r['rank']:<2} {r['rank_score']:>5.1f}  "
                f"{price:<10}  {r.get('zone') or '?':<14} {r['title']}"
            )
    lines.append(f"duration: {result.duration_s:.1f}s")
    if result.write_dir:
        lines.append(f"wrote: {result.write_dir}")
    return "\n".join(lines)
