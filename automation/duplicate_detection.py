"""
Cross-source duplicate detection — telemetry-only (no listings dropped).

Why this module exists
----------------------
Pulpo aggregates listings from 6 SV brokers; some inventory is cross-posted
(the same property appears under multiple brokers). We don't know how much.
This module measures it without changing any other pipeline behaviour, so
follow-up decisions ("is encuentra24 worth scraping? Are we paying for
duplicates in the rank?") get to start from a real number rather than a
guess.

Match algorithm (in order of precision)
---------------------------------------
1. **Phone match** (high precision). Two listings from DIFFERENT sources
   that share a normalised broker_phone are essentially certain to be
   the same property listed by the same agent on two sites. Catches the
   "agent cross-posts" case. Coverage: bienesraices + century21 (100%
   broker_phone today); other sources don't carry phone.
2. **Coord match** (medium precision). Two listings within ~100m of
   each other on lat/lng, from DIFFERENT sources, with prices in a
   ±25% band. Catches the "different brokers, same building" case
   plus geocode jitter. Coverage: all 6 sources have ~100% lat/lng.

The two passes overlap; the report counts both raw and union (`either`).

What this module does NOT do
----------------------------
- Drop listings. The ranker still sees the full list. Once we have a
  week of telemetry we can decide whether to soft-deduplicate (keep
  the highest-data-quality copy) or surface duplicates to the UI.
- Match within the same source. A single broker listing the same
  property twice is a different problem (their CMS, not our pipeline)
  and would muddy the cross-source signal.
- Title/description similarity. Postponed — phone + coord catch most
  duplicates, and fuzzy text match has higher false-positive risk
  without a clear payoff.
"""
from __future__ import annotations
import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


# ── Phone normalisation ────────────────────────────────────────────────


_NON_DIGITS = re.compile(r"\D")


def normalize_phone(phone: Any) -> str | None:
    """Reduce a phone string to digits-only canonical form.

    El Salvador phones come in many shapes — `+503 7851-3928`,
    `(503) 7851 3928`, `78513928`, `503-7851-3928`. After stripping
    every non-digit, valid SV mobiles end up as either an 8-digit
    local form (`78513928`) or an 11-digit international form
    (`50378513928`). When we get the international form, drop the
    leading `503` so phones from a scraper that emits the local form
    still match phones from one that emits the full form.

    Returns None for empty, non-string, or implausibly short inputs
    (anything < 7 digits — wouldn't be a real phone number anyway).
    """
    if phone is None:
        return None
    s = _NON_DIGITS.sub("", str(phone))
    if not s or len(s) < 7:
        return None
    # Strip SV country code if present so `+503 7851-3928` and
    # `78513928` both canonicalise to `78513928`.
    if len(s) == 11 and s.startswith("503"):
        s = s[3:]
    return s


# ── Geo distance ───────────────────────────────────────────────────────


_EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres. Mirrors automation/distance_fields
    but in m (vs km) since duplicate-detection thresholds are 100s of m,
    not km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ── Listing accessors ─────────────────────────────────────────────────


def _g(li: Any, name: str) -> Any:
    """Field accessor — works on both dataclass Listings and raw dicts.

    `automation/run.py` calls us with normalised Listing objects, but
    tests are easier to write with plain dicts; supporting both costs
    nothing and avoids a fixture conversion layer.
    """
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _key(li: Any) -> str:
    return f"{_g(li, 'source')}|{_g(li, 'source_id')}"


def _pair_key(s1: str, s2: str) -> str:
    """Canonical sorted source-pair name so `bienesraices+remax` and
    `remax+bienesraices` show up as the same bucket."""
    return "+".join(sorted([s1, s2]))


# ── Match passes ──────────────────────────────────────────────────────


COORD_RADIUS_M = 100.0       # ~3 decimals of lat/lng = ~111m grid
PRICE_TOLERANCE_PCT = 0.25   # ±25% — generous enough for currency drift,
                             # broker price-ladder differences, partial
                             # listing updates

# Coords shared by ≥ this many listings are treated as fallback "centroids"
# (a municipal/zone default the source falls back to when precise lat/lng
# isn't available) and are excluded from coord-pair matching. Pinned by a
# constant test so any change forces a deliberate decision.
#
# Threshold rationale (2026-05-08 audit):
#   The Phase 0 audit found 19/20 cross-source pairs were FPs from listings
#   sitting at shared default coords (top centroid: 49 listings on
#   (13.4833, -89.3167), the Santa Tecla default). 5+ listings exactly
#   colocated at 5-decimal precision is essentially never a real cluster
#   of distinct properties — it's a fallback. Threshold of 5 catches the
#   top-10 production centroids cleanly and accepts that we'll miss
#   genuine condo-tower duplicates (rare today; addressed by photo-URL
#   matching in Phase 1.2).
CENTROID_MIN_LISTINGS = 5

# Lat/lng rounding precision for centroid bucketing. 5 decimals ≈ 1 metre,
# so two listings at "the same coord" really do share an exact geocode
# rather than being two distinct points 50m apart that happened to round
# into the same bucket.
_CENTROID_ROUND_DECIMALS = 5


def _phone_pairs(listings: list[Any]) -> list[tuple[str, str, str]]:
    """Pairs of distinct-source listings sharing a normalised phone.

    Returns [(key1, key2, source_pair)]. Skips within-source matches
    (those are the broker's own CMS duplicate, not a cross-post).
    """
    by_phone: dict[str, list[Any]] = defaultdict(list)
    for li in listings:
        ph = normalize_phone(_g(li, "broker_phone"))
        if ph:
            by_phone[ph].append(li)

    out: list[tuple[str, str, str]] = []
    for group in by_phone.values():
        if len(group) < 2:
            continue
        for a, b in combinations(group, 2):
            sa, sb = _g(a, "source"), _g(b, "source")
            if sa == sb:
                continue
            out.append((_key(a), _key(b), _pair_key(sa, sb)))
    return out


def _compute_centroids(listings: list[Any]) -> set[tuple[float, float]]:
    """Identify coords shared by ≥ CENTROID_MIN_LISTINGS listings.

    These are scrapers' fallback geocodes (a municipal/zone centroid
    used when precise lat/lng isn't available), not genuine clusters
    of distinct properties. Returns the set of (rounded_lat, rounded_lng)
    tuples to exclude from coord matching.
    """
    counts: dict[tuple[float, float], int] = defaultdict(int)
    for li in listings:
        lat, lng = _g(li, "lat"), _g(li, "lng")
        if lat is None or lng is None:
            continue
        key = (
            round(float(lat), _CENTROID_ROUND_DECIMALS),
            round(float(lng), _CENTROID_ROUND_DECIMALS),
        )
        counts[key] += 1
    return {coord for coord, n in counts.items() if n >= CENTROID_MIN_LISTINGS}


def _coord_pairs(
    listings: list[Any],
    centroids: set[tuple[float, float]] | None = None,
) -> tuple[list[tuple[str, str, str]], int]:
    """Pairs of distinct-source listings within COORD_RADIUS_M and
    inside PRICE_TOLERANCE_PCT, with centroid coords excluded.

    Naive O(n²) cross-source pair scan. n ≈ 900 today → ~400k pairs,
    haversine ~10 FLOPs each → low milliseconds. We can move to a
    spatial index if the catalog crosses ~10k listings.

    Returns:
      (pairs, suppressed_by_centroid):
        pairs:                  list of (key1, key2, source_pair)
        suppressed_by_centroid: count of pairs that would have been
                                flagged but were excluded because at
                                least one endpoint sits at a centroid
                                coord (telemetry — proves Phase 1.1 is
                                actually doing something each nightly).
    """
    centroids = centroids or set()

    geo: list[tuple[Any, float, float, float | None,
                     tuple[float, float]]] = []
    for li in listings:
        lat, lng = _g(li, "lat"), _g(li, "lng")
        if lat is None or lng is None:
            continue
        latf, lngf = float(lat), float(lng)
        rounded = (
            round(latf, _CENTROID_ROUND_DECIMALS),
            round(lngf, _CENTROID_ROUND_DECIMALS),
        )
        geo.append((li, latf, lngf, _g(li, "price_usd"), rounded))

    out: list[tuple[str, str, str]] = []
    suppressed = 0
    for a, b in combinations(geo, 2):
        la, lat_a, lng_a, p_a, ra = a
        lb, lat_b, lng_b, p_b, rb = b
        sa, sb = _g(la, "source"), _g(lb, "source")
        if sa == sb:
            continue
        if haversine_m(lat_a, lng_a, lat_b, lng_b) > COORD_RADIUS_M:
            continue
        # Centroid suppression. If EITHER endpoint sits at a fallback
        # centroid coord, drop the pair. Aggressive on purpose — Phase 0
        # audit showed 95% of would-have-been-flags were FPs from this
        # pattern. We accept losing genuine condo-tower duplicates here
        # (rare; addressed by photo-URL matching in Phase 1.2).
        if ra in centroids or rb in centroids:
            suppressed += 1
            continue
        # Price band check — same coords with wildly different prices
        # is more likely a multi-unit building (single condo tower
        # carrying many listings) than a duplicate. Both prices must
        # be present for the band to gate.
        if p_a is not None and p_b is not None and p_a > 0 and p_b > 0:
            ratio = max(p_a, p_b) / min(p_a, p_b) - 1
            if ratio > PRICE_TOLERANCE_PCT:
                continue
        out.append((_key(la), _key(lb), _pair_key(sa, sb)))
    return out, suppressed


# ── Public API ────────────────────────────────────────────────────────


def detect_duplicates(
    listings: list[Any],
    *,
    history_path: Path | None = None,
) -> dict:
    """Compute cross-source duplicate metrics over a normalised listing
    catalogue. Telemetry only — no listing is mutated or dropped.

    Args:
        listings: Listing objects or dicts. Mixed is fine.
        history_path: Optional JSONL sidecar to append one telemetry row
            per call. None skips the write (used by tests). Write
            failure is non-fatal — never kills the pipeline.

    Returns:
      Metrics dict:
        total_listings:               int
        listings_with_phone:          int
        listings_with_coords:         int
        centroid_count:               int   # distinct fallback-coord buckets
        listings_at_centroids:        int   # listings whose coord is a centroid
        phone_pairs:                  int   # cross-source phone matches
        coord_pairs:                  int   # cross-source coord matches (post-suppression)
        coord_pairs_suppressed_centroid:
                                      int   # would-have-been-flags excluded by Phase 1.1
        union_pairs:                  int   # phone OR coord
        duplicate_listings_either:    int   # listings flagged in any pair
        unique_listings_estimate:     int   # total - duplicate_listings_either
        duplicate_pct:                float # (dups / total) × 100
        by_source_pair:               dict[str, int]
    """
    n = len(listings)
    listings_with_phone = sum(
        1 for li in listings if normalize_phone(_g(li, "broker_phone"))
    )
    listings_with_coords = sum(
        1 for li in listings
        if _g(li, "lat") is not None and _g(li, "lng") is not None
    )

    # Phase 1.1 — identify fallback centroid coords up front so coord
    # matching can suppress them. Same-pass count for telemetry.
    centroids = _compute_centroids(listings)
    listings_at_centroids = sum(
        1 for li in listings
        if _g(li, "lat") is not None and _g(li, "lng") is not None
        and (
            round(float(_g(li, "lat")), _CENTROID_ROUND_DECIMALS),
            round(float(_g(li, "lng")), _CENTROID_ROUND_DECIMALS),
        ) in centroids
    )

    phone_pairs = _phone_pairs(listings)
    coord_pairs, coord_pairs_suppressed_centroid = _coord_pairs(
        listings, centroids=centroids,
    )

    # Union for the "duplicate_listings_either" headline metric. Counts
    # a listing once even if it appears in multiple pairs.
    flagged_keys: set[str] = set()
    for k1, k2, _ in phone_pairs + coord_pairs:
        flagged_keys.add(k1)
        flagged_keys.add(k2)

    by_source_pair: dict[str, int] = defaultdict(int)
    for _, _, pair in phone_pairs + coord_pairs:
        by_source_pair[pair] += 1

    metrics = {
        "total_listings":               n,
        "listings_with_phone":          listings_with_phone,
        "listings_with_coords":         listings_with_coords,
        "centroid_count":               len(centroids),
        "listings_at_centroids":        listings_at_centroids,
        "phone_pairs":                  len(phone_pairs),
        "coord_pairs":                  len(coord_pairs),
        "coord_pairs_suppressed_centroid": coord_pairs_suppressed_centroid,
        "union_pairs":                  len(set(
            (k1, k2) for k1, k2, _ in phone_pairs + coord_pairs
        )),
        "duplicate_listings_either":    len(flagged_keys),
        "unique_listings_estimate":     n - len(flagged_keys),
        "duplicate_pct":                round(
            len(flagged_keys) / n * 100, 2
        ) if n else 0.0,
        "by_source_pair":               dict(by_source_pair),
    }

    # Sidecar telemetry — append-only JSONL.
    if history_path is not None:
        try:
            history_path.parent.mkdir(parents=True, exist_ok=True)
            row = {
                "ts": datetime.now(timezone.utc).isoformat(),
                **{k: v for k, v in metrics.items() if k != "by_source_pair"},
                "by_source_pair": metrics["by_source_pair"],
            }
            with history_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception as e:
            # Non-fatal: telemetry failure must never kill the pipeline.
            print(f"[duplicate_detection] history write failed: {e!r}")

    return metrics
