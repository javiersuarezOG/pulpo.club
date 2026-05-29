"""Favorites backend — diff logic + render contract.

Coverage:

  • _normalize_saves in subscribers.py: legacy bare-ID strings + new
    enriched objects + malformed entries collapse into a uniform
    `list[dict]` with `{id, saved_at?, price_at_save_usd?, source?}`.
  • compute_favorites in favorites.py: classification into one of
    `price_dropped / no_change / off_market / price_up`, priority
    ordering, MAX_FAVORITES cap, noise floor on small price moves,
    truthful fallback when baselines are missing.
  • Renderer behavior: empty favorites → section skipped; non-empty
    → cards in the expected order, price-drop chip with the delta,
    off-market chip + "Last seen at $X", no italics.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from automation.newsletter import build_issue, render_html
from automation.newsletter.favorites import (
    MAX_FAVORITES,
    PRICE_NOISE_FLOOR_USD,
    build_ranked_index,
    compute_favorites,
)
from automation.newsletter.subscribers import _normalize_saves
from automation.newsletter.types import SavedListing


ISSUE_DATE = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)


def _save(**kw):
    """Minimal SavedListing builder."""
    return SavedListing(**{"id": "remax__001", **kw})


def _listing(**kw):
    """Minimal ranked.json-shape dict."""
    return {
        "source": "remax",
        "source_id": "001",
        "title": "Ocean View Lot",
        "title_canonical": {"en": "Ocean View Lot", "es": "Lote con Vista al Mar"},
        "price_usd": 60_000,
        "days_listed": 12,
        "department": "La Libertad",
        "municipality": "Tamanique",
        **kw,
    }


# ── subscribers._normalize_saves ────────────────────────────────────


def test_normalize_legacy_bare_ids_become_id_only_dicts():
    raw = ["a__1", "b__2"]
    out = _normalize_saves(raw)
    assert out == [{"id": "a__1"}, {"id": "b__2"}]


def test_normalize_enriched_entries_preserve_optional_fields():
    raw = [{
        "id": "a__1",
        "saved_at": "2026-05-29T12:00:00Z",
        "price_at_save_usd": 60000.0,
        "source": "remax",
    }]
    out = _normalize_saves(raw)
    assert out[0]["id"] == "a__1"
    assert out[0]["price_at_save_usd"] == 60000.0
    assert out[0]["saved_at"] == "2026-05-29T12:00:00Z"
    assert out[0]["source"] == "remax"


def test_normalize_drops_malformed_entries_silently():
    """A malformed entry must not block the rest of the list."""
    raw = [
        "ok__1",
        None,
        42,
        {"no_id_key": True},
        {"id": ""},
        {"id": "ok__2", "price_at_save_usd": -5},  # negative price discarded
    ]
    out = _normalize_saves(raw)
    ids = [e["id"] for e in out]
    assert ids == ["ok__1", "ok__2"]
    # negative price didn't carry through
    assert "price_at_save_usd" not in out[1]


def test_normalize_non_list_returns_empty():
    assert _normalize_saves(None) == []
    assert _normalize_saves("string instead of list") == []
    assert _normalize_saves({"obj": "instead of list"}) == []


# ── compute_favorites: state classification ─────────────────────────


def test_compute_empty_saves_returns_empty():
    """No saves → empty list → renderer skips the section."""
    result = compute_favorites(saves=[], ranked_index={})
    assert result == []


def test_price_dropped_state_when_current_is_lower():
    saves = [_save(price_at_save_usd=60_000)]
    index = build_ranked_index([_listing(price_usd=55_000)])
    result = compute_favorites(saves=saves, ranked_index=index)
    assert len(result) == 1
    upd = result[0]
    assert upd.state == "price_dropped"
    assert upd.delta_usd == 5_000.0
    assert upd.current_price_usd == 55_000.0
    assert upd.price_at_save_usd == 60_000.0


def test_price_up_state_when_current_is_higher():
    """Rare but truthful — surfaced not buried."""
    saves = [_save(price_at_save_usd=55_000)]
    index = build_ranked_index([_listing(price_usd=60_000)])
    result = compute_favorites(saves=saves, ranked_index=index)
    assert len(result) == 1
    assert result[0].state == "price_up"
    assert result[0].delta_usd == 5_000.0


def test_off_market_when_not_in_ranked_index():
    saves = [_save(price_at_save_usd=60_000)]
    result = compute_favorites(saves=saves, ranked_index={})
    assert len(result) == 1
    assert result[0].state == "off_market"
    assert result[0].price_at_save_usd == 60_000.0


def test_off_market_with_no_baseline_is_skipped():
    """A legacy save with no price_at_save_usd that's also gone from
    ranked.json has no content to render — skip rather than emit a
    half-empty card."""
    saves = [_save()]  # no price baseline
    result = compute_favorites(saves=saves, ranked_index={})
    assert result == []


def test_no_change_when_price_match():
    saves = [_save(price_at_save_usd=60_000)]
    index = build_ranked_index([_listing(price_usd=60_000)])
    result = compute_favorites(saves=saves, ranked_index=index)
    assert len(result) == 1
    assert result[0].state == "no_change"
    assert result[0].days_listed == 12


def test_legacy_save_without_baseline_renders_as_no_change():
    """Pre-favorites-backend saves (bare IDs) have no price_at_save_usd.
    We still surface them as no_change rather than dropping them —
    the user expects to see their saved listings in the section."""
    saves = [_save()]  # no baseline
    index = build_ranked_index([_listing()])
    result = compute_favorites(saves=saves, ranked_index=index)
    assert len(result) == 1
    assert result[0].state == "no_change"
    assert result[0].days_listed == 12


def test_noise_floor_treats_tiny_drops_as_no_change():
    """A $200 price move is rounding noise, not a seller's decision."""
    saves = [_save(price_at_save_usd=60_000)]
    index = build_ranked_index([_listing(price_usd=60_000 - PRICE_NOISE_FLOOR_USD + 100)])
    result = compute_favorites(saves=saves, ranked_index=index)
    assert result[0].state == "no_change"


# ── compute_favorites: ordering + cap ───────────────────────────────


def test_state_priority_orders_drops_first():
    saves = [
        SavedListing(id="a__no_change", price_at_save_usd=60_000),
        SavedListing(id="b__off_market", price_at_save_usd=60_000),
        SavedListing(id="c__price_drop", price_at_save_usd=60_000),
    ]
    index = build_ranked_index([
        {"source": "a", "source_id": "no_change", "price_usd": 60_000,
         "title_canonical": {"en": "A"}, "days_listed": 5},
        # b is missing — triggers off_market
        {"source": "c", "source_id": "price_drop", "price_usd": 55_000,
         "title_canonical": {"en": "C"}, "days_listed": 5},
    ])
    result = compute_favorites(saves=saves, ranked_index=index)
    assert [u.state for u in result] == ["price_dropped", "off_market", "no_change"]


def test_max_favorites_caps_the_list():
    saves = []
    listings = []
    for i in range(MAX_FAVORITES + 3):
        sid = f"x__{i}"
        saves.append(SavedListing(id=sid, price_at_save_usd=60_000))
        # All become "no_change" to ensure ordering doesn't drop them
        listings.append({"source": "x", "source_id": str(i), "price_usd": 60_000,
                         "title_canonical": {"en": f"X{i}"}, "days_listed": 5})
    result = compute_favorites(saves=saves, ranked_index=build_ranked_index(listings))
    assert len(result) == MAX_FAVORITES


# ── Render contract ─────────────────────────────────────────────────


def test_render_skips_section_when_favorites_empty(pro_with_prefs, ranked_pool):
    """Empty `Issue.favorites` → no `saves-wrap` element in output.
    The 95% case in the wild (no saves yet) must not leak section
    chrome into the email."""
    import re
    pro_with_prefs.saves = []
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=8,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.favorites == []
    html = render_html(issue)
    # Strip the <style> block — the section's CSS comment legitimately
    # mentions "Your saved listings"; we only care about body content.
    body = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    assert 'class="saves-wrap"' not in body
    assert "Your saved listings" not in body


def test_render_emits_section_with_price_drop_chip(pro_with_prefs, ranked_pool):
    """A saved listing that's now priced lower in ranked.json shows
    the price-drop chip with the delta + struck-through old price."""
    target = ranked_pool[0]
    sid = f"{target['source']}__{target['source_id']}"
    original = target["price_usd"]
    target["price_usd"] = original - 5_000  # simulate this week's drop
    pro_with_prefs.saves = [SavedListing(id=sid, price_at_save_usd=original)]

    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=8,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    html = render_html(issue)

    assert 'class="saves-wrap"' in html
    assert "Your saved listings" in html
    assert "Price dropped" in html
    assert 'class="struck"' in html  # struck-through previous price


def test_render_off_market_chip_and_last_seen(pro_with_prefs, ranked_pool):
    """A saved listing no longer in ranked.json renders as off-market
    with the price-at-save as "Last seen at $X"."""
    pro_with_prefs.saves = [SavedListing(id="ghost__999", price_at_save_usd=125_000)]
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=8,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    html = render_html(issue)
    assert "off-market" in html.lower() or "marked off-market" in html.lower()
    assert "Last seen at $125,000" in html


def test_render_favorites_carries_no_italics(pro_with_prefs, ranked_pool):
    """Same v3.2 rule: no <em> in body content. Applies to the new
    section as much as the rest of the email."""
    import re
    target = ranked_pool[0]
    sid = f"{target['source']}__{target['source_id']}"
    pro_with_prefs.saves = [SavedListing(id=sid, price_at_save_usd=target["price_usd"])]
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=8,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    html = render_html(issue)
    body_only = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    assert body_only.count("<em>") == 0


def test_render_section_sits_between_lede_and_market(pro_with_prefs, ranked_pool):
    """Highest-attention slot per the mockup: AFTER the lede,
    BEFORE the market context. Position regression catch."""
    target = ranked_pool[0]
    sid = f"{target['source']}__{target['source_id']}"
    pro_with_prefs.saves = [SavedListing(id=sid, price_at_save_usd=target["price_usd"])]
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=8,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    html = render_html(issue)

    lede_idx = html.find("Hand-picked for")
    saves_idx = html.find('class="saves-wrap"')
    market_idx = html.find("Market context")
    assert lede_idx != -1 and saves_idx != -1 and market_idx != -1
    assert lede_idx < saves_idx < market_idx
