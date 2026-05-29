"""Compute the "Your saved listings — what changed this week" section.

Reads the recipient's saved-listings set (post-favorites-backend
enriched with `saved_at` + `price_at_save_usd`), diffs it against the
current week's `ranked.json`, and produces a list of `FavoriteUpdate`
rows ordered by editorial priority.

Design contract:

  • No saves → empty list → renderer skips the section entirely.
  • Each saved listing maps to ONE of three states:
      - price_dropped → current price < price_at_save_usd, delta > $0
      - price_up     → current price > price_at_save_usd (rare; truthful)
      - no_change    → still on market, same/near-same price
  • Saves missing from this week's ranked.json (sold? withdrawn?
    scraper hiccup? filtered out for data quality?) are silently
    SKIPPED. v3.3.1 (2026-05-29) removed an "off_market" state — its
    absence from ranked.json could mean any of those things, and
    conflating them with "sold" would lie to the reader. Add the
    state back the day ranked.json carries a real status=sold signal.
  • Up to MAX_FAVORITES rows surface. State priority on selection:
      price_dropped > price_up > no_change
  • Legacy entries without `price_at_save_usd` still surface as
    `no_change` — we just can't compute a delta.

The hard rule: never invent a baseline. If we don't have
`price_at_save_usd`, we don't emit `price_dropped`. The Account
section already shipped a "lying about persistence" bug; the
favorites section won't ship a "lying about a price drop" one.
"""

from __future__ import annotations

from typing import Optional

from .types import FavoriteUpdate, SavedListing


# Section caps to a small handful so the email stays scannable. The
# mockup renders three; we'll allow up to four when a strong-signal
# state (e.g. multiple price drops in a single week) is sitting on a
# user's saves list.
MAX_FAVORITES = 4

# A price move smaller than this is treated as "no_change" rather
# than a price_dropped/price_up event. Avoids surfacing rounding
# noise / FX adjustments as a meaningful seller move. $500 chosen
# from looking at typical listing prices ($60k – $500k); roughly 1%
# of the median.
PRICE_NOISE_FLOOR_USD = 500.0


def compute_favorites(
    *,
    saves: list[SavedListing],
    ranked_index: dict[str, dict],
    locale: str = "en",
    location_line_fn=None,
    absolute_photo_fn=None,
    pulpo_url_fn=None,
    issue_number: int = 0,
    site_root: str = "https://pulpo.club",
) -> list[FavoriteUpdate]:
    """Diff a recipient's saves against the current ranked.json.

    `ranked_index` is a dict keyed by `"{source}__{source_id}"` (the
    same shape api/saves.js uses for save IDs). Pass an empty dict
    to force every listing into the off-market branch (useful for
    tests).

    `location_line_fn`, `absolute_photo_fn`, `pulpo_url_fn` are
    injected from build_issue.py so we don't introduce a new
    cross-module dependency at import time. They share signatures
    with the equivalents already in build_issue.

    Returns up to MAX_FAVORITES rows ordered by editorial priority.
    Empty list when `saves` is empty (renderer skips the section).
    """
    if not saves:
        return []

    candidates: list[FavoriteUpdate] = []
    for save in saves:
        upd = _classify_one(
            save,
            ranked_index=ranked_index,
            locale=locale,
            location_line_fn=location_line_fn,
            absolute_photo_fn=absolute_photo_fn,
            pulpo_url_fn=pulpo_url_fn,
            issue_number=issue_number,
            site_root=site_root,
        )
        if upd is not None:
            candidates.append(upd)

    # Priority: price_dropped > price_up > no_change.
    # Within a state, preserve the user's saved-order (their list).
    _state_rank = {"price_dropped": 0, "price_up": 1, "no_change": 2}
    candidates.sort(key=lambda u: _state_rank.get(u.state, 99))
    return candidates[:MAX_FAVORITES]


def _classify_one(
    save: SavedListing,
    *,
    ranked_index: dict[str, dict],
    locale: str,
    location_line_fn,
    absolute_photo_fn,
    pulpo_url_fn,
    issue_number: int,
    site_root: str,
) -> Optional[FavoriteUpdate]:
    listing = ranked_index.get(save.id)

    if listing is None:
        # Saved listing not in this week's ranked.json. v3.3.1 (2026-05-29):
        # we silently skip these instead of surfacing an "off-market"
        # card. Absence from ranked.json could mean any of {sold,
        # withdrawn, filtered out for data quality, scraper transient
        # error} — we can't tell those apart today, and reporting
        # "marked off-market" for what may just be a scraper hiccup
        # would lie to the reader. Add back as a separate state the
        # day ranked.json carries a real status=sold signal.
        return None

    # Still on the market. Build the common metadata block.
    title = _title(listing, locale)
    location_line = _safe_call(location_line_fn, listing, locale, default="")
    photo_url = _safe_call(absolute_photo_fn, listing, site_root, default="")
    pulpo_url = _safe(pulpo_url_fn, save.id, issue_number, site_root)
    current_price = listing.get("price_usd")
    if not isinstance(current_price, (int, float)) or current_price <= 0:
        current_price = None

    # Price-change branches — only when both baselines are available.
    if (
        save.price_at_save_usd is not None
        and current_price is not None
    ):
        delta = save.price_at_save_usd - current_price
        if delta > PRICE_NOISE_FLOOR_USD:
            return FavoriteUpdate(
                state="price_dropped",
                listing_id=save.id,
                title=title,
                location_line=location_line,
                photo_url=photo_url,
                pulpo_url=pulpo_url,
                current_price_usd=float(current_price),
                price_at_save_usd=float(save.price_at_save_usd),
                delta_usd=float(delta),
                saved_at=save.saved_at,
            )
        if delta < -PRICE_NOISE_FLOOR_USD:
            return FavoriteUpdate(
                state="price_up",
                listing_id=save.id,
                title=title,
                location_line=location_line,
                photo_url=photo_url,
                pulpo_url=pulpo_url,
                current_price_usd=float(current_price),
                price_at_save_usd=float(save.price_at_save_usd),
                delta_usd=float(abs(delta)),
                saved_at=save.saved_at,
            )

    # No meaningful price move (or no baseline to compare). Fall
    # through to no_change with days_listed so the card has content.
    days = listing.get("days_listed")
    return FavoriteUpdate(
        state="no_change",
        listing_id=save.id,
        title=title,
        location_line=location_line,
        photo_url=photo_url,
        pulpo_url=pulpo_url,
        current_price_usd=float(current_price) if current_price is not None else None,
        price_at_save_usd=save.price_at_save_usd,
        days_listed=int(days) if isinstance(days, int) else None,
        saved_at=save.saved_at,
    )


def _title(listing: dict, locale: str) -> str:
    tc = listing.get("title_canonical") or {}
    if isinstance(tc, dict):
        return (tc.get(locale) or tc.get("en") or listing.get("title") or "Listing")
    return listing.get("title") or "Listing"


def _safe(fn, *args):
    """Wrap a None-tolerant call to an injected helper that returns a string."""
    if fn is None:
        return ""
    try:
        result = fn(*args)
        return result if isinstance(result, str) else ""
    except Exception:
        return ""


def _safe_call(fn, *args, default=""):
    """Variant for helpers with kwargs in their signature."""
    if fn is None:
        return default
    try:
        result = fn(*args)
        return result if isinstance(result, str) else default
    except Exception:
        return default


def build_ranked_index(ranked_listings: list[dict]) -> dict[str, dict]:
    """Index a ranked.json-shape list by "{source}__{source_id}" key.

    Matches the ID format api/saves.js stores in privateMetadata.saves.
    """
    out: dict[str, dict] = {}
    for listing in ranked_listings:
        if not isinstance(listing, dict):
            continue
        source = listing.get("source")
        source_id = listing.get("source_id")
        if not isinstance(source, str) or not source_id:
            continue
        out[f"{source}__{source_id}"] = listing
    return out
