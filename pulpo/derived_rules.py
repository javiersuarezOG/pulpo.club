"""
PRD §FR-7 — derived field rule engine.

Pure functions over upstream fields. Runs as the last step before the
ranker so that:

- `readiness_score` reflects the latest NLP-extracted utility booleans.
- `investment_signal` sees the FR-3-derived `is_repriced`.
- `data_quality_score` counts only fields that have actually been
  populated by the time we get here.
- `source_label` rolls up the upstream booleans into display chips.

All four functions are pure: same inputs → same outputs, no I/O. They
read from a Listing dict (or any object with the same field names) so
they're equally usable in production (run.py) and in tests.

Phase note: a handful of the PRD's signals depend on fields that don't
populate yet — `price_vs_zone_pct` (Phase 3 zone median batch),
`source_type` (scraper-config rename), `beachfront_tier` (Phase 2
geometric). The functions here gracefully degrade: missing inputs are
treated as "rule doesn't apply" rather than raising.
"""
from __future__ import annotations
from typing import Any, Optional

# Fields counted in data_quality_score per PRD §FR-7.4. We pick the 22 fields
# from the existing model that are meaningfully Core. PRD's exact field list
# uses different names (PRD spec uses agent_*, source_platform, etc.) — when
# the schema rename pass lands, update this list to match.
SCOREABLE_FIELDS = (
    "title",
    "description",
    "url",
    "scraped_at",
    "country",
    "department",
    "zone",
    "area_m2",
    "price_usd",
    "price_per_m2",
    "property_type",
    "first_seen_at",
    "broker_name",
    "broker_phone",
    "broker_email",
    "is_in_development",
    "is_beachfront",
    "has_water",
    "has_power",
    "has_paved_access",
    "photos_count",
    "lat",   # populates in Phase 2
)
SCOREABLE_TOTAL = len(SCOREABLE_FIELDS)


def _g(li: Any, name: str) -> Any:
    """Get a field from either a dict or a dataclass-like object."""
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def _is_populated(value: Any) -> bool:
    """Match PRD §FR-7.4's notion of populated: not null, not empty, not False/0
    when those would be defaults masking real "absent" semantics. For
    boolean fields, only True counts as informative — False is the default."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, bool):
        return value is True
    if isinstance(value, (list, tuple, dict)):
        return len(value) > 0
    if isinstance(value, (int, float)):
        return value != 0
    return True


def compute_data_quality_score(li: Any) -> float:
    """Fraction of SCOREABLE_FIELDS that are populated, in [0, 1]."""
    n = sum(1 for f in SCOREABLE_FIELDS if _is_populated(_g(li, f)))
    return round(n / SCOREABLE_TOTAL, 3)


def compute_readiness_score(li: Any) -> Optional[int]:
    """has_water + has_power + has_paved_access. Range 0-3.

    Returns None if all three inputs are absent — there's no signal to give.
    PRD §FR-7.1 actually specifies has_water + has_power + (road_access_type
    == 'paved'); we use has_paved_access as the bool form pending the enum
    rename pass.
    """
    inputs = [_g(li, "has_water"), _g(li, "has_power"), _g(li, "has_paved_access")]
    if all(v is None for v in inputs):
        return None
    return sum(1 for v in inputs if v is True)


def compute_investment_signal(li: Any) -> Optional[str]:
    """Priority-ordered: deal > hot > stale > new > None.

    PRD §FR-7.2 full rule (active after #86 zone medians shipped):
      deal:  is_repriced AND price_vs_zone_pct ≤ -10
      hot:   days_listed ≤ 7 AND saves/views in top 20%   (skipped — no signal)
      stale: days_listed ≥ 90
      new:   days_listed ≤ 7 (fallback)

    Behavior change from the previously-degraded rule:

      | is_repriced | pct ≤ -10 | pct is None | OLD result | NEW result   |
      |-------------|-----------|-------------|------------|--------------|
      | True        | True      | False       | deal       | deal         |
      | True        | False     | False       | deal ⚠     | stale/new/None |
      | True        | n/a       | True        | deal       | deal (fallback) |
      | False       | n/a       | n/a         | per below  | per below     |

    Why the None fallback: ~32% of catalog sits in zone buckets below
    the MIN_LISTINGS_PER_ZONE (10) threshold so price_vs_zone_pct is
    None. Without the fallback, a heavily-repriced listing in a
    low-volume zone loses its "deal" tag despite an obvious motivated-
    seller signal. Strict path stays primary for well-bucketed listings.

    Note: `Price Drop` source_label chip (PRD §FR-7.3) fires
    independently on is_repriced=True, so the "is_repriced but
    price_vs_zone_pct above -10" state still surfaces visually via that
    chip — investment_signal just becomes more conservative about
    what it labels a "deal."
    """
    is_repriced = _g(li, "is_repriced")
    days_listed = _g(li, "days_listed")
    price_vs_zone_pct = _g(li, "price_vs_zone_pct")

    if is_repriced is True:
        if price_vs_zone_pct is None:
            return "deal"   # fallback for low-volume zones
        if isinstance(price_vs_zone_pct, (int, float)) and price_vs_zone_pct <= -10:
            return "deal"
        # else fall through — repriced but not deeply enough below median.

    # hot: skipped — no saves/views signal yet.

    if isinstance(days_listed, int):
        if days_listed >= 90:
            return "stale"
        if days_listed <= 7:
            return "new"
    return None


def compute_source_label(li: Any) -> list[str]:
    """Display chips per PRD §FR-7.3.

    Includes:
      Beachfront — is_beachfront True
      Off-Market — source_type == 'off_market' (no signal yet; placeholder)
      Price Drop — is_repriced True
      New        — days_listed ≤ 7
      Build-Ready— readiness_score == 3
      Hot        — investment_signal == 'hot' (Phase 3)
    """
    labels: list[str] = []
    if _g(li, "is_beachfront") is True:
        labels.append("Beachfront")
    if _g(li, "source_type") == "off_market":   # field doesn't exist yet
        labels.append("Off-Market")
    if _g(li, "is_repriced") is True:
        labels.append("Price Drop")
    days_listed = _g(li, "days_listed")
    if isinstance(days_listed, int) and days_listed <= 7:
        labels.append("New")
    if compute_readiness_score(li) == 3:
        labels.append("Build-Ready")
    if _g(li, "investment_signal") == "hot":
        labels.append("Hot")
    return labels


def apply_all(li: Any) -> dict[str, Any]:
    """Compute and set all four derived fields on the listing in-place.

    Order matters: investment_signal reads is_repriced; source_label reads
    readiness_score and investment_signal. So we compute in this order:
    readiness_score → investment_signal → source_label → data_quality_score.

    Returns a dict of the values written for logging/telemetry.
    """
    rs  = compute_readiness_score(li)
    sig = compute_investment_signal(li)
    _set(li, "readiness_score", rs)
    _set(li, "investment_signal", sig)
    _set(li, "source_label", compute_source_label(li))
    _set(li, "data_quality_score", compute_data_quality_score(li))
    return {
        "readiness_score":   rs,
        "investment_signal": sig,
        "source_label":      _g(li, "source_label"),
        "data_quality_score":_g(li, "data_quality_score"),
    }


# ─────────────────────────────────────────────────────────────────────
# PR-7 — UX-facing derives (source_type + previous_price).
# These are wired into automation/run.py *before* apply_all() so that
# downstream label/signal logic can read them once they're meaningful.
# ─────────────────────────────────────────────────────────────────────

# Sources that scrape from social/private channels rather than indexed
# real-estate sites. Listings from these surface as "off_market" — the
# UI gates direct contact behind the Pro paywall.
OFF_MARKET_SOURCES: frozenset[str] = frozenset({
    "whatsapp", "facebook", "private", "instagram",
})


def derive_source_type(li: Any) -> str:
    """Map listing.source slug to 'off_market' or 'on_market'.

    Off-market is the smaller, paywalled shelf. The list is whitelist-style
    (additive): unrecognized sources default to 'on_market' so a new
    indexed scraper doesn't accidentally land on the paywall side.
    """
    src = _g(li, "source")
    if isinstance(src, str) and src.lower() in OFF_MARKET_SOURCES:
        return "off_market"
    return "on_market"


def derive_previous_price(li: Any, prices_history: Optional[dict] = None) -> Optional[float]:
    """Most-recent prior price for a repriced listing.

    Reads from `prices_history.json`'s `{source}|{source_id}` key, which
    automation/run.py populates as a chronological list of `{ts, price_usd}`
    snapshots. We surface the LAST entry whose price differs from the
    current price — that's the price the buyer "saw" before today's drop.

    Returns None when:
      - is_repriced is not True (saves the lookup; nothing to display)
      - history is missing for this listing key (some scrapers reslug
        source_id over time and detach the history)
      - the only prior entry equals the current price (not actually a drop)

    Plan note: a regex fallback for "rebajado de $X a $Y" / "reduced from
    $X to $Y" in description was scoped but not implemented here — the
    history-based path covers all listings whose source_id is stable, which
    is every current scraper. Add the regex when we see a reslug.
    """
    if _g(li, "is_repriced") is not True:
        return None
    if not prices_history:
        return None
    src = _g(li, "source")
    sid = _g(li, "source_id")
    if not (isinstance(src, str) and isinstance(sid, str)):
        return None
    history = prices_history.get(f"{src}|{sid}")
    if not isinstance(history, list) or len(history) < 2:
        return None
    cur = _g(li, "price_usd")
    if not isinstance(cur, (int, float)):
        return None
    # Walk backwards; first entry whose price differs from current is the
    # "previous" price. Skip same-price echoes (redundant snapshots).
    for entry in reversed(history[:-1]):
        prev = entry.get("price_usd") if isinstance(entry, dict) else None
        if isinstance(prev, (int, float)) and float(prev) != float(cur):
            return float(prev)
    return None


# ─────────────────────────────────────────────────────────────────────
# PR-8 — NLP enum derives (beachfront_tier, land_type).
# Composed from per-field booleans populated by pulpo/nlp_extractor.py.
# Run AFTER the extractor in the pipeline (automation/run.py).
# ─────────────────────────────────────────────────────────────────────


def derive_beachfront_tier(li: Any) -> Optional[str]:
    """Collapse beach-proximity booleans into a 3-tier enum.

    Priority (most specific wins):
        is_on_beach=True       → "on_beach"
        is_walk_to_beach=True  → "walk_to_beach"
        is_beachfront=True     → "near_beach"   (existing broader signal)
        else                   → None

    The FE adapter falls back to `near_beach` when only `is_beachfront`
    is True and no specific tier is set, matching this same logic
    client-side. Backend-driven values take precedence on the FE.
    """
    if _g(li, "is_on_beach") is True:
        return "on_beach"
    if _g(li, "is_walk_to_beach") is True:
        return "walk_to_beach"
    if _g(li, "is_beachfront") is True:
        return "near_beach"
    return None


def derive_land_type(li: Any) -> Optional[str]:
    """Collapse land-use booleans into a 4-tier enum.

    Priority (each NLP signal is well-disambiguated, so the order is
    informational rather than exclusive):
        is_agricultural=True   → "agricultural"
        is_commercial=True     → "commercial"
        is_tourist=True        → "tourist"
        property_type='land'   → "residential"   (default for land)
        property_type='house'  → "residential"
        property_type='condo'  → "residential"
        else                   → None

    `is_agricultural` runs first because Salvadoran "finca cafetalera"
    descriptions sometimes also mention "ideal para hotel" (tourist
    secondary use); the agricultural classification is the *current*
    use, which is what the buyer is paying for.

    Risk note (per plan): is_commercial in Salvadoran broker copy
    overlaps with "precio comercial" (negotiable) — the keyword
    dictionary's negative patterns suppress the most common confusions.
    """
    if _g(li, "is_agricultural") is True:
        return "agricultural"
    if _g(li, "is_commercial") is True:
        return "commercial"
    if _g(li, "is_tourist") is True:
        return "tourist"
    pt = _g(li, "property_type")
    if pt in ("land", "house", "condo"):
        return "residential"
    return None
