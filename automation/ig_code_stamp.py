"""ig_code_stamp.py — stamp a queue item with its attribution code + lever.

Makes attribution live: each post carries a content_lever (one of the 7),
an intended_tier (free/pro), and an attribution_code of the exact shape the
/go router parses — ig-d<day>-<lever>[-pro]. The bio-hub (/ig) renders each
active post's /go/<code> link; a click stamps the lever + tier as UTMs and
the signup traces back here.

The code grammar MUST match api/go/[code].js exactly (CODE_RE + the peeled
tier suffix). test_ig_code_stamp round-trips make_code() through a mirror of
that grammar so the two can never drift — a stamped code the router would
reject is a red build.

Lever ASSIGNMENT (which lever a given post gets) is the Creative Director's
job (Phase 2 rotation); this module only mints the code once a lever is
chosen and writes the fields onto the item. Idempotent.
"""
from __future__ import annotations

from typing import Optional

from automation import ig_content_categories as cats

VALID_TIERS = ("free", "pro")


def make_code(day: int, lever: str, tier: str = "free") -> str:
    """ig-d<day>-<lever>[-pro] — the exact string /go parses. Raises on
    anything the router would reject, so we never mint a dead code."""
    if not isinstance(day, int) or not (0 <= day <= 9999):
        raise ValueError(f"day must be 0-9999 (router accepts \\d{{1,4}}), got {day!r}")
    if lever not in cats.CATEGORIES:
        raise ValueError(f"unknown lever {lever!r}; valid: {cats.SLUGS}")
    if tier not in VALID_TIERS:
        raise ValueError(f"tier must be one of {VALID_TIERS}, got {tier!r}")
    code = f"ig-d{day}-{lever}"
    return code if tier == "free" else f"{code}-{tier}"


def stamp(item: dict, lever: str, tier: Optional[str] = None) -> dict:
    """Write content_lever / intended_tier / attribution_code onto a queue
    item (mutates + returns it). tier defaults to the lever's registry
    default. Idempotent: re-stamping overwrites with the current values."""
    lever_def = cats.get(lever)
    if lever_def is None:
        raise ValueError(f"unknown lever {lever!r}; valid: {cats.SLUGS}")
    tier = tier or lever_def["default_tier"]
    day = item.get("day")
    if not isinstance(day, int):
        raise ValueError(f"item has no integer 'day' to key the code on: {day!r}")
    item["content_lever"] = lever
    item["intended_tier"] = tier
    item["attribution_code"] = make_code(day, lever, tier)
    return item
