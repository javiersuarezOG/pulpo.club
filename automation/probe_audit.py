"""Probe-based thoroughness audit — PR-S3a (module).

Answers the question "what listings exist in the wild that pulpo
doesn't have?" by fuzzy-matching external probes against ranked.json.
A "probe" is one externally-discovered candidate listing (e.g. a
result from a Google site-search, a broker sitemap entry, or a manual
seed). For each probe we either find a matching ranked listing, OR
classify the miss into one of the KNOWN_MISS_CLASSIFICATIONS buckets
so a human can decide whether to act on it.

Why this exists
---------------
Pulpo's existing telemetry (source_health_history.jsonl, scraper
coverage_logger, exhaustiveness schema from PR-S1) answers "did we
fetch what each configured source has?" — but says nothing about
sources we don't configure or listings the sources have that we
filtered out. The probe audit is the opposite-direction signal:
"what's in the wild that we don't carry?"

Pattern reference: events-discovery's probe-vs-database matcher
(``src/events_discovery/probes/match.py``). Adapted to pulpo's
listing schema (title + price + zone + source URL).

Design
------
Pure-function fuzzy matcher + classifier. No I/O. The caller is
responsible for loading probes (PR-S3b) and ranked.json, calling
``match_probes(probes, listings)``, persisting the result. This
file is the matcher + classifier core only.

Per CLAUDE.md producer-consumer rule (post-2026-06-02):
``KNOWN_MISS_CLASSIFICATIONS`` is a closed set. Consumers:
  * PR-S3b — loads probes, runs the matcher, writes
    web/data/probe_audit_history.jsonl
  * PR-S3c — weekly cron + Slack alert on match-rate drop
  * Operator dashboard tile (PR-S7 partial via #672)
"""
from __future__ import annotations

import dataclasses
import re
import typing as t
import urllib.parse


# ---------- Closed-set enums ----------

KNOWN_MISS_CLASSIFICATIONS: frozenset[str] = frozenset({
    "source_not_configured",      # the probe's source domain isn't in our scraper registry
    "source_configured_but_zero", # the source IS scraped but yielded zero listings recently
    "scraped_but_filtered",       # listing is in raw scrape output but dropped at validation
    "scraped_but_failed_validation",  # listing tried to enter but DLQ'd
    "deduped_into_other",         # listing matched another listing in dedup
    "present_but_stale",          # listing IS in ranked but existence_status=stale
    "unknown",                    # could not be classified
})
"""Closed set per CLAUDE.md producer-consumer rule (post-2026-06-02).
Contract test in tests/test_probe_audit.py."""

# Fuzzy-match thresholds. Tuned conservatively — false positives
# (probe declared "matched" when the listing is actually different)
# cost more than false negatives in this audit. Better to flag an
# unmatched probe and have a human eyeball than silently classify it
# as "we have this already."
PRICE_TOLERANCE_PCT = 0.10   # ±10% on price
AREA_TOLERANCE_PCT  = 0.15   # ±15% on area_m2 (less precise reporting)
TITLE_OVERLAP_MIN   = 0.50   # 50% token overlap on normalized titles


# ---------- Data model ----------

@dataclasses.dataclass(frozen=True)
class Probe:
    """One externally-discovered candidate listing. The minimum useful
    shape for fuzzy matching."""

    title: str
    price_usd: float | None      # None if unknown/non-numeric
    location: str | None         # municipality, zone, or freeform location text
    source_url: str              # the probe's own URL (for source-domain inference)
    probe_kind: str              # e.g. "google_index" | "broker_sitemap" | "seed_list"

    @classmethod
    def from_dict(cls, d: dict) -> "Probe":
        return cls(
            title=str(d.get("title", "")),
            price_usd=_try_float(d.get("price_usd")),
            location=d.get("location"),
            source_url=str(d.get("source_url", "")),
            probe_kind=str(d.get("probe_kind", "unknown")),
        )


@dataclasses.dataclass(frozen=True)
class MatchResult:
    """Pure-function output of ``match_probe``. Either ``matched_key``
    is set (we have this listing) OR ``miss_classification`` is set
    (we don't, and here's why)."""

    probe: Probe
    matched_key: str | None     # "source|source_id" of the matching listing, else None
    matched_score: float        # 0.0-1.0; > 0 only when matched_key is set
    miss_classification: str | None  # one of KNOWN_MISS_CLASSIFICATIONS when matched_key is None
    reason: str                 # human-readable summary

    def to_dict(self) -> dict:
        return {
            "probe": dataclasses.asdict(self.probe),
            "matched_key": self.matched_key,
            "matched_score": round(self.matched_score, 4),
            "miss_classification": self.miss_classification,
            "reason": self.reason,
        }


# ---------- Helpers ----------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _try_float(v: t.Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _normalize_text(s: str) -> str:
    """Lowercase, drop non-alphanumeric, collapse whitespace. Used for
    title overlap computation."""
    return " ".join(_TOKEN_RE.findall((s or "").lower()))


def _token_set(s: str) -> set[str]:
    """Tokenize a normalized string and drop trivial stop-tokens."""
    tokens = {t for t in _TOKEN_RE.findall((s or "").lower()) if len(t) >= 3}
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity. 0 for empty sets."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def _extract_source_domain(url: str) -> str | None:
    """Parse a probe URL and return the bare domain (lowercased, no
    www., no port). Returns None for malformed URLs."""
    if not url:
        return None
    try:
        parsed = urllib.parse.urlsplit(url)
    except Exception:
        return None
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _price_close(probe_price: float | None, listing_price: float | None) -> bool:
    """True iff prices are within PRICE_TOLERANCE_PCT of each other.
    When either is None, returns False — we can't match on price alone
    if we don't have it."""
    if probe_price is None or listing_price is None or listing_price <= 0:
        return False
    delta = abs(probe_price - listing_price) / listing_price
    return delta <= PRICE_TOLERANCE_PCT


def _score_match(probe: Probe, listing: dict) -> float:
    """Composite match score in [0, 1]. Combines title token-overlap,
    price closeness, and an optional location signal.

    Weights:
      * 0.55 — title token overlap (Jaccard ≥ TITLE_OVERLAP_MIN)
      * 0.30 — price within tolerance
      * 0.15 — location/zone substring match

    A pure score function — no I/O. Callers decide a match threshold.
    """
    score = 0.0

    # Title overlap (dominant signal).
    probe_tokens = _token_set(probe.title)
    listing_title = listing.get("title") or ""
    listing_tokens = _token_set(listing_title)
    overlap = _jaccard(probe_tokens, listing_tokens)
    if overlap >= TITLE_OVERLAP_MIN:
        score += 0.55 * overlap  # weight by the actual overlap

    # Price closeness.
    if _price_close(probe.price_usd, _try_float(listing.get("price_usd"))):
        score += 0.30

    # Location signal — probe location is a substring of listing's
    # zone or location_text, or vice versa.
    if probe.location:
        probe_loc = _normalize_text(probe.location)
        l_zone = _normalize_text(listing.get("zone") or "")
        l_loc = _normalize_text(listing.get("location_text") or "")
        if probe_loc and (probe_loc in l_zone or probe_loc in l_loc
                          or l_zone in probe_loc or l_loc in probe_loc):
            score += 0.15

    return min(score, 1.0)


# ---------- Matcher ----------

def match_probe(
    probe: Probe,
    listings: t.Sequence[dict],
    *,
    threshold: float = 0.55,
    configured_sources: t.AbstractSet[str] = frozenset(),
    sources_with_zero_yield: t.AbstractSet[str] = frozenset(),
    stale_keys: t.AbstractSet[str] = frozenset(),
) -> MatchResult:
    """Find the best-matching listing for one probe; classify if none
    matches.

    Args:
        probe: the probe to match.
        listings: candidate listings (typically ranked.json contents
            as dicts).
        threshold: minimum composite score to declare a match. Default
            0.55 — a 50% title overlap alone barely qualifies, but
            title-overlap + price-close usually clears.
        configured_sources: set of scraper slugs we run. Used to
            classify miss as ``source_not_configured`` when the
            probe's URL doesn't map to any of them.
        sources_with_zero_yield: subset of ``configured_sources`` that
            returned zero listings in the most recent nightly. Used
            for ``source_configured_but_zero``.
        stale_keys: set of "source|source_id" keys whose existence
            status is ``stale`` (from PR-S4 ledger). Used for
            ``present_but_stale``.

    Returns:
        A MatchResult. Caller checks ``matched_key`` (truthy =
        matched) vs ``miss_classification`` (non-None = unmatched).
    """
    # Compute scores against every listing; pick the best.
    best_score = 0.0
    best_listing: dict | None = None
    for li in listings:
        if not isinstance(li, dict):
            continue
        s = _score_match(probe, li)
        if s > best_score:
            best_score = s
            best_listing = li

    if best_listing is not None and best_score >= threshold:
        key = f"{best_listing.get('source', '?')}|{best_listing.get('source_id', '?')}"
        # Is this listing currently stale? If so, the probe DOES have
        # a match but it's a present-but-stale match — flag it.
        if key in stale_keys:
            return MatchResult(
                probe=probe,
                matched_key=None,
                matched_score=best_score,
                miss_classification="present_but_stale",
                reason=(
                    f"matched key={key} score={best_score:.2f} but ledger "
                    f"says stale (missing ≥3 nightlies)"
                ),
            )
        return MatchResult(
            probe=probe,
            matched_key=key,
            matched_score=best_score,
            miss_classification=None,
            reason=f"matched key={key} score={best_score:.2f}",
        )

    # No match above threshold → classify the miss.
    domain = _extract_source_domain(probe.source_url)
    # Domain → source-slug mapping is a heuristic. The configured_sources
    # set comes from the scraper registry; we look for a slug whose
    # health_probe_url's host contains/is contained in the probe's
    # domain. That's the caller's job (in PR-S3b) — here we just
    # accept the set as-is and check membership.
    if domain and domain not in configured_sources:
        return MatchResult(
            probe=probe,
            matched_key=None,
            matched_score=best_score,
            miss_classification="source_not_configured",
            reason=f"probe domain {domain!r} not in configured_sources",
        )
    if domain and domain in sources_with_zero_yield:
        return MatchResult(
            probe=probe,
            matched_key=None,
            matched_score=best_score,
            miss_classification="source_configured_but_zero",
            reason=f"probe domain {domain!r} configured but recent yield=0",
        )
    if best_listing is not None and best_score > 0:
        # We had a near-match but below threshold — most likely the
        # listing was scraped but the title/price drifted, OR it was
        # filtered/dropped at validation. We can't distinguish without
        # the validation log; default to scraped_but_filtered.
        return MatchResult(
            probe=probe,
            matched_key=None,
            matched_score=best_score,
            miss_classification="scraped_but_filtered",
            reason=(
                f"near-match score={best_score:.2f} below threshold "
                f"{threshold:.2f}; likely filtered/dropped"
            ),
        )
    return MatchResult(
        probe=probe,
        matched_key=None,
        matched_score=0.0,
        miss_classification="unknown",
        reason="no candidate matched and no domain signal",
    )


def match_probes(
    probes: t.Iterable[Probe],
    listings: t.Sequence[dict],
    **match_kwargs: t.Any,
) -> list[MatchResult]:
    """Run match_probe over a collection. Returns the list of results
    in input order."""
    return [match_probe(p, listings, **match_kwargs) for p in probes]


def summarize(results: t.Sequence[MatchResult]) -> dict:
    """Per-classification counts + overall match rate. The 30-second
    operator surface."""
    total = len(results)
    matched = sum(1 for r in results if r.matched_key is not None)
    by_class: dict[str, int] = {}
    for r in results:
        if r.miss_classification:
            by_class[r.miss_classification] = by_class.get(r.miss_classification, 0) + 1
    return {
        "total_probed": total,
        "matched": matched,
        "match_rate": round(matched / total, 4) if total else 0.0,
        "by_miss_classification": by_class,
    }
