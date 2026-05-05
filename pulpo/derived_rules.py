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

    PRD §FR-7.2 has full rule:
      deal: is_repriced AND price_vs_zone_pct ≤ -10
      hot:  days_listed ≤ 7 AND saves/views in top 20%
      stale: days_listed ≥ 90
      new:  days_listed ≤ 7 (fallback)

    Phase 1 minimum we can compute today (no price_vs_zone_pct, no
    saves/views): just stale/new from days_listed, plus a degraded-deal
    that fires on is_repriced alone.
    """
    is_repriced = _g(li, "is_repriced")
    days_listed = _g(li, "days_listed")

    if is_repriced is True:
        return "deal"   # degraded — full rule needs price_vs_zone_pct (Phase 3)
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
