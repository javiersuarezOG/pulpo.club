"""Favorites backend — diff logic + render contract.

Coverage:

  • _normalize_saves in subscribers.py: legacy bare-ID strings + new
    enriched objects + malformed entries collapse into a uniform
    `list[dict]` with `{id, saved_at?, price_at_save_usd?, source?}`.
  • compute_favorites in favorites.py: classification into one of
    `price_dropped / no_change / price_up`, priority ordering,
    MAX_FAVORITES cap, noise floor on small price moves, truthful
    fallback when baselines are missing, AND silent skipping of
    saves missing from ranked.json (v3.3.1: no off_market state —
    a save's absence could mean sold / withdrawn / scraper hiccup /
    filtered out for data quality, and conflating them lies to the
    reader).
  • Renderer behavior: empty favorites → section skipped; non-empty
    → cards in the expected order, price-drop chip with the delta,
    no italics.
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


def test_save_missing_from_ranked_is_silently_skipped():
    """v3.3.1 (2026-05-29): a saved listing missing from this week's
    ranked.json is silently dropped — NOT surfaced as "off-market".
    Absence could mean any of {sold, withdrawn, scraper hiccup,
    filtered out for data quality}, and reporting it as sold would
    lie to the reader. Add back as a separate state the day
    ranked.json carries a real status=sold signal.

    Applies regardless of whether the save has a price baseline —
    no off_market card means no fabricated "Last seen at $X" copy.
    """
    # With a price baseline — still skipped under v3.3.1.
    saves = [_save(price_at_save_usd=60_000)]
    result = compute_favorites(saves=saves, ranked_index={})
    assert result == []

    # Without a baseline — still skipped (same as v3.3).
    saves = [_save()]
    result = compute_favorites(saves=saves, ranked_index={})
    assert result == []


def test_partial_index_skips_missing_keeps_present():
    """A mix of saves where some are in ranked.json and some aren't:
    only the ones present in ranked.json surface; missing ones are
    silently dropped without affecting the rest."""
    saves = [
        SavedListing(id="a__present", price_at_save_usd=60_000),
        SavedListing(id="b__missing", price_at_save_usd=60_000),
        SavedListing(id="c__present", price_at_save_usd=55_000),
    ]
    index = build_ranked_index([
        {"source": "a", "source_id": "present", "price_usd": 60_000,
         "title_canonical": {"en": "A"}, "days_listed": 5},
        # b is intentionally absent
        {"source": "c", "source_id": "present", "price_usd": 60_000,
         "title_canonical": {"en": "C"}, "days_listed": 5},
    ])
    result = compute_favorites(saves=saves, ranked_index=index)
    ids = [u.listing_id for u in result]
    assert "a__present" in ids
    assert "c__present" in ids
    assert "b__missing" not in ids
    # And no off_market state ever returned
    assert all(u.state != "off_market" for u in result)


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
        SavedListing(id="b__price_up", price_at_save_usd=55_000),
        SavedListing(id="c__price_drop", price_at_save_usd=60_000),
    ]
    index = build_ranked_index([
        {"source": "a", "source_id": "no_change", "price_usd": 60_000,
         "title_canonical": {"en": "A"}, "days_listed": 5},
        {"source": "b", "source_id": "price_up", "price_usd": 60_000,
         "title_canonical": {"en": "B"}, "days_listed": 5},
        {"source": "c", "source_id": "price_drop", "price_usd": 55_000,
         "title_canonical": {"en": "C"}, "days_listed": 5},
    ])
    result = compute_favorites(saves=saves, ranked_index=index)
    assert [u.state for u in result] == ["price_dropped", "price_up", "no_change"]


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

    # v4 (2026-05-31): `class="saves-wrap"` / `class="saves-pad"` were
    # the v3 saves chrome; the v4 rewrite uses inline-styled blocks
    # keyed on `saves-eyebrow` / `saves-h2` (still present as class
    # hooks for snapshot stability).
    assert 'class="saves-eyebrow"' in html
    assert "Your favorites" in html  # v4 eyebrow copy
    assert "Price dropped" in html
    assert 'class="struck"' in html  # struck-through previous price


# ── Admin preview path seeds saves ─────────────────────────────────


def test_synthesize_preview_recipients_seeds_three_saves():
    """The admin preview button must render the favorites section so
    the operator can QA it. Pre-fix the preview Recipient had
    saves=[] → compute_favorites returned [] → renderer collapsed the
    section. Operators triggered EN + ES previews and saw no favorites
    cards even though the renderer was fully v3.3.1.

    This test pins the fix: synthesize_preview_recipients now seeds
    three SavedListing entries against real IDs from ranked.json,
    spanning the three favorites states.
    """
    from automation.newsletter.subscribers import synthesize_preview_recipients

    recipients = synthesize_preview_recipients("operator@example.com", locale="en")
    assert len(recipients) == 1
    recipient, raw_email = recipients[0]
    # Match the ranked.json availability — could be 0/1/2/3 depending
    # on test fixture state, but ranked.json is checked into web/data
    # so we expect the full three here.
    assert len(recipient.saves) == 3, (
        "preview recipient must carry 3 sample saves; got "
        f"{len(recipient.saves)} — admin preview won't render favorites"
    )
    assert recipient.saved_count == 3
    # Each save has the full enriched shape so the diff can produce
    # all three states (price_dropped / no_change / price_up).
    for s in recipient.saves:
        assert s.id and "__" in s.id, f"malformed save id: {s.id}"
        assert s.price_at_save_usd is not None
        assert s.price_at_save_usd > 0
        assert s.saved_at is not None


def test_synthesize_preview_recipients_survives_missing_ranked(monkeypatch, tmp_path):
    """If ranked.json is unreadable (CI race, fresh checkout, file
    corrupt), the preview must still build successfully — just with
    an empty saves list. The favorites section will collapse, but the
    preview email itself ships."""
    from automation.newsletter import subscribers as subs

    def fake_build_preview_saves():
        return []

    monkeypatch.setattr(subs, "_build_preview_saves", fake_build_preview_saves)
    recipients = subs.synthesize_preview_recipients("op@example.com", locale="en")
    assert len(recipients) == 1
    assert recipients[0][0].saves == []
    assert recipients[0][0].saved_count == 0


# ── Observability ───────────────────────────────────────────────────


def test_favorites_telemetry_fires_with_state_counts(pro_with_prefs, ranked_pool, monkeypatch):
    """`newsletter.favorites_section_rendered` fires once per Issue with
    per-state counts + diagnostic shape. Dashboard rollups need every
    one of these to land.
    """
    captured: list[tuple[str, dict]] = []

    def fake_capture(event, props):
        captured.append((event, props))

    # Inject our fake into the same path build_issue imports through.
    # The package __init__ re-exports the build_issue FUNCTION as
    # `automation.newsletter.build_issue`, shadowing the module of
    # the same name. Reach the module via importlib so the
    # monkeypatch targets the actual `_telemetry_capture` symbol.
    import importlib
    bi_module = importlib.import_module("automation.newsletter.build_issue")
    monkeypatch.setattr(bi_module, "_telemetry_capture",
                        lambda event, props: captured.append((event, props)))

    target = ranked_pool[0]
    sid = f"{target['source']}__{target['source_id']}"
    pro_with_prefs.saves = [SavedListing(id=sid, price_at_save_usd=target["price_usd"] + 5_000)]
    pro_with_prefs.saved_count = 1

    build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=8,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )

    favorites_events = [(e, p) for e, p in captured if e == "newsletter.favorites_section_rendered"]
    assert len(favorites_events) == 1, "telemetry must fire exactly once per Issue"
    _, props = favorites_events[0]
    # Section was rendered (one save, with baseline, found in ranked) → price_dropped surface
    assert props["section_rendered"] is True
    assert props["favorites_count"] == 1
    assert props["state_price_dropped"] == 1
    assert props["state_price_up"] == 0
    assert props["state_no_change"] == 0
    assert props["saves_total"] == 1
    assert props["saves_with_baseline"] == 1
    assert props["saves_missing_from_ranked"] == 0
    assert props["template_version"].startswith("newsletter-v")
    assert props["issue_number"] == 8
    assert "issue_id" in props
    assert "recipient_hash" in props
    # PII guard — never leak the raw email
    assert "@" not in props["recipient_hash"]


def test_favorites_telemetry_dark_section_branch(pro_with_prefs, ranked_pool, monkeypatch):
    """The dashboard distinguishes 'no saves at all' from 'has saves
    but all missing from ranked' — both render no section but mean
    different things. saves_missing_from_ranked carries the count
    so we can separate them."""
    captured: list[tuple[str, dict]] = []

    # The package __init__ re-exports the build_issue FUNCTION as
    # `automation.newsletter.build_issue`, shadowing the module of
    # the same name. Reach the module via importlib so the
    # monkeypatch targets the actual `_telemetry_capture` symbol.
    import importlib
    bi_module = importlib.import_module("automation.newsletter.build_issue")
    monkeypatch.setattr(bi_module, "_telemetry_capture",
                        lambda event, props: captured.append((event, props)))

    # Recipient has 2 saves but neither is in ranked_pool — section goes dark.
    pro_with_prefs.saves = [
        SavedListing(id="ghost__1", price_at_save_usd=100_000),
        SavedListing(id="ghost__2", price_at_save_usd=200_000),
    ]
    pro_with_prefs.saved_count = 2

    build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=8,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )

    favorites_events = [p for e, p in captured if e == "newsletter.favorites_section_rendered"]
    assert len(favorites_events) == 1
    props = favorites_events[0]
    assert props["section_rendered"] is False
    assert props["favorites_count"] == 0
    assert props["saves_total"] == 2
    assert props["saves_missing_from_ranked"] == 2


def test_render_skips_save_missing_from_ranked(pro_with_prefs, ranked_pool):
    """v3.3.1: a saved listing whose ID is not in ranked.json no longer
    surfaces an "off-market" card. The section vanishes entirely when
    every save is missing — no chrome, no chip, no "Last seen at $X"
    leaks into the rendered HTML (those copy strings would mislead).
    """
    import re
    pro_with_prefs.saves = [SavedListing(id="ghost__999", price_at_save_usd=125_000)]
    issue = build_issue(
        recipient=pro_with_prefs,
        ranked_listings=ranked_pool,
        issue_number=8,
        issue_date=ISSUE_DATE,
        history_rows=[],
    )
    assert issue.favorites == [], "Missing-save should not surface any FavoriteUpdate"
    html = render_html(issue)
    body = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    # No section
    assert 'class="saves-wrap"' not in body
    # And no off-market language anywhere
    assert "off-market" not in body.lower()
    assert "Marked off-market" not in body
    assert "Last seen at" not in body
    assert "off_market" not in body


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
    # v4: `saves-wrap` was dropped in the inline-style rewrite; anchor on
    # the surviving `saves-eyebrow` class hook instead.
    saves_idx = html.find('class="saves-eyebrow"')
    market_idx = html.find("Market context")
    assert lede_idx != -1 and saves_idx != -1 and market_idx != -1
    assert lede_idx < saves_idx < market_idx
