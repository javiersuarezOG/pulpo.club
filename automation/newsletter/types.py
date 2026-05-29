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
    # PR-NL-8 — population of this field happens in subscribers.py from
    # Clerk's privateMetadata.saves[] length. Anonymous recipients (no
    # Clerk record) stay at 0. Defaults so older callers that build a
    # Recipient by hand don't have to pass it.
    saved_count: int = 0


ChipKind = Literal["neutral", "warm", "cool"]
# neutral = quiet context (e.g. "20 min walk to beach", "Power at the lot")
# warm    = recent action / urgency (e.g. "↓ Just dropped −$5,000")
# cool    = strong signal worth highlighting (e.g. "★ Top pick", "−78% under area average")


@dataclass
class Chip:
    """Tiny supportive label rendered next to a pick.

    Replaces the older `pills: list[str]` field on IssuePick — chips carry
    a `kind` so the renderer can color them appropriately (matching the
    mockup at /newsletter-mockup-v2). Max ~4 chips per pick; build_issue
    prioritizes warm > cool > neutral when trimming to the cap.
    """

    label: str
    kind: ChipKind = "neutral"


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
    listing_url: str                             # external source URL (e.g. remax-elsalvador.com/...)
    pills: list[str]                             # legacy; kept for back-compat with the old short_pick renderer
    blurb: str                                   # main paragraph (LLM-enriched listing description)
    callouts: list[dict]                         # [{"label": "...", "body": "..."}]
    keytable: list[tuple[str, str]]              # [("Built", "Small casita"), ...]
    paywalled: bool = False                      # free-tier hides body/CTA below a teaser
    is_repriced: bool = False
    is_new_this_fortnight: bool = False
    # ── PR-NL-5 additions ────────────────────────────────────────────
    # `pulpo_url` is the canonical /listing/<source_id> page on pulpo.club
    # — the "See on Pulpo" CTA. `save_url` carries `?save=1` so the SPA
    # can auto-trigger the save on mount once PR-NL-8 wires it; today it
    # degrades to the same listing page with the heart button.
    pulpo_url: str = ""
    save_url: str = ""
    chips: list[Chip] = field(default_factory=list)
    # ── PR-NL-6 additions ────────────────────────────────────────────
    # `story_html` is the warm editorial paragraph rendered above the
    # callouts on hero picks. Sourced from voice_guide.md +
    # llm_story.py when PULPO_NEWSLETTER_USE_LLM is on, falling back to
    # commentary.deterministic_story_for_pick when LLM is off / over-cap
    # / errors. Wrapped in `<em>...</em>` around the single emotional
    # center sentence (the renderer styles `em` clay-deep italic).
    # `blurb` stays on the type for short-pick rendering — story_html is
    # hero-only for now.
    story_html: str = ""
    # Records how the story was sourced so PostHog telemetry +
    # post-mortems can tell LLM output apart from the deterministic
    # fallback when chasing a quality regression.
    story_source: Literal["llm", "deterministic", "fallback_on_error", ""] = ""
    # ── v3 redesign · "Why we picked it" block ──────────────────────
    # Three plain-English bullets, each tied to a real Listing field
    # (price_vs_zone_pct / dist_beach_km / readiness_score / …).
    # Replaces the opaque "value 100 · location 100 · momentum 50"
    # rank-reasons row from v2.x. Sourced from
    # commentary.deterministic_why_for_pick — never from an LLM, never
    # from the rank score itself. Empty for paywalled picks (the
    # reader can't see the listing yet) and for short picks (those
    # use a single "For someone who…" framing line instead).
    why_bullets: list[str] = field(default_factory=list)
    # Single "For someone who *wants surf-city land cheap*" line shown
    # under each shortlist entry. Renderer wraps the italic phrase in
    # <em>. Sourced from commentary.deterministic_shortlist_frame.
    shortlist_frame_html: str = ""


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
class YourPulpoState:
    """PR-NL-8 — the "Your Pulpo" block at the bottom of the issue.

    Three rows tying the email back to the SPA:
      1. saved_count → /saved        ("Open your favorites")
      2. filter_summary_human → /account/notifications  ("Edit your filter")
      3. filter_match_count → /browse  ("Browse all in your filter")

    Anonymous cohort (no Clerk record) renders a softened variant —
    `saved_count = 0`, `filter_summary_human = ""` → the renderer
    swaps in welcome-style copy.
    """

    saved_count: int = 0
    filter_summary_human: str = ""               # "La Libertad · land · under $500k"
    filter_match_count: int = 0


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
    # PR-NL-8 — Your Pulpo block. Defaults so existing test fixtures
    # that build Issue by hand still work.
    your_pulpo: YourPulpoState = field(default_factory=YourPulpoState)
