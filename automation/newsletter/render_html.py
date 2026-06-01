"""Issue → HTML string.

Mirrors the structure of newsletter-drafts/pulpo-issue-01-may-18-2026.html
faithfully. Tokens are copy-pasted from the draft (which itself mirrors
web/app/styles/tokens.css) — keeping the design system as a single visual
source of truth across web + email.

No Jinja, no MJML. f-strings + a couple of helpers. The CSS lives once at
the top of the document; we'll keep it that way in PR-NL-2 and switch to
CSS-inlining (premailer-style) in PR-NL-3 when we wire the sender.

Null-safety: every field that the Issue type marks as Optional or
``list[...]`` is checked before render. Rule from CLAUDE.md — one nullable
field crashing the renderer would break the entire batch.
"""

from __future__ import annotations

import re as _re
from html import escape as _e

from . import i18n
from .components._common import (
    TEMPLATE_VERSION as _TEMPLATE_VERSION_SHARED,
    WELCOME_TEMPLATE_VERSION as _WELCOME_TEMPLATE_VERSION_SHARED,
)
from .types import Issue, IssuePick, Locale


def _title_with_widow_guard(escaped_title: str) -> str:
    """Replace the LAST inter-word space with a non-breaking space when
    the trailing word is short enough to widow on mobile wrap.

    Operates on the HTML-escaped title (post `_e(...)`) so the inserted
    `&nbsp;` entity is literal, not re-escaped. Conservative heuristic:
    only fires when the title is 3+ words AND the last word is 5 chars
    or fewer. That covers the real failure modes ("Cerromar El Sunzal Lot",
    "Beachfront Home El Sunzal") without forcing overflow on already-
    short titles like "Casa Lot" or single-word headlines.

    Email clients all render `&nbsp;` correctly; this is the universal
    fallback for the modern `text-wrap: balance` CSS we also stamp inline
    (which only Apple Mail Sonoma+ / Chromium-based webmail honor).
    """
    if not escaped_title:
        return escaped_title
    words = escaped_title.split(" ")
    if len(words) < 3:
        return escaped_title
    if len(words[-1]) > 5:
        return escaped_title
    # Re-join all-but-last with " ", glue the last with &nbsp;
    return " ".join(words[:-1]) + "&nbsp;" + words[-1]


# Bumped whenever the renderer's CSS or layout changes in a way we'd want
# to slice in PostHog (audience tests, regression hunts, A/B pre-bake).
# Stays in sync with docs/newsletter-audit.md. Exposed via
# email.newsletter.sent / email.newsletter.batch_sent telemetry AND a
# <meta name="x-pulpo-template"> tag in the rendered HTML <head>.
#
# v4.2 (2026-05-31): single source of truth lives in
# `automation.newsletter.components._common`. Re-exported here so
# existing imports (`from automation.newsletter.render_html import
# TEMPLATE_VERSION`) keep working — both in tests and in
# `build_issue._emit_favorites_telemetry`.
TEMPLATE_VERSION = _TEMPLATE_VERSION_SHARED
# Welcome carries its own version line so PostHog can slice rendered
# welcomes from weeklies cleanly. Bumped whenever the welcome's hero,
# how-it-works block, cadence note, picks intro, or onboarding cards
# change in a way worth tracking.
WELCOME_TEMPLATE_VERSION = _WELCOME_TEMPLATE_VERSION_SHARED


# LEARNING: hex literals live here on purpose. The :root { --paper: … }
# block below also defines CSS vars for clients that support them, but
# the source-of-truth values are hex because Outlook desktop + parts of
# Yahoo strip var() from inline styles. The drift risk vs.
# web/app/styles/tokens.css is mitigated by TEMPLATE_VERSION above —
# bump it when these literals are touched.
_CSS = """
:root {
  --paper:        #F4EFE6;
  --paper-2:      #F8F4EC;
  /* v3 — bumped from #EEE9DF. The paler tone was so close to --paper that
     chip backgrounds were nearly invisible against the cream page. Hex
     literal lives in `.chip` directly below for the same reason. */
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
  /* Two-font system (v3.2, 2026-05-29). Serif anchors headlines and
     the emphasised emotional centers; sans does everything else.
     Mono (JetBrains Mono) was dropped — three fonts in one email
     reads as typographic noise. Eyebrows, chips, meta strips and
     pills keep their tag-like feel via uppercase + letter-spacing
     in sans, not a monospaced family. */
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
/* `.mono` is kept as a no-op utility class so existing markup using
   `<span class="mono">` still resolves to the document's sans body —
   removing the class hits a wider blast radius for no visible win. */
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
/* v3.2 (2026-05-29) — italics removed from copy. Sebas: "never use
   italics in copy, it adds noise." The v3.1 rule used <em> wrapping
   + clay-deep italic to land the reader's eye on the emotional-center
   sentence; the v3.2 generators no longer emit <em>, so this rule is
   now a no-op safety net (covers any inbound LLM/copy that still
   carries an <em>). Belt-and-suspenders: copy passes through clean
   even if upstream forgets the v3.2 contract. */
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

/* ── chips — supportive context next to a hero pick ─────────────────
   v3 update: backgrounds use hex literals (NOT var()) so Outlook /
   Yahoo, which strip var() from inline + email-stripped CSS, still
   render the right tone. The neutral chip's `#E8DFC6` matches the
   bumped `--paper-3` token — kept hex here so the chip stays visible
   even when the var() is stripped. The `chip-top` variant is the
   forest-on-cream "Top pick" treatment from the v3 mockup. */
.chip {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-family: var(--font-sans);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: #5A5650;
  background: #E8DFC6;
  margin: 0 4px 6px 0;
  line-height: 1.6;
}
.chip-warm { background: #FBE6D8; color: #7A3D1F; font-weight: 600; }
.chip-cool { background: #C9DEC6; color: #1F3D31; font-weight: 600; }
.chip-top  { background: #1F3D31; color: #F4EFE6; font-weight: 600; }
/* "Why we picked it" — three plain-English bullets per hero pick.
   Replaces the v2.x rank-score callout (value 100 / momentum 50) that
   exposed analyst-y internals. Each bullet maps 1:1 to a real Listing
   field; the green check matches the "verified fact" feel. */
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
  content: "✓";
  position: absolute;
  left: 0;
  top: 4px;
  color: var(--forest);
  font-weight: 700;
}
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
/* v3: shortlist entries render as stacked .sl-card divs (no inner
   <table>). The mockup's per-row "For someone who *…*" frame line is
   `.sl-why` — italic clause styled clay-deep via the shared
   `.body em` rule. */
.sl-card {
  margin: 0 0 14px;
  padding: 14px 16px;
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: 6px;
}
.sl-card .sl-photo { margin: 0 0 12px; }
.sl-card .sl-photo img { border-radius: 4px; }
.sl-card .sl-meta {
  font-family: var(--font-sans);
  font-size: 11px;
  letter-spacing: 0.04em;
  color: var(--ink-3);
  margin: 4px 0 4px;
}
.sl-card .sl-why {
  font-family: var(--font-display);
  font-size: 15.5px;
  line-height: 1.45;
  color: var(--ink-2);
  margin: 8px 0 0;
}
.sl-card .sl-why em { font-style: normal; color: inherit; }  /* v3.2 — italics removed from copy */
.meta-row { font-family: var(--font-sans); font-size: 13.5px; line-height: 1.55; color: var(--ink-2); }
.callout { margin: 14px 0 0; padding: 0; background: none; }
.callout .label { font-family: var(--font-sans); font-size: 11px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--forest); margin: 0 0 4px; }
.callout .body  { margin: 0; font-size: 14.5px; line-height: 1.55; color: var(--ink); }
.callout + .callout { margin-top: 12px; }

/* ── Favorites section ────────────────────────────────────────────
   "Your saved listings — what changed this week." Sits between the
   welcome lede and the market context (highest-attention slot in the
   issue). Renderer only emits the section when Issue.favorites is
   non-empty; an empty list collapses to a no-op.

   Email-safe layout: each card is a 2-column <table>, NOT the flex
   layout the mockup at web/newsletter-with-saves-mockup.html uses
   for browser preview. Flex doesn't survive Outlook / older Gmail. */
.saves-wrap { background: var(--paper-2); border-top: 1px solid var(--line); }
.saves-pad  { padding: 24px 36px 22px; }
.saves-eyebrow {
  font-family: var(--font-sans);
  font-size: 11.5px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--forest);
  font-weight: 600;
  margin: 0 0 4px;
}
.saves-h2 {
  font-family: var(--font-display);
  font-size: 26px;
  line-height: 1.18;
  color: var(--ink);
  margin: 0 0 4px;
}
.saves-summary {
  font-family: var(--font-sans);
  font-size: 14.5px;
  line-height: 1.55;
  color: var(--ink-2);
  margin: 4px 0 16px;
}
.save-card {
  background: var(--white);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px 14px;
  margin: 0 0 10px;
}
.save-card-table { width: 100%; border-collapse: collapse; }
.save-thumb-cell {
  width: 96px;
  vertical-align: top;
  padding-right: 14px;
}
.save-thumb-cell img {
  width: 96px;
  height: 84px;
  border-radius: 6px;
  display: block;
  object-fit: cover;
}
.save-thumb-fallback {
  width: 96px;
  height: 84px;
  border-radius: 6px;
  background: var(--paper-3);
  display: block;
}
.save-body-cell { vertical-align: top; }
.change-chip {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  font-family: var(--font-sans);
  font-size: 11px;
  letter-spacing: 0.04em;
  font-weight: 600;
  margin: 0 0 6px;
}
.change-chip-warm  { background: #FBE6D8; color: #7A3D1F; }     /* price drop */
.change-chip-calm  { background: #E8DFC6; color: #5A5650; }     /* no change  */
.change-chip-up    { background: #EDE7DB; color: #5A5650; }     /* price up   */
.save-title {
  font-family: var(--font-display);
  font-size: 18px;
  line-height: 1.22;
  color: var(--ink);
  margin: 2px 0 4px;
}
.save-meta {
  font-family: var(--font-sans);
  font-size: 11.5px;
  letter-spacing: 0.04em;
  color: var(--ink-3);
  text-transform: uppercase;
  margin: 0 0 4px;
}
.save-price {
  font-family: var(--font-display);
  font-size: 18px;
  color: var(--ink);
  margin: 0 0 6px;
}
.save-price .struck {
  color: var(--burgundy);
  text-decoration: line-through;
  font-size: 13px;
  margin-left: 6px;
  font-family: var(--font-sans);
}
.save-cta {
  font-family: var(--font-sans);
  font-size: 13px;
  font-weight: 600;
  color: var(--ink);
  text-decoration: underline;
  text-underline-offset: 3px;
}
.saves-footer {
  font-family: var(--font-sans);
  font-size: 12.5px;
  color: var(--ink-3);
  margin: 12px 0 0;
}
.saves-footer a { color: var(--clay); font-weight: 500; text-decoration: none; }
.saves-footer a:hover { text-decoration: underline; }

.paywall-banner { background: var(--forest); color: var(--paper); padding: 28px 32px; margin: 16px 0; border-radius: 6px; }
.paywall-banner .eyebrow { color: var(--sage); }
.paywall-banner .h2 { color: var(--paper); }
.paywall-banner .body { color: var(--paper-3); }
.paywall-banner .cta { background: var(--clay); color: var(--paper) !important; }
/* v2.2: lightened footer. The forest-on-cream "stamp" at the end made
   the email feel bottom-heavy. Cream-on-cream lets the issue end
   instead of getting branded at the bottom. The horizontal rule
   above the footer is now the only visual separator from content. */
.footer-strip { background: var(--paper-2); color: var(--ink-2); border-top: 1px solid var(--line); }
.footer-strip .small { color: var(--ink-3); }
.footer-strip a { color: var(--forest); }
/* PR-NL-8 — Your Pulpo dark panel (matches v2.4 mockup). Sits between
   next-issue and footer. Dark surface signals "this is product, not
   editorial" so the reader's eye reads it as a control panel, not as
   another picks block. */
.yp-panel {
  background: var(--ink);
  color: var(--paper);
  padding: 36px 48px;
}
.yp-eyebrow {
  font-family: var(--font-sans);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--paper);
  opacity: 0.55;
}
.yp-title {
  color: var(--paper);
  margin: 8px 0 24px;
  font-family: var(--font-display);
  font-size: 28px;
  line-height: 1.15;
}
.yp-table { width: 100%; border-collapse: collapse; }
.yp-table td { padding: 18px 0; border-top: 1px solid rgba(255, 255, 255, 0.12); color: var(--paper); vertical-align: middle; }
.yp-row-label { font-family: var(--font-display); font-size: 20px; line-height: 1.3; color: var(--paper); }
.yp-row-cta { text-align: right; padding-left: 16px; white-space: nowrap; }
.yp-row-cta a {
  color: var(--paper) !important;
  font-family: var(--font-sans);
  font-weight: 600;
  font-size: 13px;
  text-decoration: underline;
  text-underline-offset: 4px;
}
.yp-row-cta a:hover { color: var(--clay) !important; }
/* LEARNING: this file uses max-width despite CLAUDE.md mandating
   min-width in web/app/*. Emails are an inverse world — clients without
   media-query support (Outlook 2007+, parts of Yahoo) must still receive
   the baseline, so the baseline is desktop-safe and this query upgrades
   for narrow widths. 480px matches --bp-sm in tokens.css. */
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
  /* Footer links get vertical tap targets on narrow widths so the three
     options no longer collide at 320px. The &middot; separators stay so
     legacy / no-CSS clients still get the comma-style read. */
  .footer-strip a { display: inline-block; padding: 6px 4px; }
}
"""


def _pills_html(pills: list[str]) -> str:
    if not pills:
        return ""
    return "".join(f'<span class="pill">{_e(p)}</span>' for p in pills)


def _chips_html(pick: IssuePick) -> str:
    """Render Chip objects (warm/cool/neutral/top) into the email.

    v3: the "★ Top pick this week" chip — emitted by
    build_issue._chips_for_listing with `kind=cool` for the top N — is
    promoted visually to the forest-on-cream `chip-top` treatment when
    its label starts with the star glyph. The detection is label-based
    so the underlying Chip type stays at three kinds (the mockup's
    fourth variant is purely a render-side choice).

    Falls through to the legacy `pills` list when no chips are set so
    older fixtures that haven't migrated still render something useful.
    """
    chips = getattr(pick, "chips", None) or []
    if not chips:
        return _pills_html(pick.pills)
    out: list[str] = []
    for c in chips:
        klass = "chip"
        kind = getattr(c, "kind", "neutral")
        label = c.label or ""
        if label.startswith("★"):
            klass += " chip-top"
        elif kind == "warm":
            klass += " chip-warm"
        elif kind == "cool":
            klass += " chip-cool"
        out.append(f'<span class="{klass}">{_e(label)}</span>')
    return "".join(out)


def _callouts_html(callouts: list[dict]) -> str:
    """Render the structured callouts under a hero pick.

    v3: the "Why Pulpo ranked it" callout — which surfaced analyst-y
    rank-reasons strings ("value 100 · location 100 · momentum 50") —
    is dropped here. The plain-English "Why we picked it" `.why-block`
    above the callouts covers the same job in language a reader can
    actually use. "Reasons to buy" and "The price story" stay.
    """
    if not callouts:
        return ""
    out: list[str] = []
    for c in callouts:
        label_raw = (c.get("label") or "").strip()
        body_raw = (c.get("body") or "").strip()
        if not body_raw:
            continue
        if "Why Pulpo ranked it" in label_raw or "Por qué Pulpo lo clasifica" in label_raw:
            continue
        out.append(
            f'<div class="callout"><div class="label">{_e(label_raw)}</div>'
            f'<div class="body">{_e(body_raw)}</div></div>'
        )
    return "".join(out)


def _why_block_html(pick: IssuePick, locale: Locale) -> str:
    """Render the v3 "Why we picked it" `<ul>` of plain-English bullets.

    Empty list → no block rendered (paywalled picks and any pick whose
    `deterministic_why_for_pick` falls through every branch). Each
    bullet is escaped — they're plain text out of commentary.py, no
    embedded markup.

    Email-safe styling: the `<style>` block in <head> styles `.why-block`
    via CSS vars + `:before` for the ✓ glyph, but Gmail / Outlook / Yahoo
    strip both — the cream square + checkmarks were invisible in every
    inbox we ship to. So every visual the user must see (background
    shading, ✓ glyph, clay label color) is duplicated as inline styles
    + literal text on this block. Inline always wins over <style>, so
    rich clients (Apple Mail / iOS Mail) still get the same look from
    the inline rules. Class names are preserved so the existing
    test_render.py assertions and any future `:has(.why-block)` CSS
    keep working.
    """
    bullets = getattr(pick, "why_bullets", None) or []
    if not bullets:
        return ""
    label = i18n.t("pick.why_label", locale)
    # Inline ✓ + bullet text. No `position:absolute` — Outlook's Word
    # engine is unreliable with it; a single space + non-breaking space
    # is robust enough for the hanging-indent feel without absolute
    # positioning, and `vertical-align: top` keeps the check aligned
    # with the first line of multi-line bullets.
    li_style = (
        "padding:6px 0;font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;"
        "font-size:14.5px;line-height:1.5;color:#1A1916;"
    )
    check_style = (
        "color:#1F3D31;font-weight:700;margin-right:10px;display:inline-block;"
    )
    items = "".join(
        f'<li style="{li_style}">'
        f'<span style="{check_style}">&#10003;</span>{_e(b)}'
        "</li>"
        for b in bullets
    )
    block_style = (
        "margin:18px 0 0;padding:16px 18px 18px;background:#F8F4EC;border-radius:6px;"
    )
    label_style = (
        "font-family:'Inter',-apple-system,BlinkMacSystemFont,sans-serif;"
        "font-size:11px;font-weight:600;letter-spacing:0.12em;"
        "text-transform:uppercase;color:#B8643C;margin:0 0 10px;"
    )
    ul_style = "list-style:none;margin:0;padding:0;"
    return (
        f'<div class="why-block" style="{block_style}">'
        f'<p class="why-label" style="{label_style}">{_e(label)}</p>'
        f'<ul class="why-list" style="{ul_style}">{items}</ul>'
        f"</div>"
    )


def _meta_row_html(rows: list[tuple[str, str]]) -> str:
    """Single-line magazine-spec strip replacing the old keytable grid.

    The old `<table class="keytable">` jammed four key/value pairs into one
    row with no visual separation — rendered as `$/m² $47 vs zone -78% per
    m² vs zone Beach 5.7 km Airport 36 km Listed New this week`. The
    values already carry enough context to stand alone (e.g. "5.7 km to
    beach"), so the labels are redundant.

    New rendering: a flat inline strip separated by `·`. The `vs zone` row
    is dropped here — the "price story" callout already covers that
    comp-vs-market context, so duplicating it in the meta row wastes ink.
    The `$/m²` label is preserved by concatenating the unit into the value
    ("$47/m²") because "$47" alone doesn't read as price-per-square-meter.
    """
    if not rows:
        return ""
    cells: list[str] = []
    for k, v in rows:
        k_clean = (k or "").strip()
        v_clean = (v or "").strip()
        if not v_clean:
            continue
        # Skip the comp-vs-zone datapoint — already covered by the
        # "price story" callout. Match case-insensitively + accept both
        # the EN ("vs zone") and ES ("vs zona") spellings.
        if k_clean.lower() in ("vs zone", "vs zona"):
            continue
        # Concatenate the price-per-m² unit into the value so it reads as
        # "$47/m²" rather than a bare "$47" with a separate label.
        if k_clean in ("$/m²", "$/m2") and "/m" not in v_clean:
            cells.append(f"{_e(v_clean)}/m²")
        else:
            cells.append(_e(v_clean))
    if not cells:
        return ""
    return (
        '<p class="meta-row" style="margin: 12px 0 0;">'
        + " &middot; ".join(cells)
        + "</p>"
    )


def _photo_html(pick: IssuePick) -> str:
    if not pick.photo_url:
        return ""
    alt = pick.title or "Pulpo listing photo"
    return f'<img src="{_e(pick.photo_url)}" alt="{_e(alt)}" width="680" />'


def _photo_html_short(pick: IssuePick) -> str:
    if not pick.photo_url:
        return ""
    alt = pick.title or "Pulpo listing photo"
    return f'<img src="{_e(pick.photo_url)}" alt="{_e(alt)}" width="100%" />'


def _new_pill(pick: IssuePick, locale: Locale) -> str:
    if pick.is_repriced:
        return f'<span class="pill pill-clay">{_e(i18n.t("pick.repriced_pill", locale))}</span>'
    if pick.is_new_this_fortnight:
        return f'<span class="pill pill-forest">{_e(i18n.t("pick.new_pill", locale))}</span>'
    return ""


def _cta_for_pick(pick: IssuePick, locale: Locale, paywall_url: str, ghost: bool = False) -> str:
    """Single "See on Pulpo" / "Unlock" CTA. Used by the short-pick rows
    where space is tight. Prefer the canonical `pulpo_url` (PR-NL-5);
    fall back to the external `listing_url` so older fixtures still
    render something useful."""
    klass = "cta-ghost" if ghost else "cta"
    if pick.paywalled:
        label = i18n.t("pick.cta_locked", locale)
        href = paywall_url + f"&pick={pick.rank}"
        return f'<a class="{klass}" href="{_e(href)}">{_e(label)}</a>'
    # PR-NL-5: CTA points at pulpo.club, not the external source. Falls
    # back to listing_url for older fixtures that haven't set pulpo_url.
    label = i18n.t("pick.cta_open", locale)
    href = getattr(pick, "pulpo_url", "") or pick.listing_url
    return f'<a class="{klass}" href="{_e(href)}">{_e(label)}</a>'


def _ctas_for_hero_pick(pick: IssuePick, locale: Locale, paywall_url: str) -> str:
    """Dual CTA for the v2.4 hero layout: solid "See on Pulpo" + ghost
    "♥ Save to favorites".

    Both go into the Pulpo SPA. The save link adds `?save=1` which
    PR-NL-8 will use to auto-trigger the save on mount; until then the
    listing page ignores the unknown param and the reader clicks the
    heart manually (graceful degrade). Paywalled picks keep the single
    locked CTA — no save button on a teaser the reader can't open."""
    if pick.paywalled:
        return _cta_for_pick(pick, locale, paywall_url)
    see_label = i18n.t("pick.cta_open", locale)
    save_label = i18n.t("pick.cta_save", locale)
    see_href = getattr(pick, "pulpo_url", "") or pick.listing_url
    save_href = getattr(pick, "save_url", "") or see_href
    # Spaced with non-breaking gap so the two CTAs sit side-by-side in
    # email clients that respect inline whitespace.
    return (
        f'<a class="cta" href="{_e(see_href)}">{_e(see_label)}</a>'
        f'&nbsp;&nbsp;'
        f'<a class="cta-ghost" href="{_e(save_href)}">♥ {_e(save_label)}</a>'
    )


def _rich_pick(pick: IssuePick, *, locale: Locale, paywall_url: str) -> str:
    """Hero pick render. Bumped to use:
      • PR-NL-5 chips (warm/cool/neutral) instead of the older pill row
        (legacy pills still survive via `_chips_html` fallback)
      • Dual CTA (See on Pulpo + Save to favorites)
    The structure stays IDENTICAL to the previous layout — same photo
    on top, same headline/meta/price stack, same callouts + keytable
    below the body — so existing snapshot tests only need the CTA +
    chip row diff'd, not a full template rewrite."""
    top_label = i18n.t("pick.top_label", locale, rank=pick.rank)
    # The top-of-pick row: "TOP PICK · 01" always-on, plus the repriced/
    # new signal pill if relevant, plus the PR-NL-5 chips driven by real
    # Listing fields. Chips replace v2.2's `pills[:1]` cap — they're
    # already trimmed to ISSUE_CHIPS_PER_PICK in build_issue.py and have
    # color coding (warm/cool/neutral) the old pill row couldn't carry.
    chips_html = _chips_html(pick)
    pills_html = (
        f'<span class="pill pill-forest">{_e(top_label)}</span>'
        + _new_pill(pick, locale)
        + chips_html
    )

    callouts_html = "" if pick.paywalled else _callouts_html(pick.callouts)
    meta_row_html = "" if pick.paywalled else _meta_row_html(pick.keytable)
    why_html = "" if pick.paywalled else _why_block_html(pick, locale)
    # PR-NL-6: prefer story_html (AI or deterministic — see
    # build_issue._llm_or_deterministic_story). Falls back to the
    # listing's enriched blurb when story_html is empty (short picks /
    # legacy fixtures). story_html may contain a single <em>...</em>
    # span around the emotional center, which the CSS .body em style
    # picks up and lands in clay-deep italic — DON'T html-escape it.
    if pick.paywalled:
        paywall_blurb = i18n.t("pick.paywall_blurb", locale)
        blurb_html = (
            f'<p class="body" style="margin-top: 14px; color: var(--ink-2);">{_e(paywall_blurb)}</p>'
        )
    elif getattr(pick, "story_html", ""):
        # _e() would escape the <em>; we trust story_html because:
        #   1. LLM output is sanitized in llm_story._sanitize_paragraph
        #   2. deterministic_story_for_pick builds only known-good HTML
        # If a future story source needs untrusted content, sanitize it
        # at the boundary instead of re-escaping here.
        blurb_html = f'<p class="body" style="margin-top: 14px;">{pick.story_html}</p>'
    elif pick.blurb:
        blurb_html = f'<p class="body" style="margin-top: 14px;">{_e(pick.blurb)}</p>'
    else:
        blurb_html = ""

    price_note_html = (
        f'<span class="price-note"> · {_e(pick.price_note)}</span>' if pick.price_note else ""
    )

    # Skip the photo row entirely when there's no eligible hero image —
    # build_issue._absolute_photo returns "" for listings where the
    # source could surface a broker logo (REMAX, Citymax, etc.). Dropping
    # the row (instead of rendering an empty <tr>) avoids a stray 12px
    # gap above the headline.
    photo_row = (
        f'<tr><td style="padding: 12px 0 0 0;">{_photo_html(pick)}</td></tr>'
        if pick.photo_url
        else ""
    )
    return f"""
    {photo_row}
    <tr><td class="pad" style="padding-top: 16px;">
      <div>{pills_html}</div>
      <h2 class="h1">{_e(pick.title)}</h2>
      <div class="meta" style="margin: 6px 0 16px;">{_e(pick.location_line)}</div>
      <div class="price">{_e(pick.price_text)}{price_note_html}</div>
      {meta_row_html}
      {blurb_html}
      {why_html}
      {callouts_html}
      <p style="margin-top: 16px;">{_ctas_for_hero_pick(pick, locale, paywall_url)}</p>
    </td></tr>
    <tr><td class="pad-sm"><hr class="rule" /></td></tr>
    """


def _short_pick(pick: IssuePick, *, locale: Locale, paywall_url: str) -> str:
    """v3 shortlist entry — stacked card layout, no inner <table>.

    The v2 layout used a 2-column inner `<table>` to put a tiny photo
    next to the headline + price + ghost CTA. That was the table the
    user called out — even though a `role="presentation"` table doesn't
    render visually as a grid, the surrounding chrome (cell padding,
    column widths) read as one. v3 stacks everything vertically inside
    a `.sl-card` div and surfaces a "For someone who *…*" frame line so
    the reader knows who the listing suits before they decide to click.
    """
    # Shortlist gets at most 1 editorial tag (matches rich-pick cap).
    pills_html = _new_pill(pick, locale) + _pills_html(pick.pills[:1])
    price_note_html = (
        f'<span class="price-note"> · {_e(pick.price_note)}</span>' if pick.price_note else ""
    )

    # The "For someone who *wants surf-city land cheap*" frame line.
    # `shortlist_frame_html` contains a single trusted `<em>...</em>`
    # span built by commentary.deterministic_shortlist_frame — DON'T
    # html-escape it. Falls back to the listing blurb when the frame is
    # empty (paywalled picks / listings without enough data) so the row
    # still says something useful.
    frame_html_raw = getattr(pick, "shortlist_frame_html", "") or ""
    if pick.paywalled:
        frame_html = (
            f'<p class="sl-why">{_e(i18n.t("pick.paywall_blurb", locale))}</p>'
        )
    elif frame_html_raw:
        frame_html = f'<p class="sl-why">{frame_html_raw}</p>'
    elif pick.blurb:
        frame_html = f'<p class="sl-why">{_e(pick.blurb)}</p>'
    else:
        frame_html = ""

    photo = _photo_html_short(pick)
    photo_html = (
        f'<div class="sl-photo">{photo}</div>' if photo else ""
    )

    return f"""
    <tr><td class="pad-md">
      <div class="sl-card">
        {photo_html}
        <h3 class="h3" style="margin-top: 0;">{_e(pick.title)}</h3>
        <div class="sl-meta">{_e(pick.location_line)}</div>
        <div class="price-2" style="margin: 4px 0 6px;">{_e(pick.price_text)}{price_note_html}</div>
        {('<div>' + pills_html + '</div>') if pills_html else ''}
        {frame_html}
        <p style="margin-top: 10px;">{_cta_for_pick(pick, locale, paywall_url, ghost=True)}</p>
      </div>
    </td></tr>
    """


def _filter_chips_html(chips: list[str]) -> str:
    if not chips:
        return ""
    out = "".join(f'<span class="pill pill-filter">{_e(c)}</span>' for c in chips)
    return f'<div style="margin-top: 16px;">{out}</div>'


def _paywall_banner_html(issue: Issue) -> str:
    if not issue.paywall_banner:
        return ""
    eb = i18n.t("paywall.eyebrow", issue.locale)
    hl = i18n.t("paywall.headline", issue.locale)
    body = i18n.t("paywall.body", issue.locale)
    cta = i18n.t("paywall.cta", issue.locale)
    return f"""
    <tr><td class="pad" style="padding-top: 16px; padding-bottom: 0;">
      <div class="paywall-banner">
        <div class="eyebrow">{_e(eb)}</div>
        <h2 class="h2">{_e(hl)}</h2>
        <p class="body" style="margin-top: 12px;">{_e(body)}</p>
        <p style="margin-top: 16px;"><a class="cta" href="{_e(issue.paywall_target_url)}">{_e(cta)}</a></p>
      </div>
    </td></tr>
    """


def _skip_block_html(issue: Issue) -> str:
    sp = issue.skip_pick
    if not sp:
        return ""
    locale = issue.locale
    eb = i18n.t("skip.eyebrow", locale)
    headline = issue.commentary.skip_headline or sp.title
    blurb = issue.commentary.skip_blurb or sp.blurb
    return f"""
    <tr><td class="pad" style="padding-top: 16px;">
      <hr class="rule" />
      <div style="margin-top: 12px;">
        <div class="eyebrow clay">{_e(eb)}</div>
        <h2 class="h1">{_e(headline)}</h2>
        <div class="meta" style="margin: 4px 0 12px; color: var(--clay);">{_e(sp.price_text)} · {_e(sp.location_line)}</div>
        <p class="body">{_e(blurb)}</p>
      </div>
    </td></tr>
    """


# Matches a full anchor: `<a href="…">…</a>`. Captures the href and the
# inner text. Used for the post-processing pass over LLM /
# deterministic market-context paragraphs.
_ANCHOR_RE = _re.compile(
    r'<a\s+href="([^"]*)"[^>]*>(.*?)</a>',
    flags=_re.IGNORECASE | _re.DOTALL,
)
_PICK_URL_RE = _re.compile(r"^PICK_URL_(\d+)$")


def _hydrate_pick_urls(paragraph: str, issue: Issue) -> str:
    """Resolve `PICK_URL_<N>` placeholders in market-context paragraphs.

    Source paths producing placeholders:
      • `commentary.deterministic_market_note` emits
        `<a href="PICK_URL_3">…</a>` around property phrases.
      • `llm_commentary`'s system prompt instructs DeepSeek to use the
        same convention; the renderer is what makes them real.

    For each `<a href="X">text</a>` we encounter:
      • X is `PICK_URL_<N>` AND N maps to a known pick → emit
        `<a href="<pulpo_url>">text</a>`.
      • X is `PICK_URL_<N>` but N is unknown (LLM hallucinated a rank
        outside the issue) → drop the wrapper, keep `text`.
      • X is anything else (LLM invented a literal URL) → drop the
        wrapper, keep `text`. Defensive guard so the email never ships
        a link to a URL the system didn't authorize.
    """
    # Build rank → pulpo_url lookup once. Includes rich + shortlist
    # picks so the LLM can link into either; paywalled picks excluded
    # because the reader can't open them anyway.
    rank_to_url: dict[int, str] = {}
    for p in list(issue.picks_top) + list(issue.picks_shortlist):
        if p.rank and p.pulpo_url and not p.paywalled:
            rank_to_url[p.rank] = p.pulpo_url

    def _resolve(match: _re.Match) -> str:
        href, text = match.group(1), match.group(2)
        m = _PICK_URL_RE.match(href)
        if not m:
            return text  # invented URL — strip wrapper, keep text
        rank = int(m.group(1))
        url = rank_to_url.get(rank)
        if not url:
            return text  # unknown rank — strip wrapper, keep text
        return f'<a href="{url}">{text}</a>'

    return _ANCHOR_RE.sub(_resolve, paragraph)


def _favorites_html(issue: Issue) -> str:
    """Render the "Your saved listings — what changed this week" section.

    Empty `issue.favorites` → empty string → renderer skips the
    section block entirely (no border, no spacing leak). Cap is
    enforced upstream in compute_favorites.

    Sits between the hero/lede block and market context per the
    mockup at web/newsletter-with-saves-mockup.html — the highest
    attention slot for an existing-engaged user (Pro plan, has
    saved listings before).
    """
    favorites = getattr(issue, "favorites", None) or []
    if not favorites:
        return ""

    locale = issue.locale
    en = locale == "en"

    count = len(favorites)
    eyebrow = (
        "Your favorites · this week" if en
        else "Tus favoritos · esta semana"
    )
    # v4 (2026-05-31): numeric headline per the locked mockup —
    # "3 you're following." not "Three you're following." Spelled-out
    # numerals read editorial in body copy but slow the eye in an H2.
    if count == 1:
        headline = "1 you're following." if en else "1 que seguís."
    else:
        headline = (
            f"{count} you're following." if en
            else f"{count} que seguís."
        )

    summary = _favorites_editorial_summary(favorites, locale)

    cards = "".join(_favorite_card_html(u, locale) for u in favorites)

    site = (issue.settings_url.split("/account")[0] if "/account" in issue.settings_url else "https://pulpo.club")
    ref = f"?ref=newsletter_issue_{issue.issue_number:02d}"
    saved_url = f"{site}/saved{ref}&from=favorites"
    open_all = "Open all favorites" if en else "Abrir todos los favoritos"

    return f"""
    <tr><td class="pad-h" style="padding:16px 24px 16px;background:#F8F4EC;">
      <p class="saves-eyebrow" style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#B8643C;font-weight:600;margin:0 0 4px;">{_e(eyebrow)}</p>
      <h2 class="saves-h2" style="font-family:'Instrument Serif',Georgia,serif;font-size:32px;line-height:1.08;letter-spacing:-0.012em;font-weight:400;margin:0 0 4px;color:#1A1916;">{_e(headline)}</h2>
      <p class="saves-summary" style="font-family:'Instrument Serif',Georgia,serif;font-size:16px;line-height:1.5;color:#1A1916;margin:0 0 14px;max-width:540px;">{summary}</p>
      {cards}
      <p style="margin:14px 0 0;"><a href="{_e(saved_url)}" style="display:inline-block;font-size:13px;font-weight:600;color:#1A1916;border-bottom:1px solid #1A1916;padding-bottom:1px;text-decoration:none;">{_e(open_all)} &rarr;</a></p>
    </td></tr>
    """


def _favorites_count_word(n: int, en: bool) -> str:
    """Editorial numeral for the saves headline. Matches the v3.2
    lede convention (digits read as a stat strip, words as a sentence)."""
    en_words = {2: "Two", 3: "Three", 4: "Four"}
    es_words = {2: "Dos", 3: "Tres", 4: "Cuatro"}
    return (en_words.get(n) or str(n)) if en else (es_words.get(n) or str(n))


def _favorites_summary(favorites: list, locale: str) -> str:
    """Build the qualitative one-line summary above the cards.

    Summary is composed from the actual state counts so it stays
    truthful (no fabricated drama when nothing actually moved).
    v3.3.1: the off_market state was removed; saves missing from
    ranked.json are silently skipped rather than reported as sold,
    so the summary builder no longer has that branch.
    """
    en = locale == "en"
    counts = {"price_dropped": 0, "no_change": 0, "price_up": 0}
    for u in favorites:
        counts[u.state] = counts.get(u.state, 0) + 1

    if en:
        parts: list[str] = []
        if counts["price_dropped"]:
            parts.append(_count_phrase(counts["price_dropped"], "had a price drop", "had price drops", en=True))
        if counts["price_up"]:
            parts.append(_count_phrase(counts["price_up"], "moved up in price", "moved up in price", en=True))
        if counts["no_change"]:
            parts.append(
                _count_phrase(counts["no_change"], "is still where you left it", "are still where you left them", en=True)
            )
        return _join_with_and(parts, "and") + "."
    parts_es: list[str] = []
    if counts["price_dropped"]:
        parts_es.append(_count_phrase(counts["price_dropped"], "bajó de precio", "bajaron de precio", en=False))
    if counts["price_up"]:
        parts_es.append(_count_phrase(counts["price_up"], "subió de precio", "subieron de precio", en=False))
    if counts["no_change"]:
        parts_es.append(_count_phrase(counts["no_change"], "sigue donde la dejaste", "siguen donde las dejaste", en=False))
    return _join_with_and(parts_es, "y") + "."


def _count_phrase(n: int, singular: str, plural: str, *, en: bool) -> str:
    if n == 1:
        return ("One " if en else "Una ") + singular
    word_en = {2: "Two", 3: "Three", 4: "Four"}.get(n, str(n))
    word_es = {2: "Dos", 3: "Tres", 4: "Cuatro"}.get(n, str(n))
    return ((word_en if en else word_es) + " ") + plural


def _join_with_and(parts: list[str], conj: str) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} {conj} {parts[1]}"
    return ", ".join(parts[:-1]) + f", {conj} {parts[-1]}"


def _favorite_card_html(u, locale: str) -> str:
    """Render one card. Layout: 2-column table (thumb 96px + body),
    email-safe. CSS classes carry the visual style; inline `style`
    used only for fallback thumbnail color (variable per state).
    """
    en = locale == "en"

    # Change chip — one per state, kept terse so the card scans fast.
    if u.state == "price_dropped":
        amount = _format_price_compact(u.delta_usd or 0)
        chip_text = (f"&darr; Price dropped {amount} since you saved it" if en
                     else f"&darr; Bajó {amount} desde que la guardaste")
        chip_class = "change-chip change-chip-warm"
    elif u.state == "price_up":
        amount = _format_price_compact(u.delta_usd or 0)
        chip_text = (f"&uarr; Price moved up {amount} since you saved it" if en
                     else f"&uarr; Subió {amount} desde que la guardaste")
        chip_class = "change-chip change-chip-up"
    else:  # no_change
        if u.days_listed is not None:
            chip_text = (f"Still on market &middot; {u.days_listed} day{'s' if u.days_listed != 1 else ''} listed" if en
                         else f"Sigue en el mercado &middot; {u.days_listed} día{'s' if u.days_listed != 1 else ''} listada")
        else:
            chip_text = "Still on market" if en else "Sigue en el mercado"
        chip_class = "change-chip change-chip-calm"

    # Price line — varies by state.
    if u.state == "price_dropped" and u.current_price_usd is not None and u.price_at_save_usd is not None:
        price_line = (
            f'{_format_price_full(u.current_price_usd)}'
            f' <span class="struck">{_format_price_full(u.price_at_save_usd)}</span>'
        )
    elif u.current_price_usd is not None:
        price_line = _format_price_full(u.current_price_usd)
    elif u.price_at_save_usd is not None:
        price_line = _format_price_full(u.price_at_save_usd)
    else:
        price_line = "&mdash;"

    cta_text = "See on Pulpo &rarr;" if en else "Verla en Pulpo &rarr;"

    photo_block = (
        f'<img src="{_e(u.photo_url)}" alt="" />'
        if u.photo_url
        else '<span class="save-thumb-fallback" aria-hidden="true"></span>'
    )

    title_esc = _e(u.title) if u.title else ""
    location_esc = _e(u.location_line) if u.location_line else ""

    return f"""
        <div class="save-card">
          <table class="save-card-table" role="presentation"><tr>
            <td class="save-thumb-cell">{photo_block}</td>
            <td class="save-body-cell">
              <span class="{chip_class}">{chip_text}</span>
              <p class="save-title">{title_esc}</p>
              {f'<p class="save-meta">{location_esc}</p>' if location_esc else ''}
              <p class="save-price">{price_line}</p>
              <a class="save-cta" href="{_e(u.pulpo_url)}">{cta_text}</a>
            </td>
          </tr></table>
        </div>
"""


def _format_price_full(amount: float) -> str:
    return f"${int(round(amount)):,}"


def _format_price_compact(amount: float) -> str:
    """`$1,250` → `$1,250` ; `$25,000` → `$25k` ; `$250,000` → `$250k`.

    The delta chip in the favorites section is tight on width — a
    compact representation reads cleaner than full thousands."""
    n = int(round(abs(amount)))
    if n < 1000:
        return f"${n}"
    if n < 100_000:
        # 1,000–99,999: keep one comma group when the leading digit is
        # ambiguous (e.g. $5k vs $5,400). Fallback to k-form for round.
        if n % 1000 == 0:
            return f"${n // 1000}k"
        return f"${n:,}"
    # 100,000+: always k.
    return f"${n // 1000}k"


def _market_html(issue: Issue) -> str:
    """v4.1 (2026-05-31) market context — numbered editorial mini-blocks.

    Restructure (operator feedback 2026-05-31): the v4.0 form was a
    prose paragraph that read as a wall of text. Now each beat of the
    market story renders as a numbered block: big serif numeral on
    the left (forest green, mockup-locked), bold lead + body on the
    right. Scans like a 1-2-3 checklist while keeping editorial tone.

    Splits each `market_context` string on the `||BLOCK||` sentinel
    emitted by `commentary.deterministic_market_note`. Backwards-
    compatible with LLM commentary which still returns one prose
    paragraph (rendered as a single "01" block).

    Hydrates `<a href="PICK_URL_N">` placeholders to real pulpo_url
    targets via `_hydrate_pick_urls`. Bold `<strong>` tags survive
    untouched.

    Mobile-safe layout: 44px-wide numeral cell + content column. At
    375px viewport (Gmail mobile), content gets ~250px which still
    holds a 12-15 word lead + 1 sentence comfortably.
    """
    paras = issue.commentary.market_context
    if not paras:
        return ""
    locale = issue.locale
    eb = i18n.t("market.eyebrow", locale)
    hl = i18n.t("market.headline", locale)
    decoder = i18n.t("market.decoder", locale)

    # Flatten paragraph entries + the ||BLOCK|| sentinel into one
    # ordered list of editorial blocks.
    blocks: list[str] = []
    for para in paras:
        for chunk in para.split("||BLOCK||"):
            chunk = chunk.strip()
            if chunk:
                blocks.append(chunk)

    block_html_parts: list[str] = []
    for idx, block in enumerate(blocks, start=1):
        hydrated = _hydrate_pick_urls(block, issue)
        is_last = idx == len(blocks)
        block_margin = "0" if is_last else "0 0 18px"
        block_html_parts.append(
            f'<table width="100%" role="presentation" cellpadding="0" cellspacing="0" style="margin:{block_margin};">'
            f'<tr>'
            f'<td width="44" valign="top" style="width:44px;padding:0 12px 0 0;vertical-align:top;">'
            f'<div style="font-family:\'Instrument Serif\',Georgia,serif;font-size:32px;line-height:1;color:#1F3D31;font-weight:400;letter-spacing:-0.02em;">{idx:02d}</div>'
            f'</td>'
            f'<td valign="top" style="vertical-align:top;">'
            f'<p style="font-size:15.5px;line-height:1.6;color:#1A1916;margin:0;">{hydrated}</p>'
            f'</td>'
            f'</tr></table>'
        )
    blocks_html = "".join(block_html_parts)

    return f"""
    <tr><td class="pad-h" style="padding:18px 24px 16px;">
      <div style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#1F3D31;font-weight:600;margin-bottom:6px;">{_e(eb)}</div>
      <h2 style="font-family:'Instrument Serif',Georgia,serif;font-size:30px;line-height:1.08;letter-spacing:-0.012em;font-weight:400;margin:0 0 10px;color:#1A1916;">{_e(hl)}</h2>
      <p style="font-size:13px;line-height:1.55;color:#5A5650;margin:0 0 18px;">{decoder}</p>
      {blocks_html}
    </td></tr>
    """


def _one_number_html(issue: Issue) -> str:
    title = issue.commentary.one_number_title
    body = issue.commentary.one_number_body
    if not title:
        return ""
    eb = i18n.t("one_number.eyebrow", issue.locale)
    body_html = f'<p class="body">{_e(body)}</p>' if body else ""
    return f"""
    <tr><td class="pad" style="padding-top: 16px;">
      <div class="eyebrow">{_e(eb)}</div>
      <h2 class="h1">{_e(title)}</h2>
      {body_html}
    </td></tr>
    """


def _footer_html(issue: Issue) -> str:
    """v4 (2026-05-31) — branded footer matching the locked mockup.

    Layout (top to bottom inside the cream `footer-strip` cell):
      • Small Pulpo octopus mark + lowercase "pulpo" wordmark
      • Brand tagline ("Every beach and lake home in El Salvador,
        ranked by value.")
      • Trust paragraph ("Pulpo doesn't take commission...")
      • Horizontal rule
      • Personalisation note ("You're getting this because your filter
        is set to La Libertad")
      • Pill-button row: [Change filters] [Change cadence] [Unsubscribe]
      • Copyright line

    Replaces v3's pipe-separated link row + 4-paragraph stack. Pill
    buttons are inline-styled so Gmail/Outlook render them as filled
    chips (not text links).
    """
    locale = issue.locale
    from . import i18n as _i18n
    tagline = i18n.t("footer.tagline", locale)
    if issue.cohort in ("anonymous", "logged_no_prefs"):
        you_line = i18n.t("footer.you_get_this.no_prefs", locale)
    else:
        summary = _i18n.filter_summary(issue.recipient.preference, locale)
        you_line = i18n.t("footer.you_get_this", locale, filter_summary=summary)
    change_filters_label = i18n.t("footer.change_filters", locale)
    change_cadence_label = i18n.t("footer.change_cadence", locale)
    unsubscribe_label = i18n.t("footer.unsubscribe", locale)
    no_commission = i18n.t("footer.no_commission", locale)
    copyright_line = i18n.t("footer.copyright", locale, year=issue.issue_id[:4])

    def _pill(href: str, label: str) -> str:
        return (
            f'<a href="{_e(href)}" style="display:inline-block;'
            f'font-size:12px;font-weight:600;padding:6px 12px;'
            f'color:#1A1916;border:1px solid rgba(0,0,0,0.18);'
            f'border-radius:999px;text-decoration:none;margin:0 6px 6px 0;">'
            f'{_e(label)}</a>'
        )

    return f"""
    <tr><td class="pad footer-strip" style="padding:24px 24px 28px;background:#F4EFE6;border-top:1px solid rgba(0,0,0,0.08);">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td style="line-height:0;padding-right:8px;vertical-align:middle;">
          <img src="https://pulpo.club/assets/email-logo-32@2x.png" width="20" height="20" alt="Pulpo" style="display:block;width:20px;height:20px;border:0;" />
        </td>
        <td style="vertical-align:middle;">
          <span style="font-size:16px;font-weight:700;letter-spacing:-0.03em;color:#1F3D31;">pulpo</span><span style="display:inline-block;font-size:9px;font-weight:700;letter-spacing:0.14em;padding:2px 5px;background:#D4A04A;color:#1F3D31;border-radius:3px;margin-left:5px;vertical-align:middle;line-height:1;">PRO</span>
        </td>
      </tr></table>
      <p style="margin:10px 0 0;font-size:13px;line-height:1.55;color:#1A1916;font-weight:500;">{_e(tagline)}</p>
      <p style="margin:8px 0 0;font-size:12.5px;line-height:1.55;color:#5A5650;">{_e(no_commission)}</p>
      <div style="margin:18px 0 14px;height:1px;background:rgba(0,0,0,0.08);"></div>
      <p style="margin:0 0 10px;font-size:12px;color:#888780;letter-spacing:0.04em;">{_e(you_line)}</p>
      <div>
        {_pill(issue.settings_url, change_filters_label)}{_pill(issue.settings_url, change_cadence_label)}{_pill(issue.unsubscribe_url, unsubscribe_label)}
      </div>
      <p style="margin:14px 0 0;font-size:11px;color:#888780;letter-spacing:0.04em;">{_e(copyright_line)} · pulpo.club</p>
      <p style="margin:4px 0 0;font-size:11px;color:#888780;letter-spacing:0.04em;">Pulpo · San Salvador, El Salvador</p>
    </td></tr>
    """


def _your_pulpo_html(issue: Issue) -> str:
    """v4 (2026-05-31) — "Pick up where you left off" block.

    Three stacked cream action cards (one per CTA) matching the locked
    mockup. Replaces the v3 dark navy `yp-panel` table. Each card is a
    full-width anchor with: small uppercase eyebrow (context — e.g.
    "3 saved listings") + bold title (action — e.g. "Open your
    favorites") + right-aligned arrow.

    Card visibility:
      • Saved-listings card — only when `your_pulpo.saved_count > 0`
        (cold-start / anonymous cohorts skip).
      • Filter card — only when `your_pulpo.filter_summary_human` is
        set (anonymous + logged-no-prefs skip).
      • Browse card — always rendered.
      • Welcome card — anonymous cohort only, carries the `/welcome?r=`
        URL the cross-device telemetry pipes off (was previously in
        the dropped `_next_issue_html` block).
    """
    yp = issue.your_pulpo
    locale = issue.locale
    site = _site_root_from_issue(issue)
    ref = f"?ref=newsletter_issue_{issue.issue_number:02d}"
    eb = i18n.t("yp.eyebrow", locale)
    title = i18n.t("yp.title", locale)

    saved_url = f"{site}/saved{ref}"
    filter_url = f"{site}/account/newsletter{ref}"
    browse_url = f"{site}/browse{ref}"

    def _card(href: str, eyebrow: str, action: str) -> str:
        return (
            f'<a href="{_e(href)}" style="display:block;background:#F8F4EC;'
            f'border:1px solid rgba(0,0,0,0.08);border-radius:8px;'
            f'padding:14px 16px;margin:0 0 10px;color:#1A1916;'
            f'text-decoration:none;">'
            f'<table width="100%" role="presentation"><tr>'
            f'<td>'
            f'<p style="margin:0 0 2px;font-size:11px;letter-spacing:0.10em;'
            f'text-transform:uppercase;color:#888780;font-weight:600;">'
            f'{_e(eyebrow)}</p>'
            f'<p style="margin:0;font-size:16px;font-weight:600;'
            f'color:#1A1916;">{_e(action)}</p>'
            f'</td>'
            f'<td align="right" style="font-size:18px;color:#1A1916;'
            f'font-weight:600;">&rarr;</td>'
            f'</tr></table></a>'
        )

    cards: list[str] = []

    if yp.saved_count > 0:
        eyebrow = i18n.t("yp.saved.label", locale, n=yp.saved_count)
        action = i18n.t("yp.saved.cta", locale)
        cards.append(_card(saved_url, eyebrow, action))

    if yp.filter_summary_human:
        eyebrow = i18n.t("yp.filter.label", locale, filter=yp.filter_summary_human)
        action = i18n.t("yp.filter.cta", locale)
        cards.append(_card(filter_url, eyebrow, action))

    browse_eyebrow = i18n.t("yp.browse.label", locale, n=yp.filter_match_count)
    browse_action = i18n.t("yp.browse.cta", locale)
    cards.append(_card(browse_url, browse_eyebrow, browse_action))

    if issue.cohort == "anonymous" and issue.welcome_prefs_url:
        welcome_eyebrow = i18n.t("yp.welcome.label", locale)
        welcome_action = i18n.t("yp.welcome.cta", locale)
        cards.append(_card(issue.welcome_prefs_url, welcome_eyebrow, welcome_action))

    return f"""
    <tr><td class="pad-h" style="padding:18px 24px 8px;">
      <div style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#1F3D31;font-weight:700;margin-bottom:4px;">{_e(eb)}</div>
      <h2 class="yp-title" style="font-family:'Instrument Serif',Georgia,serif;font-size:28px;line-height:1.08;letter-spacing:-0.012em;font-weight:400;margin:0 0 16px;color:#1A1916;">{_e(title)}</h2>
      {"".join(cards)}
    </td></tr>
    """


def _site_root_from_issue(issue: Issue) -> str:
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


def _next_issue_html(issue: Issue) -> str:
    locale = issue.locale
    eb = i18n.t("next.eyebrow", locale)
    body = i18n.t("next.body", locale)
    if issue.cohort == "anonymous" and issue.welcome_prefs_url:
        cta_label = i18n.t("next.cta.anon", locale)
        href = issue.welcome_prefs_url
    else:
        cta_label = i18n.t("next.cta", locale)
        href = issue.settings_url
    return f"""
    <tr><td class="pad" style="padding-top: 16px; padding-bottom: 20px;">
      <hr class="rule" />
      <div style="margin-top: 12px;">
        <div class="eyebrow">{_e(eb)}</div>
        <p class="body" style="max-width: 520px;">{_e(body)}</p>
        <p style="margin-top: 12px;"><a class="cta-ghost" href="{_e(href)}">{_e(cta_label)}</a></p>
      </div>
    </td></tr>
    """


# ─────────────────────────────────────────────────────────────────────────
# v4.0 — locked card component + new section intros + weekly news spotlight
#
# These replace the v3.x rich/short split. EVERY pick (top 3 and 4-10)
# renders through `_pick_card_html` — only the background color and the
# rank-pill copy differ between the two variants. Section intros sit
# between blocks of picks. The Weekly News Spotlight replaces the v3
# skip-block + next-issue pair with a single LLM-curated regional news
# story (deterministic placeholder until the LLM pipeline ships).
# ─────────────────────────────────────────────────────────────────────────


def _state_pill_html(text: str, bg: str, color: str) -> str:
    """One small uppercase chip rendered with inline styles (Outlook-safe)."""
    return (
        f'<span style="display:inline-block;font-size:11px;font-weight:600;'
        f'letter-spacing:0.10em;text-transform:uppercase;padding:5px 10px;'
        f'background:{bg};color:{color};border-radius:999px;">{_e(text)}</span>'
    )


def _pick_state_pill_html(pick: IssuePick, locale: Locale) -> str:
    """Derive the per-card state pill from real Listing fields.

    Order of precedence (one pill at most):
      1. Significantly under area average → sage discount pill
      2. New on the market this week → clay "New this week" pill
      3. Repriced this week           → "Price moved" pill
      4. None of the above                 → no pill
    """
    en = locale == "en"

    # Keytable carries pre-formatted "vs zone -78%" / "·" rows from build_issue.
    # Look for a negative percentage on the value/zone row.
    zone_pct: int | None = None
    for k, v in (pick.keytable or []):
        if "vs zone" in (k or "").lower() or "zona" in (k or "").lower():
            v_clean = (v or "").strip().replace("%", "").replace("−", "-")
            try:
                n = int(float(v_clean))
                if n < 0:
                    zone_pct = n
            except ValueError:
                pass
            break
    if zone_pct is not None and zone_pct <= -25:
        text = f"−{abs(zone_pct)}% under area avg" if en else f"−{abs(zone_pct)}% bajo el promedio"
        return _state_pill_html(text, bg="#C9DEC6", color="#1F3D31")

    if pick.is_new_this_fortnight:
        text = i18n.t("pick.new_pill", locale)
        return _state_pill_html(text, bg="#FBE6D8", color="#7A3D1F")

    if pick.is_repriced:
        text = i18n.t("pick.repriced_pill", locale)
        return _state_pill_html(text, bg="#EDE7DB", color="#5A5650")

    return ""


def _pick_ppm_from_keytable(pick: IssuePick) -> str:
    """Pull '$XXX/m²' out of the legacy keytable. Returns '' if absent."""
    for k, v in (pick.keytable or []):
        k_clean = (k or "").strip()
        if k_clean in ("$/m²", "$/m2"):
            v_clean = (v or "").strip()
            if not v_clean or v_clean == "—":
                return ""
            return v_clean + ("/m²" if "/m" not in v_clean else "")
    return ""


def _pick_card_html(
    pick: IssuePick,
    *,
    locale: Locale,
    is_top_deal: bool,
    paywall_url: str,
) -> str:
    """The single locked listing-card component for all 10 picks.

    Top-deal variant (ranks 01–03): sage `#DDE9DC` background +
    forest "Top deal · NN" pill. Regular variant (ranks 04–10):
    white background + sand "Top deal · NN" pill. v4.4 (2026-06-01)
    — the label TEXT is unified across all 10 picks; only the card
    surface + pill chrome differ. Every other slot — photo, title,
    spec strip, price, "Why we picked it" card, See-on-Pulpo + Save
    CTAs — renders identically across both.

    All visual rules are duplicated as inline `style=""` on each
    element so Gmail / Outlook / Yahoo (which strip `<style>` for
    most selectors and ALL pseudo-elements + CSS vars) still
    render the design. The class names stay for rich-client
    enhancement and for `tests/newsletter/test_render.py`
    snapshot assertions.

    Paywalled picks (Free cohort) render the photo and a teaser
    pill but suppress the title, price, why card, and CTAs — the
    paywall banner one row up carries the upsell.
    """
    en = locale == "en"
    rank = pick.rank

    # The rank LABEL is the same for every pick — "Top deal · NN" /
    # "Mejor oferta · NN" — because the numbering already tells the
    # ranking story (01 outranks 04 outranks 10). What still telegraphs
    # the editorial split between hero + shortlist is the card surface:
    # top-3 stay sage with a forest pill (visually loud), picks 4-10
    # stay white with a sand pill (visually calm). Two labels (Pick vs
    # Top deal) was confusing — readers asked "what's the difference?"
    # when there isn't a product difference, just a typographic one.
    rank_label = "Top deal" if en else "Mejor oferta"
    if is_top_deal:
        card_bg = "#DDE9DC"
        rank_pill_bg = "#1F3D31"
        rank_pill_color = "#F4EFE6"
    else:
        card_bg = "#FFFFFF"
        rank_pill_bg = "#E8DFC6"
        rank_pill_color = "#5A5650"

    state_pill = _pick_state_pill_html(pick, locale)

    # Pill row — rank pill ALWAYS, state pill if any.
    pill_row = (
        f'<div style="margin-bottom:8px;">'
        f'<span style="display:inline-block;font-size:11px;font-weight:700;'
        f'letter-spacing:0.10em;text-transform:uppercase;padding:5px 10px;'
        f'background:{rank_pill_bg};color:{rank_pill_color};border-radius:999px;'
        f'margin-right:6px;">{_e(rank_label)} · {rank:02d}</span>'
        f'{state_pill}'
        f'</div>'
    )

    # Photo (full-width). v4.3 (2026-05-31): listings without a
    # card-eligible photo are filtered out in `build_issue` via
    # `_listing_has_eligible_photo` BEFORE picking, so by the time we
    # reach here `pick.photo_url` is guaranteed non-empty. Operator
    # policy: a listing can only appear in the newsletter if every
    # field needed to render its card — photo included — is available.
    photo_html = (
        f'<img src="{_e(pick.photo_url)}" alt="{_e(pick.title or "")}" '
        f'width="100%" style="width:100%;height:auto;display:block;" />'
    )

    # Price line — "$900,000" + optional " · $621/m²" inline.
    ppm = _pick_ppm_from_keytable(pick) if not pick.paywalled else ""
    price_text = _e(pick.price_text or "—")
    if ppm:
        price_line = (
            f'{price_text} <span style="font-size:14px;color:#5A5650;'
            f'font-family:\'Inter\',-apple-system,sans-serif;letter-spacing:0;">· '
            f'{_e(ppm)}</span>'
        )
    else:
        price_line = price_text

    # Paywalled picks hide the body + CTAs — the paywall banner upsells.
    body_html = ""
    cta_html = ""
    if pick.paywalled:
        teaser = _e(i18n.t("pick.paywall_blurb", locale))
        body_html = (
            f'<p style="margin:0 0 14px;font-family:\'Inter\',sans-serif;'
            f'font-size:14.5px;line-height:1.55;color:#5A5650;">{teaser}</p>'
        )
    else:
        why_html = _why_block_html(pick, locale)
        cta_label = i18n.t("pick.cta_open", locale)
        save_label = i18n.t("pick.cta_save", locale)
        primary_url = pick.pulpo_url or pick.listing_url or paywall_url
        save_url = pick.save_url or (primary_url + ("&save=1" if "?" in primary_url else "?save=1"))
        title_html = _title_with_widow_guard(_e(pick.title or ""))
        body_html = (
            f'<h2 class="pick-title" style="font-family:\'Instrument Serif\','
            f'Georgia,serif;font-size:30px;line-height:1.06;letter-spacing:-0.01em;'
            f'font-weight:400;margin:0 0 4px;color:#1A1916;'
            # text-wrap: balance is honoured by Apple Mail Sonoma+, Gmail
            # web (Chromium), Outlook web; older clients silently fall
            # back to the default greedy wrap. The &nbsp; in title_html
            # is the universal-client fallback for short-word widows.
            f'text-wrap:balance;">{title_html}</h2>'
            f'<p style="margin:0 0 12px;font-size:12.5px;color:#5A5650;'
            f'letter-spacing:0.02em;text-transform:uppercase;font-weight:500;">'
            f'{_e(pick.location_line or "")}</p>'
            f'<p style="margin:0 0 14px;font-family:\'Instrument Serif\','
            f'Georgia,serif;font-size:30px;line-height:1;letter-spacing:-0.01em;'
            f'color:#1A1916;">{price_line}</p>'
            f'{why_html}'
        )
        # v4.3 (2026-05-31) — operator feedback: the &hearts; entity
        # was being rendered as a full-size red emoji by Apple Mail /
        # iOS Mail (U+2665 gets emoji-substituted at line-height),
        # pushing the button to 2 lines. Two defenses:
        #   1. `white-space:nowrap` on the anchor — even if the heart
        #      stays large, the content never wraps.
        #   2. `&#xfe0e;` after the heart — the U+FE0E text variation
        #      selector forces every client to render the preceding
        #      glyph as text, not emoji. Cross-client safe.
        # Same nowrap on the filled CTA so the right-arrow can't wrap
        # away from the label on tight viewports.
        cta_html = (
            f'<table role="presentation"><tr>'
            f'<td style="padding-right:8px;">'
            f'<a class="btn-fill" href="{_e(primary_url)}" '
            f'style="display:inline-block;font-size:13px;font-weight:600;'
            f'padding:11px 18px;background:#18211C;color:#F4EFE6;'
            f'border-radius:999px;letter-spacing:0.02em;text-decoration:none;'
            f'white-space:nowrap;">'
            f'{_e(cta_label)}</a></td>'
            f'<td><a class="btn-ghost" href="{_e(save_url)}" '
            f'style="display:inline-block;font-size:13px;font-weight:600;'
            f'padding:10px 16px;color:#1A1916;border:1px solid #1A1916;'
            f'border-radius:999px;letter-spacing:0.02em;text-decoration:none;'
            f'white-space:nowrap;">'
            f'&hearts;&#xfe0e; {_e(save_label)}</a></td>'
            f'</tr></table>'
        )

    # Open the title block with a "TOP DEAL · 01" pill for the top-3
    # variant only if we render full content (otherwise the pill row
    # already carries the rank). Paywalled picks still get the pill row.
    return f"""
    <tr><td class="pad-h" style="padding:8px 24px 8px;">
      <div class="pick-card" style="background:{card_bg};border-radius:10px;overflow:hidden;border:1px solid rgba(0,0,0,0.10);">
        {photo_html}
        <div style="padding:16px 18px 18px;">
          {pill_row}
          {body_html}
          {cta_html}
        </div>
      </div>
    </td></tr>
    """


def _preheader_html(issue: Issue) -> str:
    # The inbox-preview line. Hidden in the rendered email (CSS +
    # mso-hide:all for Outlook) but harvested by Gmail / Apple Mail /
    # Yahoo as the snippet shown next to the subject. Without this
    # block, mailers fall back to the first visible body text — which
    # is just the header chrome ("PULPO PRO · ISSUE 01 · 31 MAY 2026")
    # and adds zero curiosity. Source the tease from real content so
    # operators don't have to remember to set it per issue.
    locale = issue.locale
    top = issue.picks_top[0].title if issue.picks_top else ""
    n_rest = len(issue.picks_shortlist)
    if top and n_rest:
        if locale == "es":
            text = f"{top} — y {n_rest} más esta semana."
        else:
            text = f"{top} — plus {n_rest} more picks this week."
    elif top:
        if locale == "es":
            text = top
        else:
            text = top
    else:
        if locale == "es":
            text = "10 propiedades seleccionadas de El Salvador, esta semana."
        else:
            text = "10 hand-picked listings from El Salvador, this week."
    # Belt-and-braces hide chain: every property here covers a real
    # client. `mso-hide:all` covers Outlook; `display:none + opacity:0`
    # covers Gmail web + Apple Mail; the zeroed font/line/max-height
    # covers the rest. Trailing &#847; characters discourage Gmail from
    # appending the next visible block to the snippet.
    return (
        '<div style="display:none;font-size:1px;line-height:1px;'
        'max-height:0;max-width:0;opacity:0;overflow:hidden;'
        'mso-hide:all;color:transparent;visibility:hidden;">'
        f"{_e(text)}"
        f"{'&#847;&zwnj;&nbsp;' * 60}"
        "</div>"
    )


def _section_intro_top3_html(locale: Locale) -> str:
    """Editorial section header sitting between market context and pick 01."""
    title = i18n.t("section.top3.title", locale)
    body = i18n.t("section.top3.body", locale)
    return f"""
    <tr><td class="pad-h" style="padding:26px 24px 14px;">
      <div style="height:1px;background:#1A1916;margin-bottom:20px;"></div>
      <h2 style="font-family:'Instrument Serif',Georgia,serif;font-size:38px;line-height:1.04;letter-spacing:-0.015em;font-weight:400;margin:0 0 10px;color:#1A1916;">{_e(title)}</h2>
      <p style="font-family:'Instrument Serif',Georgia,serif;font-size:17px;line-height:1.45;color:#5A5650;margin:0;max-width:560px;">{_e(body)}</p>
    </td></tr>
    """


def _section_intro_rest_html(locale: Locale, n_rest: int) -> str:
    """Editorial section header sitting between pick 03 and pick 04."""
    title = i18n.t("section.rest.title", locale, n=n_rest)
    body = i18n.t("section.rest.body", locale)
    return f"""
    <tr><td class="pad-h" style="padding:26px 24px 14px;">
      <div style="height:1px;background:#1A1916;margin-bottom:20px;"></div>
      <h2 style="font-family:'Instrument Serif',Georgia,serif;font-size:38px;line-height:1.04;letter-spacing:-0.015em;font-weight:400;margin:0 0 10px;color:#1A1916;">{_e(title)}</h2>
      <p style="font-family:'Instrument Serif',Georgia,serif;font-size:17px;line-height:1.45;color:#5A5650;margin:0;max-width:560px;">{_e(body)}</p>
    </td></tr>
    """


def _weekly_news_spotlight_html(issue: Issue) -> str:
    """The "Weekly News Spotlight" block — one curated regional-news
    story per issue, sourced from a whitelist of El Salvador outlets
    (El Diario de Hoy, La Prensa Gráfica, El Mundo, Diario El Salvador,
    La Página).

    v4.0 ships a DETERMINISTIC placeholder so the block renders today.
    The LLM news-search pipeline is the follow-up (separate PR): it
    will populate `issue.news_spotlight` with `{title, paragraph,
    source_name, source_url, source_date}` each Sunday before the
    Monday send. When that field is empty, the deterministic fallback
    below renders — no fake news, no fabricated citations.
    """
    locale = issue.locale
    en = locale == "en"
    eyebrow = i18n.t("spotlight.eyebrow", locale)

    spot = getattr(issue, "news_spotlight", None)
    if spot:
        # Accept either the `NewsSpotlight` dataclass or a plain dict —
        # keeps the renderer testable without a build_issue round-trip.
        def _g(key: str) -> str:
            val = getattr(spot, key, None)
            if val is None and isinstance(spot, dict):
                val = spot.get(key)
            return val or ""
        title = _g("title")
        paragraph = _g("paragraph")
        source_name = _g("source_name")
        source_url = _g("source_url")
        source_date = _g("source_date")
    else:
        # Deterministic fallback — generic editorial frame keyed off
        # the issue's data. Honest, no LLM-curated article. We DO
        # attribute it to Pulpo's own coastal market scan so the
        # spotlight block has a complete "Reported by …" line at the
        # top (otherwise the section looks unbranded — operator
        # feedback, 2026-05-30). The attribution is sourceless (no
        # URL), which the renderer below handles by emitting the
        # citation text without a link.
        title = i18n.t("spotlight.fallback.title", locale)
        paragraph = i18n.t("spotlight.fallback.body", locale)
        source_name = "Pulpo Pro coastal scan" if en else "Escaneo costero de Pulpo Pro"
        source_url = ""
        source_date = _e(issue.issue_date_human) if getattr(issue, "issue_date_human", "") else ""

    if not title or not paragraph:
        return ""

    # Source citation only when a source is named. Article URL is the
    # specific story the LLM pulled (or empty for the deterministic
    # fallback's self-attribution).
    source_line_html = ""
    if source_name:
        reported_by = "Reported by" if en else "Reportado por"
        if source_url:
            src_html = (
                f'<a href="{_e(source_url)}" target="_blank" rel="noopener" '
                f'style="color:#5A5650;border-bottom:1px solid #5A5650;">'
                f'{_e(source_name)}</a>'
            )
        else:
            src_html = _e(source_name)
        date_html = f" · {_e(source_date)}" if source_date else ""
        source_line_html = (
            f'<p style="font-size:11.5px;color:#5A5650;letter-spacing:0.04em;'
            f'margin:0 0 12px;font-weight:500;">{reported_by} {src_html}{date_html}</p>'
        )

    # Pulpo brand-mark icon next to the eyebrow — signals this is a
    # recurring Pulpo institutional section.
    return f"""
    <tr><td class="pad-h" style="padding:28px 24px 22px;">
      <div style="height:1px;background:#1A1916;margin-bottom:20px;"></div>
      <table role="presentation" cellpadding="0" cellspacing="0" style="margin-bottom:6px;"><tr>
        <td style="line-height:0;padding-right:8px;vertical-align:middle;">
          <img src="https://pulpo.club/assets/email-logo-32@2x.png" width="18" height="18" alt="Pulpo" style="display:block;width:18px;height:18px;border:0;" />
        </td>
        <td style="vertical-align:middle;">
          <div style="font-size:11px;letter-spacing:0.14em;text-transform:uppercase;color:#1F3D31;font-weight:700;">{_e(eyebrow)}</div>
        </td>
      </tr></table>
      {source_line_html}
      <h2 style="font-family:'Instrument Serif',Georgia,serif;font-size:30px;line-height:1.08;letter-spacing:-0.012em;font-weight:400;margin:0 0 10px;color:#1A1916;">{_e(title)}</h2>
      <p style="font-size:15.5px;line-height:1.6;color:#1A1916;margin:0;max-width:580px;">{paragraph}</p>
    </td></tr>
    """


def _favorites_editorial_summary(favorites: list, locale: str) -> str:
    """Editorial framing line for the favorites block.

    Replaces v3's verbose state-by-state summary ("One had a price
    drop, One moved up in price, …") with a single editorial sentence
    keyed off the count of movers vs total saves. Honest in both
    directions: a quiet week reads "your watchlist held flat", a
    busy week reads "busier than a typical week".
    """
    en = locale == "en"
    total = len(favorites)
    moved = sum(1 for u in favorites if u.state in ("price_dropped", "price_up"))

    en_word = {0: "None", 1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five"}
    es_word = {0: "Ninguno", 1: "Uno", 2: "Dos", 3: "Tres", 4: "Cuatro", 5: "Cinco"}
    total_en = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
    total_es = {1: "uno", 2: "dos", 3: "tres", 4: "cuatro", 5: "cinco"}

    moved_word = (en_word.get(moved) or str(moved)) if en else (es_word.get(moved) or str(moved))
    total_word = (total_en.get(total) or str(total)) if en else (total_es.get(total) or str(total))

    if moved == 0:
        return (
            "<strong style='font-style:normal;'>None moved on price this week</strong> — your watchlist held flat."
            if en else
            "<strong style='font-style:normal;'>Ninguno se movió en precio esta semana</strong> — tu lista quedó plana."
        )

    # Busy vs quiet read — "busy" when most/all moved.
    busy = moved >= max(2, total - 1)
    if en:
        tail = "busier than a typical week on your watchlist" if busy else "fewer moves than usual on your watchlist"
        return (
            f"<strong style='font-style:normal;'>{moved_word} of {total_word} moved on price this week</strong> — {tail}."
        )
    else:
        tail = "más actividad que una semana típica en tu lista" if busy else "menos actividad de la habitual en tu lista"
        return (
            f"<strong style='font-style:normal;'>{moved_word} de {total_word} se movieron en precio esta semana</strong> — {tail}."
        )


def render_html(issue: Issue) -> str:
    locale = issue.locale
    head_title = f"Pulpo — Issue {issue.issue_number:02d} · {issue.issue_date_human}"
    issue_strip = i18n.t(
        "header.issue", locale, n=f"{issue.issue_number:02d}", date=issue.issue_date_human.upper()
    )

    # v4.0 — every pick (top 3 + 4-10) renders through the SAME locked
    # `_pick_card_html` component. Only the background color and the
    # rank-pill copy differ. The v3 split between `_rich_pick` and
    # `_short_pick` is dead.
    top3_html = "".join(
        _pick_card_html(p, locale=locale, is_top_deal=True, paywall_url=issue.paywall_target_url)
        for p in issue.picks_top
    )
    rest_html = ""
    section_intro_rest_html = ""
    if issue.picks_shortlist:
        rest_html = "".join(
            _pick_card_html(p, locale=locale, is_top_deal=False, paywall_url=issue.paywall_target_url)
            for p in issue.picks_shortlist
        )
        section_intro_rest_html = _section_intro_rest_html(locale, len(issue.picks_shortlist))

    section_intro_top3_html = (
        _section_intro_top3_html(locale) if issue.picks_top else ""
    )

    hero_block = f"""
    <tr><td style="padding:28px 24px 20px;">
      <div class="eyebrow">{_e(issue.commentary.eyebrow_hero)}</div>
      <h1 class="h-hero">{_e(issue.commentary.headline_hero)}</h1>
      <p class="lede" style="margin: 4px 0 14px; max-width: 540px;">{issue.commentary.lede_hero}</p>
      {_filter_chips_html(issue.commentary.filter_chips)}
    </td></tr>
    """

    # Brand mark: hosted PNG so every email client renders it. Inline
    # SVGs are stripped by Gmail iOS app, Outlook desktop, Yahoo, AOL —
    # `web/assets/email-logo-32@2x.png` (64x64 RGBA) is the canonical
    # Pulpo octopus + gold-catch mark. Served from pulpo.club with a
    # 1-day CDN cache + image/png Content-Type.
    #
    # Horizontal padding switched from `class="pad-sm"` (36px from the
    # v3 CSS block) to inline 24px to match every v4 body block —
    # without this the header sat 12px further out than the content
    # below it, producing the "floating header" effect.
    header_strip = f"""
    <tr><td style="padding:14px 24px;border-bottom: 1px solid var(--line);">
      <table width="100%" role="presentation"><tr>
        <td style="vertical-align: middle;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align: middle; padding-right: 10px; line-height: 0;">
              <img src="https://pulpo.club/assets/email-logo-32@2x.png" width="26" height="26" alt="Pulpo" style="display:block;width:26px;height:26px;border:0;" />
            </td>
            <td style="vertical-align: middle;">
              <span class="display" style="font-size: 24px; font-weight: 700; letter-spacing: -0.035em; color: #1F3D31; line-height: 1; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;">pulpo</span><span style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:0.14em;padding:2px 6px;background:#D4A04A;color:#1F3D31;border-radius:3px;margin-left:6px;vertical-align:middle;line-height:1;">PRO</span>
            </td>
          </tr></table>
        </td>
        <td align="right" style="vertical-align: middle;">
          <span class="mono" style="font-size: 11px; color: var(--ink-3); letter-spacing: 0.08em;">{_e(issue_strip)}</span>
        </td>
      </tr></table>
    </td></tr>
    """

    # v4.0 layout order:
    #   header → hero → favorites → market context →
    #   [Top 3 this week intro] → picks 01-03 → paywall (if free) →
    #   [7 more this week intro] → picks 04-10 →
    #   Weekly News Spotlight → Your Pulpo → footer.
    #
    # Dropped from v3: skip block (just noise) and "next issue" block
    # (replaced by the Weekly News Spotlight). The shortlist section
    # header is replaced by the bigger `_section_intro_rest_html`.
    return f"""<!doctype html>
<html lang="{locale}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="x-pulpo-template" content="{_e(TEMPLATE_VERSION)}" />
<title>{_e(head_title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet" />
<style>{_CSS}</style>
</head>
<body>
{_preheader_html(issue)}
<div class="wrap">
  <table class="frame" role="presentation" cellpadding="0" cellspacing="0" width="680">
    {header_strip}
    {hero_block}
    {_favorites_html(issue)}
    {_market_html(issue)}
    {section_intro_top3_html}
    {top3_html}
    {_paywall_banner_html(issue)}
    {section_intro_rest_html}
    {rest_html}
    {_weekly_news_spotlight_html(issue)}
    {_your_pulpo_html(issue)}
    {_footer_html(issue)}
  </table>
</div>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────────────
# Pulpo Pro Welcome — one-shot onboarding email fired after first Stripe
# payment.
#
# Composition reuses the General template's chrome (header, picks card,
# footer) and swaps the editorial top:
#
#   header_strip → welcome_hero → how_pulpo_works → cadence_note
#               → welcome_picks_intro → picks 01-10
#               → welcome_start_here → footer
#
# DROPPED from General: favorites (nothing saved yet), market_context
# (replaced by how_pulpo_works), paywall_banner (Pro reader),
# news_spotlight (welcome is heavy enough), your_pulpo (replaced by
# welcome_start_here onboarding cards).
#
# All shared visuals (CSS, brand chrome, pick cards, section intro
# component, footer) come from the same private helpers the weekly
# digest uses — so a future v4.5 bump to the pick card lands on both
# templates automatically.
# ─────────────────────────────────────────────────────────────────────────


def _welcome_hero_html(issue: Issue) -> str:
    """Welcome hero — eyebrow + first-name H1 + 2-sentence lede.

    Falls back to "Welcome aboard." when `display_name` is empty
    (Clerk's first-name field is optional). First-name only — strips
    any trailing surname so "Sebastian García" reads as "Welcome,
    Sebastian." not "Welcome, Sebastian García."
    """
    locale = issue.locale
    eyebrow = i18n.t("welcome.hero.eyebrow", locale)
    name = (issue.recipient.display_name or "").strip()
    if name:
        first = name.split()[0]
        headline = i18n.t("welcome.hero.headline.named", locale, name=first)
    else:
        headline = i18n.t("welcome.hero.headline.unnamed", locale)
    lede = i18n.t("welcome.hero.lede", locale)
    return f"""
    <tr><td style="padding:28px 24px 20px;">
      <div class="eyebrow">{_e(eyebrow)}</div>
      <h1 class="h-hero">{_e(headline)}</h1>
      <p class="lede" style="margin: 4px 0 14px; max-width: 540px;">{_e(lede)}</p>
    </td></tr>
    """


def _how_pulpo_works_html(locale: Locale) -> str:
    """3 numbered editorial beats explaining the Pulpo value chain.

    Reuses the visual treatment of `_market_html` (big serif 01/02/03
    numerals + forest green) so the reader sees the same chrome they'll
    get on every weekly digest. The bold tags inside each step survive
    the no-escape pass — they're hand-authored in i18n.STRINGS and have
    no LLM provenance, so escaping is unnecessary and would hide the
    intentional emphasis.
    """
    eb = i18n.t("welcome.how.eyebrow", locale)
    hl = i18n.t("welcome.how.headline", locale)
    steps = [
        i18n.t("welcome.how.step1", locale),
        i18n.t("welcome.how.step2", locale),
        i18n.t("welcome.how.step3", locale),
    ]

    block_html_parts: list[str] = []
    for idx, block in enumerate(steps, start=1):
        is_last = idx == len(steps)
        block_margin = "0" if is_last else "0 0 18px"
        block_html_parts.append(
            f'<table width="100%" role="presentation" cellpadding="0" cellspacing="0" style="margin:{block_margin};">'
            f'<tr>'
            f'<td width="44" valign="top" style="width:44px;padding:0 12px 0 0;vertical-align:top;">'
            f'<div style="font-family:\'Instrument Serif\',Georgia,serif;font-size:32px;line-height:1;color:#1F3D31;font-weight:400;letter-spacing:-0.02em;">{idx:02d}</div>'
            f'</td>'
            f'<td valign="top" style="vertical-align:top;">'
            f'<p style="font-size:15.5px;line-height:1.6;color:#1A1916;margin:0;">{block}</p>'
            f'</td>'
            f'</tr></table>'
        )
    blocks_html = "".join(block_html_parts)

    return f"""
    <tr><td class="pad-h" style="padding:18px 24px 16px;">
      <div style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#1F3D31;font-weight:600;margin-bottom:6px;">{_e(eb)}</div>
      <h2 style="font-family:'Instrument Serif',Georgia,serif;font-size:30px;line-height:1.08;letter-spacing:-0.012em;font-weight:400;margin:0 0 16px;color:#1A1916;">{_e(hl)}</h2>
      {blocks_html}
    </td></tr>
    """


def _format_cadence_date(d, locale: Locale) -> str:
    """Format a date for the cadence note. EN: "Sunday, June 7" /
    ES: "el domingo 7 de junio". Locale-aware so we don't ship English
    month names into a Spanish email."""
    months_en = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ]
    months_es = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    if locale == "es":
        return f"el domingo {d.day} de {months_es[d.month - 1]}"
    return f"Sunday, {months_en[d.month - 1]} {d.day}"


def _cadence_note_html(issue: Issue, now=None) -> str:
    """Editorial line setting the reader's expectation for the first
    weekly digest. `now` is a `datetime` (UTC) — defaults to actual
    wall-clock; tests pass an explicit value for reproducible output.

    Two variants:
      • Today IS Sunday before 10:00 SV → same-day variant ("lands today
        at 10 AM SV"). Welcome and the week's digest will collide; the
        reader is forewarned.
      • Otherwise → future variant ("lands Sunday, June 7"). Computes
        the next Sunday 10:00 SV after `now`.

    SV is UTC-6, no DST — single offset, no zoneinfo dependency.
    """
    from datetime import datetime, timedelta, timezone
    locale = issue.locale
    sv_offset = timezone(timedelta(hours=-6))
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_sv = now.astimezone(sv_offset)
    weekday = now_sv.weekday()  # Mon=0 … Sun=6
    days_until_sun = (6 - weekday) % 7

    if days_until_sun == 0 and now_sv.hour < 10:
        # Welcome lands on a Sunday morning — same-day collision with
        # this week's digest. Tell the reader directly.
        note = i18n.t("welcome.cadence.same_day", locale)
    else:
        if days_until_sun == 0:
            # Sunday after 10am — next send is 7 days out.
            days_until_sun = 7
        next_sun = (now_sv + timedelta(days=days_until_sun)).replace(
            hour=10, minute=0, second=0, microsecond=0
        )
        date_str = _format_cadence_date(next_sun, locale)
        note = i18n.t("welcome.cadence.future", locale, date=date_str)

    return f"""
    <tr><td class="pad-h" style="padding:0 24px 22px;">
      <p style="font-family:'Inter',sans-serif;font-size:13.5px;line-height:1.55;color:#5A5650;margin:0;border-left:3px solid #1F3D31;padding-left:14px;">{_e(note)}</p>
    </td></tr>
    """


def _welcome_picks_intro_html(locale: Locale) -> str:
    """Section header above pick 01 in the welcome. Mirrors the
    visual weight of `_section_intro_top3_html` so the reader's
    second weekly already recognizes the chrome."""
    title = i18n.t("welcome.section.picks.title", locale)
    body = i18n.t("welcome.section.picks.body", locale)
    return f"""
    <tr><td class="pad-h" style="padding:26px 24px 14px;">
      <div style="height:1px;background:#1A1916;margin-bottom:20px;"></div>
      <h2 style="font-family:'Instrument Serif',Georgia,serif;font-size:38px;line-height:1.04;letter-spacing:-0.015em;font-weight:400;margin:0 0 10px;color:#1A1916;">{_e(title)}</h2>
      <p style="font-family:'Instrument Serif',Georgia,serif;font-size:17px;line-height:1.45;color:#5A5650;margin:0;max-width:560px;">{_e(body)}</p>
    </td></tr>
    """


def _welcome_start_here_html(issue: Issue) -> str:
    """3 stacked cream onboarding cards. Replaces the General's
    "Pick up where you left off" block (returning-user) with a
    "Start here" block (first-time user). Always renders all 3 —
    no conditional visibility, because every brand-new Pro user
    benefits from each of these actions."""
    locale = issue.locale
    site = _site_root_from_issue(issue)
    ref = "?ref=newsletter_pro_welcome"
    eb = i18n.t("welcome.start.eyebrow", locale)
    title = i18n.t("welcome.start.title", locale)

    filter_url = f"{site}/account/newsletter{ref}"
    browse_url = f"{site}/browse{ref}"
    account_url = f"{site}/account{ref}"

    def _card(href: str, eyebrow: str, action: str) -> str:
        return (
            f'<a href="{_e(href)}" style="display:block;background:#F8F4EC;'
            f'border:1px solid rgba(0,0,0,0.08);border-radius:8px;'
            f'padding:14px 16px;margin:0 0 10px;color:#1A1916;'
            f'text-decoration:none;">'
            f'<table width="100%" role="presentation"><tr>'
            f'<td>'
            f'<p style="margin:0 0 2px;font-size:11px;letter-spacing:0.10em;'
            f'text-transform:uppercase;color:#888780;font-weight:600;">'
            f'{_e(eyebrow)}</p>'
            f'<p style="margin:0;font-size:16px;font-weight:600;'
            f'color:#1A1916;">{_e(action)}</p>'
            f'</td>'
            f'<td align="right" style="font-size:18px;color:#1A1916;'
            f'font-weight:600;">&rarr;</td>'
            f'</tr></table></a>'
        )

    cards = [
        _card(filter_url,
              i18n.t("welcome.start.filter.label", locale),
              i18n.t("welcome.start.filter.cta", locale)),
        _card(browse_url,
              i18n.t("welcome.start.browse.label", locale),
              i18n.t("welcome.start.browse.cta", locale)),
        _card(account_url,
              i18n.t("welcome.start.account.label", locale),
              i18n.t("welcome.start.account.cta", locale)),
    ]

    return f"""
    <tr><td class="pad-h" style="padding:18px 24px 8px;">
      <div style="font-size:11px;letter-spacing:0.12em;text-transform:uppercase;color:#1F3D31;font-weight:700;margin-bottom:4px;">{_e(eb)}</div>
      <h2 class="yp-title" style="font-family:'Instrument Serif',Georgia,serif;font-size:28px;line-height:1.08;letter-spacing:-0.012em;font-weight:400;margin:0 0 16px;color:#1A1916;">{_e(title)}</h2>
      {"".join(cards)}
    </td></tr>
    """


def render_welcome_html(issue: Issue, *, now=None) -> str:
    """Render the Pulpo Pro Welcome email.

    `now` is an optional datetime override for the cadence-note
    computation — tests pin a known wall-clock so the same-day vs
    future variant is deterministic.

    Composition order (mirrors General where chrome is shared):
      header → welcome_hero → how_pulpo_works → cadence_note
            → welcome_picks_intro → picks 01-10
            → welcome_start_here → footer

    Dropped vs General: favorites, market_context, paywall_banner,
    news_spotlight, your_pulpo (replaced with welcome_start_here).
    """
    locale = issue.locale
    head_title = i18n.t("welcome.hero.eyebrow", locale)
    issue_strip = i18n.t(
        "header.issue", locale, n=f"{issue.issue_number:02d}", date=issue.issue_date_human.upper()
    )

    # Picks render through the SAME `_pick_card_html` the weekly uses.
    # Top 3 = sage background ("Top deal · NN"); next 7 = white ("Pick · NN").
    top_html = "".join(
        _pick_card_html(p, locale=locale, is_top_deal=True, paywall_url=issue.paywall_target_url)
        for p in issue.picks_top
    )
    rest_html = ""
    section_intro_rest_html = ""
    if issue.picks_shortlist:
        rest_html = "".join(
            _pick_card_html(p, locale=locale, is_top_deal=False, paywall_url=issue.paywall_target_url)
            for p in issue.picks_shortlist
        )
        section_intro_rest_html = _section_intro_rest_html(locale, len(issue.picks_shortlist))

    # Header strip — duplicated from `render_html` so the welcome
    # template is fully self-contained. If the brand chrome ever
    # refactors into a shared helper, both templates can swap to it.
    header_strip = f"""
    <tr><td style="padding:14px 24px;border-bottom: 1px solid var(--line);">
      <table width="100%" role="presentation"><tr>
        <td style="vertical-align: middle;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align: middle; padding-right: 10px; line-height: 0;">
              <img src="https://pulpo.club/assets/email-logo-32@2x.png" width="26" height="26" alt="Pulpo" style="display:block;width:26px;height:26px;border:0;" />
            </td>
            <td style="vertical-align: middle;">
              <span class="display" style="font-size: 24px; font-weight: 700; letter-spacing: -0.035em; color: #1F3D31; line-height: 1; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;">pulpo</span><span style="display:inline-block;font-size:10px;font-weight:700;letter-spacing:0.14em;padding:2px 6px;background:#D4A04A;color:#1F3D31;border-radius:3px;margin-left:6px;vertical-align:middle;line-height:1;">PRO</span>
            </td>
          </tr></table>
        </td>
        <td align="right" style="vertical-align: middle;">
          <span class="mono" style="font-size: 11px; color: var(--ink-3); letter-spacing: 0.08em;">{_e(issue_strip)}</span>
        </td>
      </tr></table>
    </td></tr>
    """

    return f"""<!doctype html>
<html lang="{locale}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="x-pulpo-template" content="{_e(WELCOME_TEMPLATE_VERSION)}" />
<title>{_e(head_title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&display=swap" rel="stylesheet" />
<style>{_CSS}</style>
</head>
<body>
{_preheader_html(issue)}
<div class="wrap">
  <table class="frame" role="presentation" cellpadding="0" cellspacing="0" width="680">
    {header_strip}
    {_welcome_hero_html(issue)}
    {_how_pulpo_works_html(locale)}
    {_cadence_note_html(issue, now=now)}
    {_welcome_picks_intro_html(locale)}
    {top_html}
    {section_intro_rest_html}
    {rest_html}
    {_welcome_start_here_html(issue)}
    {_footer_html(issue)}
  </table>
</div>
</body>
</html>
"""
