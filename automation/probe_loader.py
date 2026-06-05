"""Probe loader + source-domain resolver — PR-S3b.

Bridges between PR-S3a's pure-function matcher (which only knows
about Probe objects + listings) and the production data layer:

  * Load probes from a JSON/YAML seed config
  * Resolve each scraper's ``health_probe_url`` domain → scraper slug
    so the matcher's ``configured_sources`` parameter is correctly
    populated from the registry
  * Identify "zero-yield" sources by reading the latest
    source_health_history rows

Per CLAUDE.md producer-consumer rule (post-2026-06-02): every
component here has a named consumer (the runner in
scripts/run_probe_audit.py + tests).
"""
from __future__ import annotations

import json
import typing as t
import urllib.parse
from pathlib import Path

from automation.probe_audit import Probe


# ---------- Probe loading ----------

def load_probes_from_file(path: Path) -> list[Probe]:
    """Load probes from a JSON file. Expected shape:

        [
          {"title": "...", "price_usd": 240000, "location": "El Tunco",
           "source_url": "https://x.com/listing/123",
           "probe_kind": "seed_list"},
          ...
        ]

    Tolerant: malformed rows are skipped (not raised); empty/missing
    files return [].
    """
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(raw, list):
        return []
    out: list[Probe] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            out.append(Probe.from_dict(row))
        except (KeyError, TypeError, ValueError):
            continue
    return out


# ---------- Source-domain resolution ----------

def _strip_www(host: str) -> str:
    host = host.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _extract_host(url: str) -> str | None:
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return None
    host = parsed.hostname or ""
    if not host:
        return None
    return _strip_www(host)


def build_domain_to_slug(
    scraper_metadata: t.Mapping[str, dict],
) -> dict[str, str]:
    """Build a {domain: scraper_slug} index from SCRAPER_METADATA.

    Each scraper's ``health_probe_url`` host is normalized (lowercased,
    www-stripped). Scrapers without a probe URL are skipped.

    Note: a single scraper may control multiple domains (e.g. citymax
    franchise → citymax-sv.com AND citymax-sc.com). Today's metadata
    has one URL per scraper; extending to multiple is a follow-up
    schema change (list[str] of probe URLs).
    """
    index: dict[str, str] = {}
    for slug, meta in scraper_metadata.items():
        url = meta.get("health_probe_url")
        if not url:
            continue
        host = _extract_host(str(url))
        if host:
            index[host] = slug
    return index


def configured_source_domains(
    scraper_metadata: t.Mapping[str, dict],
) -> set[str]:
    """Return the set of domains the matcher should treat as
    ``configured_sources``. Just the keys of the domain index."""
    return set(build_domain_to_slug(scraper_metadata).keys())


# ---------- Zero-yield detection ----------

def zero_yield_domains(
    source_health_history_path: Path,
    *,
    scraper_metadata: t.Mapping[str, dict],
    window_runs: int = 1,
) -> set[str]:
    """Return the set of domains whose scrapers returned 0 listings in
    the most-recent ``window_runs`` nightly entries.

    Reads source_health_history.jsonl, groups by source slug, takes the
    most-recent N entries per slug, and flags slugs whose entire window
    yielded ``count <= 0``. Then maps slug → domain via the registry.

    Tolerant of malformed rows / missing files (returns empty set).
    """
    if not source_health_history_path.exists():
        return set()
    rows_by_slug: dict[str, list[dict]] = {}
    try:
        for line in source_health_history_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            slug = row.get("source")
            if not slug:
                continue
            rows_by_slug.setdefault(str(slug), []).append(row)
    except OSError:
        return set()

    zero_yield_slugs: set[str] = set()
    for slug, rows in rows_by_slug.items():
        # Sort by ts ascending; take the most recent N.
        rows.sort(key=lambda r: str(r.get("ts", "")))
        recent = rows[-window_runs:]
        if not recent:
            continue
        if all(int(r.get("count") or 0) <= 0 for r in recent):
            zero_yield_slugs.add(slug)

    # Map slug → domain.
    slug_to_domain: dict[str, str] = {
        slug: _extract_host(str(meta.get("health_probe_url") or "")) or ""
        for slug, meta in scraper_metadata.items()
    }
    return {
        slug_to_domain[slug]
        for slug in zero_yield_slugs
        if slug_to_domain.get(slug)
    }


# ---------- Stale-key reader (PR-S4 ledger integration) ----------

def stale_keys_from_ledger(ledger_path: Path) -> set[str]:
    """Read PR-S4's ledger and return the set of stale keys. Pure
    delegation to automation.listing_ledger.load_ledger +
    listing_ledger.stale_keys; centralized here so callers don't have
    to import both modules just to wire the matcher."""
    try:
        from automation.listing_ledger import load_ledger, stale_keys
    except ImportError:
        return set()
    ledger = load_ledger(ledger_path)
    return stale_keys(ledger)


# ---------- Composite "build matcher inputs" helper ----------

def build_matcher_inputs(
    *,
    scraper_metadata: t.Mapping[str, dict],
    source_health_history_path: Path,
    ledger_path: Path,
) -> dict[str, t.Any]:
    """One-shot builder that assembles every match_probe() kwarg from
    the production data layer. The runner script just calls this +
    match_probes.
    """
    return {
        "configured_sources": configured_source_domains(scraper_metadata),
        "sources_with_zero_yield": zero_yield_domains(
            source_health_history_path,
            scraper_metadata=scraper_metadata,
        ),
        "stale_keys": stale_keys_from_ledger(ledger_path),
    }
