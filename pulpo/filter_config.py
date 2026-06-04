"""Filter strictness slider — PRD A2.

The visibility filter is a *slider*, not a wall. Three named levels live
here; one config flip (`PULPO_FILTER_STRICTNESS=...`) changes which
listings qualify for shelves without a code deploy.

Every level sits on top of an immutable floor. The
``automation/validation.py`` DROP gates (numeric price within bounds,
area within bounds, country exclusion, placeholder photo, days-listed
sanity) remain on top — they remove structurally broken listings
regardless of strictness. The slider only tunes *visibility* above
that floor, never the floor itself.

Level semantics:

- ``strict``   — type + zone + price + area + ≥1 photo
- ``moderate`` — type + zone + price (PRD default — "What is it? Where? How much?")
- ``lenient``  — type + price (no zone requirement; max recall above the floor)

Photo requirement only applies under ``strict``. The FE (HomeShelf.jsx,
PR A3) layers a shelf-aware photo waiver on top: when a shelf has < 10
strict-eligible listings, it tops up with loose-eligible (no photo) and
renders a "Foto aún no disponible" placeholder.

``exclude_agricultural`` stays True at every level — agricultural is a
category exclusion (separate inventory pool), not a quality filter.
``property_type`` stays required at every level — a listing without a
type cannot be assigned to any shelf subcategory.

Callers
-------
``pulpo/derived_rules.derive_is_incomplete`` re-exports
``derive_is_incomplete`` from here so existing imports keep working.
"""
from __future__ import annotations

import os
from typing import Any

from pulpo.derived_rules import _g


# IMMUTABLE FLOOR. Every level requires these; ``lenient`` cannot drop
# below. The audit emitter in automation/shelf_audit.py mirrors this
# constant — keep in sync until A2 unifies the two.
FLOOR_REQUIRED: tuple[str, ...] = ("price_usd", "url")


# Strictness level definitions. Each level enumerates which fields must
# be populated (``required``) and the minimum photo count
# (``min_photos``). ``exclude_agricultural`` is True at every level by
# design — agricultural exclusion is enforced by downstream consumers
# (web/app/data/use-listings.tsx, ig_photo_gate, HomeShelf) and is
# decoupled from this gate.
STRICTNESS_LEVELS: dict[str, dict[str, Any]] = {
    "strict": {
        "required": FLOOR_REQUIRED + ("property_type", "zone", "area_m2"),
        "min_photos": 1,
        "exclude_agricultural": True,
        "require_zone_confidence": "specific",
    },
    "moderate": {
        "required": FLOOR_REQUIRED + ("property_type", "zone"),
        "min_photos": 0,
        "exclude_agricultural": True,
        "require_zone_confidence": "municipality",
    },
    "lenient": {
        "required": FLOOR_REQUIRED + ("property_type",),
        "min_photos": 0,
        "exclude_agricultural": True,
        "require_zone_confidence": "department",
    },
}

DEFAULT_LEVEL = "moderate"


def active_level() -> str:
    """Return the live strictness level from PULPO_FILTER_STRICTNESS,
    falling back to ``moderate`` on absent or unknown values. Read once
    per call site (cheap; no caching) so a test that flips the env var
    sees the new value on the next call without an importlib.reload."""
    level = (os.environ.get("PULPO_FILTER_STRICTNESS") or "").strip().lower()
    if level not in STRICTNESS_LEVELS:
        return DEFAULT_LEVEL
    return level


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


def derive_is_incomplete_for_level(
    li: Any,
    level: str,
) -> tuple[bool, list[str]]:
    """True iff the listing fails the named strictness level. Returns a
    (flag, reasons) tuple so callers can log/audit which gate(s) failed.

    Priority chain for reasons: the listing reports EVERY field it's
    missing, not just the first. This is for diagnostic completeness;
    the audit module collapses to a single dominant blocker per row.

    Unknown level falls back to ``moderate``.
    """
    spec = STRICTNESS_LEVELS.get(level) or STRICTNESS_LEVELS[DEFAULT_LEVEL]
    reasons: list[str] = []
    for field in spec["required"]:
        if _missing(li, field):
            reasons.append(f"no_{field}")
    if spec["min_photos"] > 0 and _photos_count(li) < spec["min_photos"]:
        reasons.append("no_photos")
    return (len(reasons) > 0, reasons)


def derive_is_incomplete(li: Any) -> bool:
    """Live entry point — switches on the active level.

    Replaces ``pulpo.derived_rules.derive_is_incomplete``'s old rule
    (``price_usd is None OR area_m2 is None``). The old rule corresponds
    roughly to ``lenient`` (price required) PLUS area_m2 (which is
    ``strict``-only under the new scheme). PR A2's effect on the live
    pipeline is to RELAX the gate to moderate (PRD default): listings
    missing ONLY area become visible, recovering ~80-120 listings from
    the hidden cohort per the PRD's audit.
    """
    flag, _ = derive_is_incomplete_for_level(li, active_level())
    return flag


def derive_incomplete_reasons(li: Any) -> list[str]:
    """Public helper used by the shelf audit to break out per-reason
    counts. Returns the empty list when the listing passes the active
    level."""
    _, reasons = derive_is_incomplete_for_level(li, active_level())
    return reasons
