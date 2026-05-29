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

from html import escape as _e

from . import i18n
from .types import Issue, IssuePick, Locale


# Bumped whenever the renderer's CSS or layout changes in a way we'd want
# to slice in PostHog (audience tests, regression hunts, A/B pre-bake).
# Stays in sync with docs/newsletter-audit.md. Exposed via
# email.newsletter.sent / email.newsletter.batch_sent telemetry AND a
# <meta name="x-pulpo-template"> tag in the rendered HTML <head>.
TEMPLATE_VERSION = "newsletter-v3.0-2026-05"


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
  --font-display: "Instrument Serif", "Iowan Old Style", Georgia, "Times New Roman", serif;
  --font-sans:    "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  --font-mono:    "JetBrains Mono", "SFMono-Regular", Menlo, Consolas, monospace;
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
.mono    { font-family: var(--font-mono); }
.ink     { color: var(--ink); }
.ink-2   { color: var(--ink-2); }
.muted   { color: var(--ink-3); }
.forest  { color: var(--forest); }
.clay    { color: var(--clay); }
.rule        { border: 0; border-top: 1px solid var(--line); margin: 0; }
.rule-strong { border: 0; border-top: 1px solid var(--ink); margin: 0; }
.eyebrow {
  font-family: var(--font-mono);
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
/* PR-NL-6 — story_html wraps the single emotional-center sentence in
   <em>...</em>. Lands the reader's eye there without using bold or a
   colored callout block. PR-NL-7a extends to .lede for the welcome
   teaser and to the first market_context paragraph. */
.body em, .body-2 em, .lede em { font-style: italic; color: var(--clay-deep); }
.small   { font-family: var(--font-sans); font-size: 12.5px; line-height: 1.55; color: var(--ink-3); }
.meta    { font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.06em; color: var(--forest); text-transform: uppercase; }
.price       { font-family: var(--font-display); font-size: 30px; line-height: 1; font-weight: 400; color: var(--ink); letter-spacing: -0.01em; }
.price-2     { font-family: var(--font-display); font-size: 22px; line-height: 1; font-weight: 400; color: var(--ink); letter-spacing: -0.01em; }
.price-note  { font-family: var(--font-sans); font-size: 12.5px; color: var(--ink-3); }
.pill {
  display: inline-block;
  font-family: var(--font-mono);
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
  font-family: var(--font-mono);
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
  font-family: var(--font-mono);
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
  font-family: var(--font-mono);
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
.sl-card .sl-why em { font-style: italic; color: var(--clay-deep); }
.meta-row { font-family: var(--font-sans); font-size: 13.5px; line-height: 1.55; color: var(--ink-2); }
.callout { margin: 14px 0 0; padding: 0; background: none; }
.callout .label { font-family: var(--font-mono); font-size: 11px; font-weight: 600; letter-spacing: 0.12em; text-transform: uppercase; color: var(--forest); margin: 0 0 4px; }
.callout .body  { margin: 0; font-size: 14.5px; line-height: 1.55; color: var(--ink); }
.callout + .callout { margin-top: 12px; }
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
  font-family: var(--font-mono);
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

    v3: the "★ Top pick this fortnight" chip — emitted by
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
    """
    bullets = getattr(pick, "why_bullets", None) or []
    if not bullets:
        return ""
    label = i18n.t("pick.why_label", locale)
    items = "".join(f"<li>{_e(b)}</li>" for b in bullets)
    return (
        f'<div class="why-block">'
        f'<p class="why-label">{_e(label)}</p>'
        f'<ul class="why-list">{items}</ul>'
        f"</div>"
    )


def _meta_row_html(rows: list[tuple[str, str]]) -> str:
    """Single-line magazine-spec strip replacing the old keytable grid.

    The old `<table class="keytable">` jammed four key/value pairs into one
    row with no visual separation — rendered as `$/m² $47 vs zone -78% per
    m² vs zone Beach 5.7 km Airport 36 km Listed New this fortnight`. The
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

    return f"""
    <tr><td style="padding: 12px 0 0 0;">{_photo_html(pick)}</td></tr>
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


def _market_html(issue: Issue) -> str:
    paras = issue.commentary.market_context
    if not paras:
        return ""
    locale = issue.locale
    eb = i18n.t("market.eyebrow", locale)
    hl = i18n.t("market.headline", locale)
    # PR-NL-7a: the first paragraph is the warm market note that may
    # contain a single <em>...</em> span — don't html-escape it. Source
    # is either deterministic_market_note (known-good HTML) or
    # llm_commentary (prompt enforces only <em> tags, no other markup).
    # Subsequent paragraphs stay plain text and ARE escaped.
    para_html_parts: list[str] = []
    for i, para in enumerate(paras):
        if i == 0:
            para_html_parts.append(f'<p class="body">{para}</p>')
        else:
            para_html_parts.append(f'<p class="body">{_e(para)}</p>')
    para_html = "".join(para_html_parts)
    return f"""
    <tr><td class="pad" style="background: var(--paper-2); padding-top: 20px; padding-bottom: 20px;">
      <div class="eyebrow">{_e(eb)}</div>
      <h2 class="h1">{_e(hl)}</h2>
      {para_html}
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
    return f"""
    <tr><td class="pad footer-strip">
      <p class="small">{_e(tagline)}</p>
      <p class="small" style="margin-top: 6px;">{_e(you_line)}</p>
      <p class="small" style="margin-top: 12px;">
        <a href="{_e(issue.settings_url)}">{_e(change_filters_label)}</a> &middot;
        <a href="{_e(issue.settings_url)}">{_e(change_cadence_label)}</a> &middot;
        <a href="{_e(issue.unsubscribe_url)}">{_e(unsubscribe_label)}</a>
      </p>
      <p class="small" style="margin-top: 14px;">{_e(no_commission)}</p>
      <p class="small" style="margin-top: 14px;">{_e(copyright_line)} &middot; <span class="mono">pulpo.club</span></p>
    </td></tr>
    """


def _your_pulpo_html(issue: Issue) -> str:
    """PR-NL-8 — the dark "Your Pulpo" panel.

    Three rows, each driven by `issue.your_pulpo`:
      • saved listings count   → /saved
      • filter summary line    → /account/notifications
      • filter-match count     → /browse

    All URLs carry `ref=newsletter_issue_<N>` so PostHog can attribute
    in-app conversion back to the issue. The panel intentionally lives
    AFTER the editorial content (skip, market, next-issue) and just
    above the footer — the natural "what to do next on Pulpo" slot.

    Anonymous cohort renders a softer variant: no saved-listings row,
    no filter summary (they don't have one yet), just the "browse all"
    nudge. The renderer falls through to those defaults when
    `your_pulpo.filter_summary_human` is empty.
    """
    yp = issue.your_pulpo
    locale = issue.locale
    site = _site_root_from_issue(issue)
    ref = f"?ref=newsletter_issue_{issue.issue_number:02d}"
    eb = i18n.t("yp.eyebrow", locale)
    title = i18n.t("yp.title", locale)

    saved_url = f"{site}/saved{ref}"
    filter_url = f"{site}/account/notifications{ref}"
    browse_url = f"{site}/browse{ref}"

    rows: list[str] = []

    # Row 1 — saved listings (skip for anonymous / 0-saved cold-start).
    if yp.saved_count > 0:
        saved_label = i18n.t("yp.saved.label", locale, n=yp.saved_count)
        saved_cta = i18n.t("yp.saved.cta", locale)
        rows.append(
            f'<tr><td class="yp-row-label">{_e(saved_label)}</td>'
            f'<td class="yp-row-cta"><a href="{_e(saved_url)}">{_e(saved_cta)}</a></td></tr>'
        )

    # Row 2 — filter summary (skip for anonymous).
    if yp.filter_summary_human:
        filter_cta = i18n.t("yp.filter.cta", locale)
        rows.append(
            f'<tr><td class="yp-row-label">{_e(yp.filter_summary_human)}</td>'
            f'<td class="yp-row-cta"><a href="{_e(filter_url)}">{_e(filter_cta)}</a></td></tr>'
        )

    # Row 3 — browse the full filter (always present).
    browse_label = i18n.t("yp.browse.label", locale, n=yp.filter_match_count)
    browse_cta = i18n.t("yp.browse.cta", locale)
    rows.append(
        f'<tr><td class="yp-row-label">{_e(browse_label)}</td>'
        f'<td class="yp-row-cta"><a href="{_e(browse_url)}">{_e(browse_cta)}</a></td></tr>'
    )

    return f"""
    <tr><td class="yp-panel">
      <div class="yp-eyebrow">{_e(eb)}</div>
      <h2 class="yp-title">{_e(title)}</h2>
      <table class="yp-table" role="presentation">
        {''.join(rows)}
      </table>
    </td></tr>
    """


def _site_root_from_issue(issue: Issue) -> str:
    """Extract https://pulpo.club (or whatever PULPO_SITE_ROOT points at)
    from any of the absolute URLs already on the Issue. Avoids re-reading
    the env var here — build_issue.py already resolved it once."""
    candidate = (
        (issue.unsubscribe_url or "").split("/unsubscribe", 1)[0]
        or (issue.settings_url or "").split("/account", 1)[0]
        or "https://pulpo.club"
    )
    return candidate.rstrip("/") or "https://pulpo.club"


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


def render_html(issue: Issue) -> str:
    locale = issue.locale
    head_title = f"Pulpo — Issue {issue.issue_number:02d} · {issue.issue_date_human}"
    issue_strip = i18n.t(
        "header.issue", locale, n=f"{issue.issue_number:02d}", date=issue.issue_date_human.upper()
    )

    rich_html = "".join(_rich_pick(p, locale=locale, paywall_url=issue.paywall_target_url) for p in issue.picks_top)
    shortlist_html = ""
    if issue.picks_shortlist:
        sl_eb = i18n.t("shortlist.eyebrow", locale, n=len(issue.picks_shortlist))
        sl_hl = i18n.t("shortlist.headline", locale)
        sl_lede = i18n.t("shortlist.lede", locale)
        shortlist_header = f"""
        <tr><td class="pad" style="padding-top: 16px; padding-bottom: 4px;">
          <hr class="rule" />
          <div style="margin-top: 12px;">
            <div class="eyebrow">{_e(sl_eb)}</div>
            <h2 class="h1">{_e(sl_hl)}</h2>
            <p class="body-2" style="margin-top: 6px; max-width: 480px;">{_e(sl_lede)}</p>
          </div>
        </td></tr>
        """
        shortlist_rows = "".join(_short_pick(p, locale=locale, paywall_url=issue.paywall_target_url) for p in issue.picks_shortlist)
        shortlist_html = shortlist_header + shortlist_rows

    hero_block = f"""
    <tr><td class="pad" style="padding-top: 28px; padding-bottom: 20px;">
      <div class="eyebrow">{_e(issue.commentary.eyebrow_hero)}</div>
      <h1 class="h-hero">{_e(issue.commentary.headline_hero)}</h1>
      <p class="lede" style="margin: 4px 0 14px; max-width: 540px;">{issue.commentary.lede_hero}</p>
      {_filter_chips_html(issue.commentary.filter_chips)}
    </td></tr>
    """

    # Brand mark: a tentacle coiled around the gold catch. Inline SVG so
    # email clients render it without external assets. Hex colors only —
    # most clients strip CSS vars from inline styles.
    header_strip = f"""
    <tr><td class="pad-sm" style="border-bottom: 1px solid var(--line);">
      <table width="100%" role="presentation"><tr>
        <td style="vertical-align: middle;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align: middle; padding-right: 10px; line-height: 0;">
              <svg width="26" height="26" viewBox="-50 -50 100 100" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                <path d="M -38 0 C -38 -21, -21 -38, 0 -38 C 21 -38, 38 -21, 38 0 C 38 17, 24 30, 7 30 C -8 30, -18 18, -18 4 C -18 -8, -8 -18, 4 -18 C 12 -18, 18 -12, 18 -4" stroke="#1F3D31" stroke-width="8.5" stroke-linecap="round" fill="none"/>
                <circle cx="18" cy="-4" r="9.5" fill="#1F3D31"/>
                <circle cx="18" cy="-4" r="5.5" fill="#D4A04A"/>
              </svg>
            </td>
            <td style="vertical-align: middle;">
              <span class="display" style="font-size: 24px; font-weight: 700; letter-spacing: -0.035em; color: #1F3D31; line-height: 1; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;">pulpo</span>
            </td>
          </tr></table>
        </td>
        <td align="right" style="vertical-align: middle;">
          <span class="mono" style="font-size: 11px; color: var(--ink-3); letter-spacing: 0.08em;">{_e(issue_strip)}</span>
        </td>
      </tr></table>
    </td></tr>
    """

    # v3 layout order (Sebas's 5 fixes, 2026-05-29):
    #   header → hero (welcome teaser) → MARKET CONTEXT → top 3 picks →
    #   paywall banner (if free) → shortlist → skip → next issue →
    #   your pulpo → footer.
    #
    # Fix #5: market context moved up from just-above-the-footer to
    # right after the welcome teaser. That gives the reader the "why
    # this fortnight" framing BEFORE they see any listing.
    #
    # Dropped from v2: the `<table class="glance">` numbered-list block
    # (the welcome teaser already names #01-#03 and the per-pick
    # sections cover the rest) and the `_one_number_html` block (the
    # "$X per m² median" callout duplicated the market_context data dump
    # the user called "horrible" — the warm market note carries the load).
    return f"""<!doctype html>
<html lang="{locale}">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="x-pulpo-template" content="{_e(TEMPLATE_VERSION)}" />
<title>{_e(head_title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Instrument+Serif:ital@0;1&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet" />
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <table class="frame" role="presentation" cellpadding="0" cellspacing="0" width="680">
    {header_strip}
    {hero_block}
    {_market_html(issue)}
    {rich_html}
    {_paywall_banner_html(issue)}
    {shortlist_html}
    {_skip_block_html(issue)}
    {_next_issue_html(issue)}
    {_your_pulpo_html(issue)}
    {_footer_html(issue)}
  </table>
</div>
</body>
</html>
"""
