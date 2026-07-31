"""The 7 content levers are well-formed AND stay in lockstep with the /go
attribution router's allow-list. If someone adds a lever here but not in
api/go/[code].js (or vice-versa), the router would 302 a real post's code
to the homepage-fallback — silent attribution loss. This contract test
(grep pattern, like email_type_contract) makes that drift a red build."""
from __future__ import annotations

import re
from pathlib import Path

from automation import ig_content_categories as cats

ROUTER = Path("api/go/[code].js")


def test_exactly_seven_levers():
    assert len(cats.SLUGS) == 7
    assert len(set(cats.SLUGS)) == 7  # no dupes


def test_every_lever_is_complete_and_on_a_valid_tier():
    for slug, c in cats.CATEGORIES.items():
        for field in cats.REQUIRED_FIELDS:
            assert c.get(field), f"{slug} missing {field}"
        assert c["default_tier"] in cats.VALID_TIERS, f"{slug} bad tier {c['default_tier']}"
        # ES/EN copy are distinct (bilingual, not a copy-paste)
        assert c["name_es"] != c["name_en"]


def test_slugs_are_router_safe_tokens():
    # api/go/[code].js's CODE_RE accepts [a-z_]+ for the category segment.
    for slug in cats.SLUGS:
        assert re.fullmatch(r"[a-z_]+", slug), f"{slug} not a valid /go code token"


def _router_allow_list() -> set[str]:
    src = ROUTER.read_text(encoding="utf-8")
    m = re.search(r"CONTENT_CATEGORIES\s*=\s*new Set\(\[(.*?)\]\)", src, re.S)
    assert m, "could not find CONTENT_CATEGORIES in the router"
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def test_registry_matches_router_allow_list_exactly():
    assert set(cats.SLUGS) == _router_allow_list()


def test_get_and_is_valid():
    assert cats.get("scarcity")["audience"] == "fence-sitters"
    assert cats.get("nope") is None
    assert cats.is_valid("investment") and not cats.is_valid("clickbait")
