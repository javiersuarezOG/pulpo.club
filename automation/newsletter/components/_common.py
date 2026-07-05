"""Shared helpers used by every component in this package.

Public exports:
  • `TEMPLATE_VERSION` — stamped into the rendered `<meta>` tag so
    PostHog telemetry can slice rendered emails by template revision.
    Bump this when the renderer's CSS or layout changes meaningfully.
  • `escape` (re-export of `html.escape`) — single import path for every
    component so we don't sprinkle `from html import escape` across N files.
  • `CSS` — the canonical `<style>` block. Email clients without inline-only
    rendering will pick up these rules; the components also duplicate critical
    styles inline so Outlook / Yahoo still render the design (see PR #572).
  • `site_root_from_issue` — extract the canonical `https://pulpo.club` host
    from an Issue's settings/unsubscribe URL. Used wherever components need
    to build a fresh URL.

Anything kept here is genuinely cross-cutting. Component-specific helpers
live with their component.
"""

from __future__ import annotations

from html import escape

from ..types import Issue

# Bumped whenever the renderer's CSS or layout changes in a way we'd want
# to slice in PostHog (audience tests, regression hunts, A/B pre-bake).
# Stays in sync with docs/newsletter-audit.md. Exposed via
# email.newsletter.sent / email.newsletter.batch_sent telemetry AND a
# <meta name="x-pulpo-template"> tag in the rendered HTML <head>.
#
# Revision history (most recent first):
#   v4.4 (2026-06-01) — unified rank label across all 10 picks
#       ("Top deal · NN" / "Mejor oferta · NN" everywhere; the
#       white-vs-sage card surface still telegraphs hero-vs-shortlist
#       editorial weight). Title widow guard: post-escape &nbsp;
#       between last short word + preceding word, plus inline
#       text-wrap: balance for modern email clients.
#   v4.3 (2026-05-31) — hard photo-eligibility filter (no broker-logo
#       placeholders) · chrome alignment (header/hero/footer flush at
#       24px horizontal) · inline-SVG brand mark replaced with hosted
#       PNG (works on Gmail iOS / Outlook desktop / Yahoo / AOL) ·
#       `&hearts;&#xfe0e;` text variation selector + `white-space:
#       nowrap` on Save / See-on-Pulpo CTAs
#   v4.2 (2026-05-31) — component package + templates registry scaffolding
#   v4.1 (2026-05-31) — italic removal · Pro branding pill in header/footer ·
#       numbered editorial blocks in market context · v4.0 photo-fallback
#       placeholder (superseded in v4.3 by the hard upstream filter)
#   v4.0 (2026-05-30) — locked card component · section intros ·
#       Weekly News Spotlight · Your Pulpo cream cards · footer pill
#       buttons · skip + next-issue blocks removed
#   v4.5 (2026-06-06) — Weekly News Spotlight now READS from the committed
#       artifact (web/data/news_spotlight.json, nightly carry-forward) so
#       every Pro email cites a real outlet article; the source-less
#       "Pulpo Pro coastal scan" filler is retired and the section is
#       omitted entirely on a cold start. Spotlight HTML changed.
#   v4.6 (2026-06-09) — footer Unsubscribe link now carries `&e=<edition>`
#       + `&l=<locale>` so /api/unsubscribe can render the in-brand
#       free-vs-pro confirmation page. Cosmetic params only (not in the
#       HMAC); rendered footer HTML changed, hence the bump.
#   v4.7 (2026-06-10) — footer Unsubscribe link's edition/locale params
#       (`&e=`/`&l=`) now derive from the renderer's `free` flag in
#       _footer_html (variant-driven) instead of recipient.tier, so the
#       /api/unsubscribe confirmation page always matches the edition
#       sent. Standard-send output byte-identical; logic changed.
#   v4.8 (2026-06-12) — listing <img> tags now carry a height attribute
#       (680x453 = 3:2 reservation; save-thumb 96x84) so email clients
#       reserve vertical space pre-load and don't reflow. CSS height:auto
#       still rescales on load (plan 007 step 4).
#   v5.0 (2026-07-05) — Your Pulpo filter summary now localizes category
#       tokens through i18n (filter.category.<slug>) instead of humanizing
#       the raw slug: a Spanish reader with a category filter sees "Vista
#       al mar" not "Ocean View" (enum-render trap fix, launch audit P0-4).
#       Rendered Your Pulpo block changes for category-filtered recipients
#       in BOTH locales (EN casing "Ocean View" -> "Ocean view" too).
#   v5.1 (2026-07-05) — two ES leaks fixed (launch audit D). (1) masthead
#       date is locale-aware: the Spanish edition renders "5 ene 2026" not
#       "5 Jan 2026" (_format_issue_date; strftime %b is English-only) —
#       header + <title> change for months whose abbreviation differs EN↔ES
#       (Jan/Apr/Aug/Dec, ...). (2) footer filter summary dropped the
#       hardcoded English " OK" after "Terreno" and the literal "default"
#       fallback (now "Todas las propiedades").
TEMPLATE_VERSION = "newsletter-v5.1-2026-07-05"

# Human-readable timestamp surfaced in component docs + the admin
# widget so collaborators can see when the locked design was last
# revised without trawling git log. Matches the `vN.N (date)` line at
# the top of the revision history above.
LAST_UPDATED = "2026-07-05"


# ─────────────────────────────────────────────────────────────────────
# Pulpo Pro Welcome — own version line.
#
# The welcome template ships on a separate cadence from the weekly
# General digest: a copy tweak to the warm hero, a re-shape of the
# "How Pulpo works" beats, or a new onboarding card all bump the
# welcome version WITHOUT touching the General's. Keeping the two
# version lines in parallel lets PostHog slice rendered welcomes from
# weeklies cleanly and lets the admin widget surface the right
# version chip on each newsletter card.
#
# The regex in `api/admin/newsletter/template-version.js` is anchored
# with `^...` + the `m` flag so it can disambiguate
# WELCOME_TEMPLATE_VERSION from TEMPLATE_VERSION at the line-start
# level. Adding more named templates here in future = one more
# constant pair + one more regex row in the API.
#
# Revision history (most recent first):
#   welcome-v2.0 (2026-06-02) — MAJOR restructure. The welcome is now
#       the General weekly master with ONLY the hero swapped
#       (render_html variant="welcome"): it carries the full weekly body
#       (favorites, market context, 10 picks, news spotlight, Your Pulpo,
#       footer) and drops the bespoke onboarding blocks (how-it-works,
#       cadence note, "your first 10" intro, "Start here" cards). The
#       rendered HTML changed end-to-end vs v1.0, hence the major bump.
#   welcome-v1.0 (2026-06-01) — initial ship. Welcome hero + "How
#       Pulpo works" 3-beat block + cadence note + "Your first 10
#       picks" section intro + "Start here" onboarding cards.
#   welcome-v2.1 (2026-06-06) — inherits the v4.5 Weekly News Spotlight
#       change (real-article artifact read, filler retired). Welcome body
#       carries the spotlight, so its HTML changed.
#   welcome-v2.2 (2026-06-09) — inherits the v4.6 footer Unsubscribe-link
#       edition/locale params. Welcome body carries the footer, so its
#       HTML changed.
#   welcome-v2.3 (2026-06-10) — inherits the v4.7 footer edition-stamp
#       change (page == email edition). Welcome body carries the footer.
#   welcome-v2.4 (2026-06-12) — inherits the v4.8 listing <img> height
#       reservation. Welcome body carries listing cards, so its HTML changed.
#   welcome-v2.6 (2026-07-05) — inherits the v5.0 Your Pulpo category
#       localization (P0-4). Welcome body carries Your Pulpo.
WELCOME_TEMPLATE_VERSION = "welcome-v2.7-2026-07-05"
WELCOME_LAST_UPDATED = "2026-07-05"


# ─────────────────────────────────────────────────────────────────────
# Pulpo Pro Welcome BACK (resubscribe) — own version line.
#
# The resubscribe re-acquisition email ships on its own cadence too:
# a copy tweak to the "Good to have you back" hero or the "Pick up
# where you left off" cards bumps THIS version without touching the
# first-time welcome or the weekly General. Same parallel-version
# rationale as WELCOME_TEMPLATE_VERSION above — lets PostHog slice
# welcome-back renders cleanly from first-time welcomes and weeklies.
#
# Revision history (most recent first):
#   welcome-back-v1.0 (2026-06-02) — initial ship. The General weekly
#       master with ONLY the hero swapped to a "Welcome back" greeting
#       (render_html variant="welcome_back"). Hero copy DERIVES from the
#       welcome.* strings via i18n.welcome_text, so it can't drift from
#       the first-time welcome beyond the greeting. Same full weekly body
#       as the General + first-time welcome.
#   welcome-back-v1.1 (2026-06-06) — inherits the v4.5 Weekly News
#       Spotlight change (real-article artifact read, filler retired).
#       Welcome-back body carries the spotlight, so its HTML changed.
#   welcome-back-v1.2 (2026-06-09) — inherits the v4.6 footer
#       Unsubscribe-link edition/locale params. Welcome-back body carries
#       the footer, so its HTML changed.
#   welcome-back-v1.3 (2026-06-10) — inherits the v4.7 footer edition-
#       stamp change. Welcome-back body carries the footer.
#   welcome-back-v1.4 (2026-06-12) — inherits the v4.8 listing <img>
#       height reservation. Welcome-back body carries listing cards.
#   welcome-back-v1.6 (2026-07-05) — inherits the v5.0 Your Pulpo category
#       localization (P0-4). Welcome-back body carries Your Pulpo.
WELCOME_BACK_TEMPLATE_VERSION = "welcome-back-v1.7-2026-07-05"
WELCOME_BACK_LAST_UPDATED = "2026-07-05"


# ─────────────────────────────────────────────────────────────────────
# Pulpo FREE General — own version line.
#
# The free-tier weekly digest. It IS the General weekly master
# (render_html variant="free_general") with three free-cohort changes,
# all gated on the variant so the Pro path never sees them:
#   1. masthead drops the gold "PRO" badge -> plain `pulpo`.
#   2. ranks 04-10 swap the "See on Pulpo" CTA for "Sign up to Pro"
#      (top 3 keep "See on Pulpo"); every card still renders the full
#      listing component (photo, title, location, price, why-block).
#   3. the Weekly News Spotlight is Pro-LOCKED: real headline + source +
#      opening sentence show, the rest of the read sits behind a sign-up
#      panel.
# Same parallel-version rationale as the welcome lines above — lets
# PostHog slice free-weekly renders from Pro weeklies, and the admin
# widget surface the right version chip. The regex in
# api/admin/newsletter/template-version.js reads this at line-start.
#
# Revision history (most recent first):
#   free-general-v1.0 (2026-06-07) — initial ship. Plain `pulpo`
#       masthead, top-3 "See on Pulpo" + ranks 04-10 "Sign up to Pro",
#       Pro-locked Weekly News Spotlight. Built on the v4.5 master body
#       (real-article spotlight artifact).
#   free-general-v1.2 (2026-07-05) — inherits the v5.0 Your Pulpo category
#       localization (P0-4). Free weekly carries Your Pulpo.
FREE_GENERAL_TEMPLATE_VERSION = "free-general-v1.3-2026-07-05"
FREE_GENERAL_LAST_UPDATED = "2026-07-05"


# ─────────────────────────────────────────────────────────────────────
# Pulpo FREE Welcome + Welcome-back — own version lines.
#
# The free-tier onboarding pair. Each is the free-general master
# (render_html variant="free_welcome" / "free_welcome_back") with ONLY
# the hero swapped — same plain-`pulpo` masthead, "Sign up to Pro" ranks
# 04-10, and Pro-locked spotlight as the free weekly. The welcome-back
# hero DERIVES from the free welcome copy via i18n.welcome_text (same
# "Welcome → Welcome back" / "first 10 → next 10" rewrite as the Pro
# pair), so the two free onboarding emails cannot drift. Parallel version
# lines let PostHog slice free welcome / welcome-back renders from the
# free weekly and from the Pro onboarding pair.
#
# Revision history (most recent first):
#   free-welcome-v1.0 (2026-06-07) — initial ship. Free welcome hero
#       ("Welcome to Pulpo", plain — not "Pulpo Pro") on the free-general
#       body.
#   free-welcome-back-v1.0 (2026-06-07) — initial ship. The free welcome
#       with the "Welcome back" / "next 10" rewrite.
#   free-welcome-v1.2 / free-welcome-back-v1.2 (2026-07-05) — inherit the
#       v5.0 Your Pulpo category localization (P0-4). Both carry Your Pulpo.
FREE_WELCOME_TEMPLATE_VERSION = "free-welcome-v1.3-2026-07-05"
FREE_WELCOME_LAST_UPDATED = "2026-07-05"
FREE_WELCOME_BACK_TEMPLATE_VERSION = "free-welcome-back-v1.3-2026-07-05"
FREE_WELCOME_BACK_LAST_UPDATED = "2026-07-05"


# LEARNING: hex literals live here on purpose. The :root { --paper: … }
# block below also defines CSS vars for clients that support them, but
# the source-of-truth values are hex because Outlook desktop + parts of
# Yahoo strip var() from inline styles. The drift risk vs.
# web/app/styles/tokens.css is mitigated by TEMPLATE_VERSION above —
# bump it when these literals are touched.
CSS = """
:root {
  --paper:        #F4EFE6;
  --paper-2:      #F8F4EC;
  --paper-3:      #E8DFC6;
  --white:        #FFFFFF;
  --ink:          #1A1916;
  --ink-2:        #5A5650;
  --ink-3:        #888780;
  --line:         rgba(0, 0, 0, 0.08);
  --line-2:       rgba(0, 0, 0, 0.14);
  --forest:       #1F3D31;
  --forest-mid:   #3D6450;
  --sage:         #DDE9DC;
  --sage-strong:  #C9DEC6;
  --clay:         #B8643C;
  --clay-deep:    #7A3D1F;
  --navy:         #1E2A3A;
  --button-dark:  #18211C;
  --button-text:  #F4EFE6;
  --burgundy:     #6B2C2C;
  --burgundy-bg:  #F5E3E0;
  --font-display: "Instrument Serif", "Iowan Old Style", Georgia, "Times New Roman", serif;
  --font-sans:    "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
}
body { margin: 0; padding: 0; background: var(--paper); color: var(--ink); font-family: var(--font-sans); -webkit-font-smoothing: antialiased; }
a { color: var(--clay); text-decoration: none; }
a:hover { text-decoration: underline; }
img { display: block; max-width: 100%; height: auto; border: 0; }
table { border-collapse: collapse; }
.wrap   { width: 100%; background: var(--paper); padding: 0; }
.frame  { width: 100%; max-width: 680px; margin: 0 auto; background: var(--white); border: 1px solid var(--line); }
.pad    { padding: 24px 36px; }
.pad-md { padding: 18px 36px; }
.pad-sm { padding: 12px 36px; }
.display { font-family: var(--font-display); font-weight: 400; letter-spacing: -0.01em; }
.sans    { font-family: var(--font-sans); }
.ink     { color: var(--ink); }
.ink-2   { color: var(--ink-2); }
.muted   { color: var(--ink-3); }
.forest  { color: var(--forest); }
.clay    { color: var(--clay); }
.rule        { border: 0; border-top: 1px solid var(--line); margin: 0; }
.rule-strong { border: 0; border-top: 1px solid var(--ink); margin: 0; }
.eyebrow {
  font-family: var(--font-sans);
  font-size: 12px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--forest);
  font-weight: 600;
}
.eyebrow.clay { color: var(--clay); }
.eyebrow.muted { color: var(--ink-3); }
.h-hero  { font-family: var(--font-display); font-size: 60px; line-height: 1.02; letter-spacing: -0.015em; font-weight: 400; margin: 8px 0 10px; color: var(--ink); }
.h1      { font-family: var(--font-display); font-size: 40px; line-height: 1.08; letter-spacing: -0.012em; font-weight: 400; margin: 8px 0 6px; color: var(--ink); }
.h2      { font-family: var(--font-display); font-size: 26px; line-height: 1.14; letter-spacing: -0.01em; font-weight: 400; margin: 10px 0 4px; color: var(--ink); }
.h3      { font-family: var(--font-display); font-size: 22px; line-height: 1.18; letter-spacing: -0.005em; font-weight: 400; margin: 6px 0 2px; color: var(--ink); }
.lede    { font-family: var(--font-sans); font-size: 18px; line-height: 1.5; color: var(--ink); font-weight: 400; }
.body    { font-family: var(--font-sans); font-size: 15px; line-height: 1.65; color: var(--ink); }
.body-2  { font-family: var(--font-sans); font-size: 14px; line-height: 1.6; color: var(--ink-2); }
.body em, .body-2 em, .lede em { font-style: normal; color: inherit; }
.small   { font-family: var(--font-sans); font-size: 12.5px; line-height: 1.55; color: var(--ink-3); }
.meta    { font-family: var(--font-sans); font-size: 11px; letter-spacing: 0.06em; color: var(--forest); text-transform: uppercase; }
.price       { font-family: var(--font-display); font-size: 30px; line-height: 1; font-weight: 400; color: var(--ink); letter-spacing: -0.01em; }
.price-2     { font-family: var(--font-display); font-size: 22px; line-height: 1; font-weight: 400; color: var(--ink); letter-spacing: -0.01em; }
.price-note  { font-family: var(--font-sans); font-size: 12.5px; color: var(--ink-3); }
.pill {
  display: inline-block;
  font-family: var(--font-sans);
  font-size: 10.5px;
  font-weight: 500;
  letter-spacing: 0.10em;
  text-transform: uppercase;
  padding: 5px 9px;
  background: var(--paper-3);
  color: var(--ink-2);
  margin: 0 5px 6px 0;
  border-radius: 999px;
}
.pill-forest  { background: var(--sage); color: var(--forest); }
.pill-clay    { background: var(--burgundy-bg); color: var(--clay-deep); }
.pill-filter  { background: transparent; color: var(--forest); border: 1px solid var(--forest); }
.why-block {
  margin: 18px 0 0;
  padding: 16px 18px 18px;
  background: var(--paper-2);
  border-radius: 6px;
}
.why-label {
  font-family: var(--font-sans);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  color: var(--clay);
  margin: 0 0 10px;
}
.why-list { list-style: none; margin: 0; padding: 0; }
.why-list li {
  font-family: var(--font-sans);
  font-size: 14.5px;
  line-height: 1.5;
  color: var(--ink);
  padding: 4px 0 4px 22px;
  position: relative;
}
.why-list li:before {
  content: "\\2713";
  position: absolute;
  left: 0;
  top: 4px;
  color: var(--forest);
  font-weight: 700;
}
.paywall-banner { background: var(--forest); color: var(--paper); padding: 28px 32px; margin: 16px 0; border-radius: 6px; }
.paywall-banner .eyebrow { color: var(--sage); }
.paywall-banner .h2 { color: var(--paper); }
.paywall-banner .body { color: var(--paper-3); }
.paywall-banner .cta { background: var(--clay); color: var(--paper) !important; }
.cta {
  display: inline-block;
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.04em;
  padding: 13px 22px;
  background: var(--button-dark);
  color: var(--button-text) !important;
  border-radius: 999px;
}
.cta:hover { background: var(--forest); text-decoration: none; }
.cta-ghost {
  display: inline-block;
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 500;
  letter-spacing: 0.04em;
  padding: 12px 20px;
  background: transparent;
  color: var(--ink) !important;
  border: 1px solid var(--ink);
  border-radius: 999px;
}
.cta-ghost:hover { background: var(--ink); color: var(--paper) !important; text-decoration: none; }
.footer-strip { background: var(--paper-2); color: var(--ink-2); border-top: 1px solid var(--line); }
.footer-strip .small { color: var(--ink-3); }
.footer-strip a { color: var(--forest); }
@media (max-width: 480px) {
  .pad, .pad-md, .pad-sm { padding-left: 20px; padding-right: 20px; }
  .pad    { padding-top: 18px; padding-bottom: 18px; }
  .pad-md { padding-top: 14px; padding-bottom: 14px; }
  .pad-sm { padding-top: 10px; padding-bottom: 10px; }
  .h-hero { font-size: 38px; }
  .h1     { font-size: 28px; }
  .h2     { font-size: 21px; }
  .h3     { font-size: 20px; }
  .body, .body-2 { font-size: 16px; line-height: 1.6; }
  .lede   { font-size: 16.5px; line-height: 1.55; }
  .price  { font-size: 24px; }
  .price-2 { font-size: 19px; }
  .cta, .cta-ghost { padding: 14px 22px; font-size: 14px; }
}
"""


def site_root_from_issue(issue: Issue) -> str:
    """Extract https://pulpo.club (or whatever PULPO_SITE_ROOT points at)
    from any of the absolute URLs already on the Issue. Avoids re-reading
    the env var here — build_issue.py already resolved it once.

    `settings_url` is the safest anchor because `/account` is a stable
    SPA route (the unsubscribe URL is `/api/unsubscribe?...` post-2026-05-29,
    so splitting on "/unsubscribe" would leave a stray "/api" suffix and
    produce `https://pulpo.club/api/saved` etc. for the "Your Pulpo" links).
    """
    settings_part = (issue.settings_url or "").split("/account", 1)[0]
    if settings_part:
        return settings_part.rstrip("/") or "https://pulpo.club"
    unsub_part = (issue.unsubscribe_url or "").split("/api/unsubscribe", 1)[0]
    if unsub_part:
        return unsub_part.rstrip("/") or "https://pulpo.club"
    return "https://pulpo.club"


__all__ = [
    "TEMPLATE_VERSION",
    "LAST_UPDATED",
    "WELCOME_TEMPLATE_VERSION",
    "WELCOME_LAST_UPDATED",
    "WELCOME_BACK_TEMPLATE_VERSION",
    "WELCOME_BACK_LAST_UPDATED",
    "FREE_GENERAL_TEMPLATE_VERSION",
    "FREE_GENERAL_LAST_UPDATED",
    "FREE_WELCOME_TEMPLATE_VERSION",
    "FREE_WELCOME_LAST_UPDATED",
    "FREE_WELCOME_BACK_TEMPLATE_VERSION",
    "FREE_WELCOME_BACK_LAST_UPDATED",
    "CSS",
    "escape",
    "site_root_from_issue",
]
