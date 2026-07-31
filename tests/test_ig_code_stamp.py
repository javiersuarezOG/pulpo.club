"""Code-stamping mints codes the /go router accepts, and stamps queue items
idempotently. The round-trip guard mirrors api/go/[code].js's grammar so a
Python-minted code the JS router would reject fails the build here."""
from __future__ import annotations

import re

import pytest

from automation import ig_code_stamp as stamp
from automation import ig_content_categories as cats

# EXACT mirror of api/go/[code].js: peel an optional -free/-pro, then match
# ig-d<day>-<lever>, then require the lever ∈ the allow-list.
_TIERS = ("free", "pro")
_CODE_RE = re.compile(r"^ig-d(\d{1,4})-([a-z_]+)$")


def _router_parse(code: str):
    """Faithful port of the router's parseCode → (day, lever, tier) | None."""
    tier, rest = "free", code
    for t in _TIERS:
        if code.endswith(f"-{t}"):
            tier, rest = t, code[: -(len(t) + 1)]
            break
    m = _CODE_RE.match(rest)
    if not m:
        return None
    lever = m.group(2)
    if lever not in cats.CATEGORIES:
        return None
    return int(m.group(1)), lever, tier


@pytest.mark.parametrize("lever", cats.SLUGS)
@pytest.mark.parametrize("tier", ["free", "pro"])
@pytest.mark.parametrize("day", [1, 5, 214, 9999])
def test_minted_codes_round_trip_through_the_router_grammar(lever, tier, day):
    code = stamp.make_code(day, lever, tier)
    parsed = _router_parse(code)
    assert parsed == (day, lever, tier), f"{code} → {parsed}"


def test_make_code_rejects_router_incompatible_input():
    with pytest.raises(ValueError):
        stamp.make_code(10000, "scarcity")      # 5 digits — router is \d{1,4}
    with pytest.raises(ValueError):
        stamp.make_code(5, "clickbait")          # lever not in allow-list
    with pytest.raises(ValueError):
        stamp.make_code(5, "scarcity", "gold")   # bad tier


def test_stamp_writes_all_three_fields_with_tier_default():
    item = {"day": 220, "caption": "…"}
    stamp.stamp(item, "investment")               # investment default_tier = pro
    assert item["content_lever"] == "investment"
    assert item["intended_tier"] == "pro"
    assert item["attribution_code"] == "ig-d220-investment-pro"


def test_stamp_tier_override_and_idempotency():
    item = {"day": 7}
    stamp.stamp(item, "aspiration", tier="free")
    assert item["attribution_code"] == "ig-d7-aspiration"
    # re-stamp with a different lever overwrites cleanly (no stale fields)
    stamp.stamp(item, "authority")
    assert item["content_lever"] == "authority"
    assert item["attribution_code"] == "ig-d7-authority-pro"


def test_stamp_requires_an_integer_day():
    with pytest.raises(ValueError):
        stamp.stamp({"caption": "no day"}, "scarcity")
