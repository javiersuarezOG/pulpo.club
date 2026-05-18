"""Newsletter data types.

Kept on stdlib dataclasses to match pulpo/models.py — no Pydantic, no
serialization framework. Each Issue is the contract between build_issue.py
and render_html.py: if a field isn't on Issue, the template can't read it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# Four buyer cohorts the build pipeline branches on. See the module-level
# proposal for the full table. The render template adapts content per cohort
# (e.g. "C / D" get an "adjust your filter" CTA instead of named picks).
Cohort = Literal["pro_prefs", "free_prefs", "logged_no_prefs", "anonymous"]

Locale = Literal["en", "es"]


@dataclass
class Preference:
    """Filter spec applied to ranked.json to produce a recipient's top-N.

    Empty defaults mean "no opinion" — segments.py treats that as a passthrough.
    Authenticated users with prefs set populate any non-empty subset; anonymous
    cohorts get the broadest fallback (see build_issue.fallback_preference).
    """

    zones: list[str] = field(default_factory=list)                # zone slugs
    departments: list[str] = field(default_factory=list)
    property_types: list[str] = field(default_factory=list)       # land/house/condo
    max_price_usd: Optional[float] = None
    min_price_usd: Optional[float] = None
    categories: list[str] = field(default_factory=list)           # keys from lib/categories.ts


@dataclass
class Recipient:
    """A single newsletter recipient at send time.

    `email_hash` is the deterministic key used by store.py — never the raw
    address. The store joins recipient → previously-sent listings without
    recording PII.
    """

    email_hash: str
    display_name: Optional[str]                 # "Javier" (first name) or None
    locale: Locale
    tier: Literal["free", "pro", "agency"]
    has_account: bool                            # False == anonymous Resend-only contact
    preference: Preference


@dataclass
class IssuePick:
    """One listing as it lands in the rendered template.

    Carries only what the template needs. The full ranked.json row stays in
    build_issue's scope so we don't bloat email-side data.
    """

    rank: int
    source_id: str
    title: str
    location_line: str                           # "Chiltiupán · La Libertad · 25 min to El Zonte"
    price_text: str                              # "$185,000" or "from $199,386"
    price_note: Optional[str]                    # "· negotiable · paperwork is clean"
    photo_url: str                               # absolute https://
    listing_url: str
    pills: list[str]                             # ["Working land", "Coffee · river · trees"]
    blurb: str                                   # main paragraph
    callouts: list[dict]                         # [{"label": "...", "body": "..."}]
    keytable: list[tuple[str, str]]              # [("Built", "Small casita"), ...]
    paywalled: bool = False                      # free-tier hides body/CTA below a teaser
    is_repriced: bool = False
    is_new_this_fortnight: bool = False


@dataclass
class Commentary:
    """Per-issue editorial copy that ISN'T tied to one listing.

    Currently filled by commentary.py's deterministic stub; PR-NL-3 toggles
    in the DeepSeek path (same provider as automation/llm_enrichment.py).
    """

    eyebrow_hero: str
    headline_hero: str
    lede_hero: str
    filter_chips: list[str]
    glance_subhead: str
    skip_headline: Optional[str]
    skip_blurb: Optional[str]
    market_context: list[str]                    # paragraph strings
    one_number_title: Optional[str]
    one_number_body: Optional[str]


@dataclass
class Issue:
    issue_id: str                                # YYYY-MM-DD of generation
    issue_number: int                            # 01, 02, 03 …
    issue_date_human: str                        # "18 May 2026"
    recipient: Recipient
    cohort: Cohort
    locale: Locale
    glance: list[dict]                           # [{"num": "01", "title": "...", "where": "...", "price": "$185,000"}, ...]
    picks_top: list[IssuePick]                   # rendered with hero image (2 by default)
    picks_shortlist: list[IssuePick]             # rendered as 2-column rows
    skip_pick: Optional[IssuePick]
    commentary: Commentary
    paywall_banner: bool                         # free-tier sees the upgrade CTA in body
    paywall_target_url: str                      # /api/stripe/start-checkout?ref=newsletter_issue_<N>
    settings_url: str
    unsubscribe_url: str
    welcome_prefs_url: Optional[str]             # anonymous cohort gets a "set your filter" link
