"""Producer/consumer contract for the `is_agricultural` exclusion.

PRD A4 — locks the canonical FE exclusion surface so a future refactor
can't silently remove the filter that the entire user-facing rendering
funnel depends on.

Pattern mirrors `tests/api/email_type_contract.test.js` (the post-
2026-05-28 producer/consumer pattern called out in CLAUDE.md).

Scope decision
--------------
The first iteration of this test greped the full repo for ranked.json
readers, then narrowed to "user-facing renderers." Both turned out to be
the wrong shape:

- The broad grep was 80+ files, 90% false positives.
- The user-rendering list included single-listing fetchers (saves, l/,
  social/card) that don't render *lists* of inventory; they receive a
  listing by ID and serve it. Filtering at the read-by-ID layer is the
  wrong abstraction.

The contract that actually matters: the canonical FE filter
(`excludeAgricultural` in `web/app/data/use-listings.tsx`) is the
load-bearing surface — every FE renderer of the listings array goes
through it. PR A4's lock is:

  1. The helper must exist and have the correct predicate shape.
  2. `HomeShelf.jsx::pickTopByMasterAndSub` keeps the defense-in-depth
     clause so a future caller bypassing the data hook still gets the
     exclusion before listings hit a curated shelf.
  3. Known gaps in the Python rendering path (newsletter, featured,
     repick) are documented inline for the follow-up cleanup PR — not
     enforced here because the agri-LAND purge in
     `automation/run.py` already strips the dominant case (pure
     agricultural land); the remaining gap is built-structure
     agricultural listings (agri-HOUSE/agri-CONDO) that the narrowed
     2026-05-25 purge intentionally retains.

Tracked follow-ups (NOT enforced by this test):
  - automation/newsletter/build_issue.py
  - automation/newsletter/render_html.py
  - automation/newsletter/welcome_dispatch.py
  - automation/newsletter/segments.py
  - automation/newsletter/favorites.py
  - pulpo/featured_listing.py
  - automation/repick_heroes.py
"""
from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_canonical_excludeagricultural_exists():
    """The named helper at web/app/data/use-listings.tsx is the
    canonical FE exclusion surface. Every other FE reader inherits
    it via the data hook."""
    src = (REPO_ROOT / "web" / "app" / "data" / "use-listings.tsx").read_text()
    assert "export function excludeAgricultural" in src, (
        "Missing canonical excludeAgricultural helper in use-listings.tsx. "
        "Removing this surface silently re-includes agricultural inventory "
        "across the entire FE rendering funnel."
    )


def test_canonical_predicate_shape_unchanged():
    """The predicate must be `is_agricultural !== true` (not `=== false`,
    not `!`) to handle undefined/null/false correctly. A refactor that
    inverts the filter would silently re-include agricultural rows."""
    src = (REPO_ROOT / "web" / "app" / "data" / "use-listings.tsx").read_text()
    assert "is_agricultural !== true" in src, (
        "excludeAgricultural predicate shape changed — must remain "
        "`is_agricultural !== true` to treat undefined/null as "
        "non-agricultural. Inverting to `=== true` would silently "
        "include the entire agricultural pool."
    )


def test_home_shelf_has_defense_in_depth_filter():
    """HomeShelf.jsx::pickTopByMasterAndSub must include the
    `!l.is_agricultural` clause. Defense-in-depth: a future caller
    that bypasses the data hook still has agricultural inventory
    excluded before it surfaces on a curated shelf."""
    src = (REPO_ROOT / "web" / "app" / "home" / "HomeShelf.jsx").read_text()
    match = re.search(
        r"function\s+pickTopByMasterAndSub.*?\.is_agricultural\s*!==\s*true",
        src,
        flags=re.DOTALL,
    )
    assert match is not None, (
        "HomeShelf.jsx::pickTopByMasterAndSub missing "
        "`!l.is_agricultural` defense-in-depth filter. Add the clause "
        "back so direct-data callers don't bypass the agricultural "
        "exclusion."
    )


def test_use_listings_provider_wires_excludeagricultural():
    """The ListingsProvider must actually CALL excludeAgricultural in
    the loadListings().then() branch. Defining the helper but not
    invoking it would silently re-include agricultural rows."""
    src = (REPO_ROOT / "web" / "app" / "data" / "use-listings.tsx").read_text()
    # Look for the helper call inside the .then handler. Loose pattern
    # tolerates either direct call or a `const filtered = exclude…`
    # destructure style.
    assert "excludeAgricultural(" in src, (
        "use-listings.tsx defines excludeAgricultural but never invokes it. "
        "Every loaded listings array must pass through the helper."
    )
