"""Per-shelf eligibility audit — emits web/data/shelf_audit.json each nightly.

Read-only telemetry that mirrors the FE shelf-eligibility predicate in
``web/app/home/HomeShelf.jsx::isShelfEligible`` while ALSO computing what the
shelf would look like under three named strictness levels (strict / moderate /
lenient). The PRD's "Inventory Expansion & Listing Quality Filter" requires
shelf-aware visibility decisions; this audit is the diagnostic surface
operators use to pick an informed strictness level via PULPO_FILTER_STRICTNESS
(introduced in PR A2).

The audit DOES NOT change which listings are visible — it only reports what
would happen at each level against today's `is_incomplete` rule (price OR area
missing). Once A2 lands, the per-level counts swap to reading
`pulpo.filter_config.derive_is_incomplete_for_level` instead of the local
predicates here.

Schema (top-level keys):

    {
      "computed_at": "<ISO>",
      "active_level": "moderate",           # current PULPO_FILTER_STRICTNESS
      "total_in_dataset": 962,
      "aggregate": {
        "eligible_strict":   <int>,
        "eligible_moderate": <int>,
        "eligible_lenient":  <int>,
        "hidden_by_no_type":      <int>,
        "hidden_by_no_zone":      <int>,
        "hidden_by_no_price":     <int>,
        "hidden_by_no_area":      <int>,
        "hidden_by_no_photos":    <int>,
        "hidden_by_is_agricultural": <int>
      },
      "shelves": {
        "beach_homes":   {<per-shelf-block>},
        "beach_condos":  {<per-shelf-block>},
        "beach_land":    {<per-shelf-block>},
        "lake_homes":    {<per-shelf-block>},
        "lake_condos":   {<per-shelf-block>},
        "lake_land":     {<per-shelf-block>}
      }
    }

Per-shelf block::

    {
      "total_in_cohort":      <int>,
      "eligible_strict":      <int>,        # has type+zone+price+area+>=1 photo
      "eligible_moderate":    <int>,        # has type+zone+price (PRD default)
      "eligible_lenient":     <int>,        # has type+price
      "hidden_by_no_type":    <int>,        # mutually exclusive accounting
      "hidden_by_no_zone":    <int>,
      "hidden_by_no_price":   <int>,
      "hidden_by_no_area":    <int>,        # only material under strict
      "hidden_by_no_photos":  <int>,
      "hidden_by_is_agricultural": <int>
    }

The mutually-exclusive accounting walks the gates in priority order (type →
zone → price → area → photos → agricultural). A listing missing both type
and zone is only counted under `hidden_by_no_type`. This lets the operator
read one column and see the dominant blocker without double-counting.
"""
from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from typing import Any, Iterable

from automation._atomic import atomic_write_json
from pulpo.derived_rules import _g
from pulpo.filter_config import STRICTNESS_LEVELS as LEVELS


SHELF_KEYS: tuple[str, ...] = (
    "beach_homes",
    "beach_condos",
    "beach_land",
    "lake_homes",
    "lake_condos",
    "lake_land",
)


def _shelf_key(li: Any) -> str | None:
    """Map listing → one of SHELF_KEYS based on master_category × subcategory.

    Returns None for listings not assignable to a homepage shelf (interior
    inventory, agricultural, etc.). These still count toward
    ``total_in_dataset`` but never increment per-shelf cohorts.
    """
    mc = _g(li, "master_category")
    sub = _g(li, "subcategory")
    if mc not in ("beach", "lake"):
        return None
    if sub == "homes":
        return f"{mc}_homes"
    if sub == "condos":
        return f"{mc}_condos"
    if sub == "land":
        return f"{mc}_land"
    return None


def _missing(li: Any, field: str) -> bool:
    v = _g(li, field)
    if v is None:
        return True
    if isinstance(v, str) and v.strip() == "":
        return True
    return False


def _photos_count(li: Any) -> int:
    n = _g(li, "photos_count")
    if isinstance(n, int):
        return n
    photos = _g(li, "photos")
    if isinstance(photos, list):
        return len(photos)
    photo_urls = _g(li, "photo_urls")
    if isinstance(photo_urls, list):
        return len(photo_urls)
    return 0


def _passes_level(li: Any, level_spec: dict[str, Any]) -> bool:
    """True iff listing passes the named strictness level.

    Each level requires every field in `required` plus min_photos photos.
    Agricultural exclusion is enforced separately by the consumer (FE
    use-listings, ig_photo_gate, HomeShelf) — this audit measures eligibility
    of the underlying data, not the post-exclusion shelf composition.
    """
    for field in level_spec["required"]:
        if _missing(li, field):
            return False
    if level_spec["min_photos"] > 0 and _photos_count(li) < level_spec["min_photos"]:
        return False
    return True


def _primary_blocker(li: Any) -> str | None:
    """Walks gates in priority order, returns the first one this listing
    fails. Used for mutually-exclusive accounting so the audit reports a
    single dominant blocker per hidden listing.

    Priority: type → zone → price → area → photos → agricultural.
    """
    if _missing(li, "property_type"):
        return "no_type"
    if _missing(li, "zone"):
        return "no_zone"
    if _missing(li, "price_usd"):
        return "no_price"
    if _missing(li, "area_m2"):
        return "no_area"
    if _photos_count(li) < 1:
        return "no_photos"
    if _g(li, "is_agricultural") is True:
        return "is_agricultural"
    return None


def compute_audit(
    listings: Iterable[Any],
    *,
    active_level: str = "moderate",
) -> dict[str, Any]:
    """Pure compute — no I/O. Same shape as the JSON written by
    ``write_audit``. Used directly in tests."""
    by_shelf: dict[str, dict[str, int]] = {
        key: {
            "total_in_cohort": 0,
            "eligible_strict": 0,
            "eligible_moderate": 0,
            "eligible_lenient": 0,
            "hidden_by_no_type": 0,
            "hidden_by_no_zone": 0,
            "hidden_by_no_price": 0,
            "hidden_by_no_area": 0,
            "hidden_by_no_photos": 0,
            "hidden_by_is_agricultural": 0,
        }
        for key in SHELF_KEYS
    }
    aggregate = {
        "eligible_strict": 0,
        "eligible_moderate": 0,
        "eligible_lenient": 0,
        "hidden_by_no_type": 0,
        "hidden_by_no_zone": 0,
        "hidden_by_no_price": 0,
        "hidden_by_no_area": 0,
        "hidden_by_no_photos": 0,
        "hidden_by_is_agricultural": 0,
    }
    total_in_dataset = 0

    for li in listings:
        total_in_dataset += 1
        shelf = _shelf_key(li)

        passes_strict   = _passes_level(li, LEVELS["strict"])
        passes_moderate = _passes_level(li, LEVELS["moderate"])
        passes_lenient  = _passes_level(li, LEVELS["lenient"])

        if passes_strict:
            aggregate["eligible_strict"] += 1
        if passes_moderate:
            aggregate["eligible_moderate"] += 1
        if passes_lenient:
            aggregate["eligible_lenient"] += 1

        blocker = _primary_blocker(li)
        if blocker is not None:
            aggregate[f"hidden_by_{blocker}"] += 1

        if shelf is not None:
            block = by_shelf[shelf]
            block["total_in_cohort"] += 1
            if passes_strict:
                block["eligible_strict"] += 1
            if passes_moderate:
                block["eligible_moderate"] += 1
            if passes_lenient:
                block["eligible_lenient"] += 1
            if blocker is not None:
                block[f"hidden_by_{blocker}"] += 1

    return {
        "computed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "active_level": active_level,
        "total_in_dataset": total_in_dataset,
        "aggregate": aggregate,
        "shelves": by_shelf,
    }


def write_audit(
    listings: Iterable[Any],
    web_data_dir: Path,
    *,
    active_level: str | None = None,
) -> dict[str, Any]:
    """Compute audit and write to ``<web_data_dir>/shelf_audit.json``.

    Returns the audit dict so callers can log a summary line.
    """
    level = active_level or os.environ.get("PULPO_FILTER_STRICTNESS", "moderate")
    if level not in LEVELS:
        level = "moderate"
    audit = compute_audit(listings, active_level=level)
    out_path = Path(web_data_dir) / "shelf_audit.json"
    atomic_write_json(out_path, audit, indent=2, sort_keys=True, trailing_newline=True)
    return audit
