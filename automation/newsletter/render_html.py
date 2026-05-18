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


_CSS = """
:root {
  --paper:        #F4EFE6;
  --paper-2:      #F8F4EC;
  --paper-3:      #EEE9DF;
  --white:        #FFFFFF;
  --ink:          #1A1916;
  --ink-2:        #5A5650;
  --ink-3:        #888780;
  --line:         rgba(0, 0, 0, 0.08);
  --line-2:       rgba(0, 0, 0, 0.14);
  --forest:       #1F3D31;
  --forest-mid:   #3D6450;
  --sage:         #DDE9DC;
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
.wrap   { width: 100%; background: var(--paper); padding: 32px 0; }
.frame  { width: 100%; max-width: 680px; margin: 0 auto; background: var(--white); border: 1px solid var(--line); }
.pad    { padding: 40px 48px; }
.pad-md { padding: 28px 48px; }
.pad-sm { padding: 18px 48px; }
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
.rule-clay   { border: 0; border-top: 2px solid var(--clay); width: 56px; margin: 0; }
.eyebrow {
  font-family: var(--font-mono);
  font-size: 11px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--forest);
  font-weight: 500;
}
.eyebrow.clay { color: var(--clay); }
.eyebrow.muted { color: var(--ink-3); }
.h-hero  { font-family: var(--font-display); font-size: 56px; line-height: 1.02; letter-spacing: -0.015em; font-weight: 400; margin: 14px 0 12px; color: var(--ink); }
.h1      { font-family: var(--font-display); font-size: 40px; line-height: 1.08; letter-spacing: -0.012em; font-weight: 400; margin: 12px 0 8px; color: var(--ink); }
.h2      { font-family: var(--font-display); font-size: 30px; line-height: 1.12; letter-spacing: -0.01em; font-weight: 400; margin: 14px 0 6px; color: var(--ink); }
.h3      { font-family: var(--font-display); font-size: 22px; line-height: 1.18; letter-spacing: -0.005em; font-weight: 400; margin: 8px 0 4px; color: var(--ink); }
.lede    { font-family: var(--font-sans); font-size: 17px; line-height: 1.6; color: var(--ink); font-weight: 400; }
.body    { font-family: var(--font-sans); font-size: 15px; line-height: 1.65; color: var(--ink); }
.body-2  { font-family: var(--font-sans); font-size: 14px; line-height: 1.6; color: var(--ink-2); }
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
.cta {
  display: inline-block;
  font-family: var(--font-sans);
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  padding: 11px 18px;
  background: var(--button-dark);
  color: var(--button-text) !important;
  border-radius: 999px;
}
.cta:hover { background: var(--forest); text-decoration: none; }
.cta-ghost {
  display: inline-block;
  font-family: var(--font-sans);
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0.04em;
  padding: 10px 16px;
  background: transparent;
  color: var(--ink) !important;
  border: 1px solid var(--ink);
  border-radius: 999px;
}
.cta-ghost:hover { background: var(--ink); color: var(--paper) !important; text-decoration: none; }
.glance td { padding: 12px 0; border-bottom: 1px solid var(--line); font-family: var(--font-sans); font-size: 14px; vertical-align: top; color: var(--ink); }
.glance .num { font-family: var(--font-mono); color: var(--clay); font-weight: 500; width: 32px; font-size: 12px; padding-top: 14px; }
.glance .where { font-family: var(--font-mono); color: var(--ink-3); font-size: 11px; letter-spacing: 0.04em; }
.glance .pricecol { font-family: var(--font-display); font-size: 17px; color: var(--ink); white-space: nowrap; }
.keytable td { padding: 7px 14px 7px 0; vertical-align: top; }
.keytable .k { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--forest); padding-right: 10px; }
.keytable .v { font-family: var(--font-sans); font-size: 14px; color: var(--ink); }
.callout { background: var(--paper-2); padding: 18px 22px; border-left: 3px solid var(--clay); margin: 16px 0; }
.callout .label { font-family: var(--font-mono); font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--clay); }
.callout .body  { margin-top: 6px; font-size: 14.5px; line-height: 1.6; color: var(--ink); }
.paywall-banner { background: var(--forest); color: var(--paper); padding: 28px 32px; margin: 16px 0; border-radius: 6px; }
.paywall-banner .eyebrow { color: var(--sage); }
.paywall-banner .h2 { color: var(--paper); }
.paywall-banner .body { color: var(--paper-3); }
.paywall-banner .cta { background: var(--clay); color: var(--paper) !important; }
.footer-strip { background: var(--forest); color: var(--paper); }
.footer-strip .small { color: var(--paper-3); }
.footer-strip a { color: var(--paper); }
@media (max-width: 560px) {
  .pad, .pad-md, .pad-sm { padding-left: 22px; padding-right: 22px; }
  .h-hero { font-size: 40px; }
  .h1 { font-size: 30px; }
  .h2 { font-size: 24px; }
  .price { font-size: 26px; }
}
"""


def _pills_html(pills: list[str]) -> str:
    if not pills:
        return ""
    return "".join(f'<span class="pill">{_e(p)}</span>' for p in pills)


def _callouts_html(callouts: list[dict]) -> str:
    if not callouts:
        return ""
    out: list[str] = []
    for c in callouts:
        label = _e(c.get("label", ""))
        body = _e(c.get("body", ""))
        if not body:
            continue
        out.append(
            f'<div class="callout"><div class="label">{label}</div>'
            f'<div class="body">{body}</div></div>'
        )
    return "".join(out)


def _keytable_html(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    tds: list[str] = []
    for i, (k, v) in enumerate(rows):
        tds.append(f'<td class="k">{_e(k)}</td><td class="v">{_e(v)}</td>')
    # 2-column layout: pair adjacent rows
    paired = []
    for i in range(0, len(tds), 4):
        chunk = "".join(tds[i:i + 4])
        paired.append(f"<tr>{chunk}</tr>")
    return f'<table class="keytable" role="presentation" style="margin-top: 14px;">{"".join(paired)}</table>'


def _photo_html(pick: IssuePick) -> str:
    if not pick.photo_url:
        return ""
    return f'<img src="{_e(pick.photo_url)}" alt="{_e(pick.title)}" width="680" />'


def _photo_html_short(pick: IssuePick) -> str:
    if not pick.photo_url:
        return ""
    return f'<img src="{_e(pick.photo_url)}" alt="{_e(pick.title)}" width="100%" />'


def _new_pill(pick: IssuePick, locale: Locale) -> str:
    if pick.is_repriced:
        return f'<span class="pill pill-clay">{_e(i18n.t("pick.repriced_pill", locale))}</span>'
    if pick.is_new_this_fortnight:
        return f'<span class="pill pill-forest">{_e(i18n.t("pick.new_pill", locale))}</span>'
    return ""


def _cta_for_pick(pick: IssuePick, locale: Locale, paywall_url: str, ghost: bool = False) -> str:
    klass = "cta-ghost" if ghost else "cta"
    if pick.paywalled:
        label = i18n.t("pick.cta_locked", locale)
        href = paywall_url + f"&pick={pick.rank}"
        return f'<a class="{klass}" href="{_e(href)}">{_e(label)}</a>'
    label = i18n.t("pick.cta_open", locale)
    return f'<a class="{klass}" href="{_e(pick.listing_url)}">{_e(label)}</a>'


def _rich_pick(pick: IssuePick, *, locale: Locale, paywall_url: str) -> str:
    top_label = i18n.t("pick.top_label", locale, rank=pick.rank)
    pills_html = (
        f'<span class="pill pill-forest">{_e(top_label)}</span>'
        + _new_pill(pick, locale)
        + _pills_html(pick.pills)
    )

    callouts_html = "" if pick.paywalled else _callouts_html(pick.callouts)
    keytable_html = "" if pick.paywalled else _keytable_html(pick.keytable)
    blurb_html = (
        f'<p class="body" style="margin-top: 22px;">{_e(pick.blurb)}</p>'
        if not pick.paywalled and pick.blurb
        else ""
    )
    if pick.paywalled:
        paywall_blurb = i18n.t("pick.paywall_blurb", locale)
        blurb_html = (
            f'<p class="body" style="margin-top: 22px; color: var(--ink-2);">{_e(paywall_blurb)}</p>'
        )

    price_note_html = (
        f'<span class="price-note"> · {_e(pick.price_note)}</span>' if pick.price_note else ""
    )

    return f"""
    <tr><td style="padding: 36px 0 0 0;">{_photo_html(pick)}</td></tr>
    <tr><td class="pad" style="padding-top: 28px;">
      <div>{pills_html}</div>
      <h2 class="h1">{_e(pick.title)}</h2>
      <div class="meta" style="margin: 6px 0 16px;">{_e(pick.location_line)}</div>
      <div class="price">{_e(pick.price_text)}{price_note_html}</div>
      {blurb_html}
      {callouts_html}
      {keytable_html}
      <p style="margin-top: 22px;">{_cta_for_pick(pick, locale, paywall_url)}</p>
    </td></tr>
    <tr><td class="pad-sm"><hr class="rule" /></td></tr>
    """


def _short_pick(pick: IssuePick, *, locale: Locale, paywall_url: str) -> str:
    eyebrow_text = ""  # not yet generated deterministically — PR-NL-3 LLM hook
    pills_html = _new_pill(pick, locale) + _pills_html(pick.pills[:2])
    blurb_html = ""
    if pick.paywalled:
        blurb_html = f'<p class="body-2" style="margin: 8px 0 0;">{_e(i18n.t("pick.paywall_blurb", locale))}</p>'
    elif pick.blurb:
        blurb_html = f'<p class="body-2" style="margin: 8px 0 0;">{_e(pick.blurb)}</p>'
    price_note_html = (
        f'<span class="price-note"> · {_e(pick.price_note)}</span>' if pick.price_note else ""
    )
    eyebrow_html = (
        f'<div class="eyebrow">{_e(eyebrow_text)}</div>' if eyebrow_text else ""
    )
    return f"""
    <tr><td class="pad-md">
      <table width="100%" role="presentation"><tr>
        <td width="38%" style="vertical-align: top; padding-right: 22px;">{_photo_html_short(pick)}</td>
        <td style="vertical-align: top;">
          {eyebrow_html}
          <h3 class="h3" style="margin-top: 6px;">{_e(pick.title)}</h3>
          <div class="price-2" style="margin: 6px 0;">{_e(pick.price_text)}{price_note_html}</div>
          {('<div>' + pills_html + '</div>') if pills_html else ''}
          {blurb_html}
          <p style="margin-top: 12px;">{_cta_for_pick(pick, locale, paywall_url, ghost=True)}</p>
        </td>
      </tr></table>
    </td></tr>
    <tr><td class="pad-sm"><hr class="rule" /></td></tr>
    """


def _glance_html(rows: list[dict]) -> str:
    if not rows:
        return ""
    out: list[str] = []
    for r in rows:
        muted = r.get("muted", False)
        num_style = ' style="color: var(--ink-3);"' if muted else ""
        price_style = ' style="color: var(--ink-3);"' if muted else ""
        out.append(
            f'<tr>'
            f'<td class="num"{num_style}>{_e(r["num"])}</td>'
            f'<td><strong>{_e(r["title"])}</strong><br/>'
            f'<span class="where">{_e(r["where"])}</span></td>'
            f'<td align="right" class="pricecol"{price_style}>{_e(r["price"])}</td>'
            f'</tr>'
        )
    return "".join(out)


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
    <tr><td class="pad" style="padding-top: 24px; padding-bottom: 0;">
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
    <tr><td class="pad" style="padding-top: 36px;">
      <hr class="rule" />
      <div style="margin-top: 28px;">
        <div class="eyebrow clay">{_e(eb)}</div>
        <h2 class="h1">{_e(headline)}</h2>
        <div class="meta" style="margin: 6px 0 16px; color: var(--clay);">{_e(sp.price_text)} · {_e(sp.location_line)}</div>
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
    para_html = "".join(f'<p class="body">{_e(p)}</p>' for p in paras)
    return f"""
    <tr><td class="pad" style="background: var(--paper-2); padding-top: 36px; padding-bottom: 36px;">
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
    <tr><td class="pad" style="padding-top: 36px;">
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
      <p class="small" style="color: var(--paper-3);">{_e(tagline)}</p>
      <p class="small" style="color: var(--paper-3); margin-top: 8px;">{_e(you_line)}</p>
      <p class="small" style="margin-top: 14px;">
        <a href="{_e(issue.settings_url)}">{_e(change_filters_label)}</a> &middot;
        <a href="{_e(issue.settings_url)}">{_e(change_cadence_label)}</a> &middot;
        <a href="{_e(issue.unsubscribe_url)}">{_e(unsubscribe_label)}</a>
      </p>
      <p class="small" style="color: var(--paper-3); margin-top: 18px;">{_e(no_commission)}</p>
      <p class="small" style="color: var(--paper-3); margin-top: 18px;">{_e(copyright_line)} &middot; <span class="mono">pulpo.club</span></p>
    </td></tr>
    """


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
    <tr><td class="pad" style="padding-top: 24px; padding-bottom: 36px;">
      <hr class="rule" />
      <div style="margin-top: 24px;">
        <div class="eyebrow">{_e(eb)}</div>
        <p class="body" style="max-width: 520px;">{_e(body)}</p>
        <p style="margin-top: 16px;"><a class="cta-ghost" href="{_e(href)}">{_e(cta_label)}</a></p>
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
        sl_eb = i18n.t("shortlist.eyebrow", locale)
        sl_hl = i18n.t("shortlist.headline", locale, n=len(issue.picks_shortlist))
        sl_lede = i18n.t("shortlist.lede", locale)
        shortlist_header = f"""
        <tr><td class="pad" style="padding-top: 36px; padding-bottom: 4px;">
          <hr class="rule" />
          <div style="margin-top: 28px;">
            <div class="eyebrow">{_e(sl_eb)}</div>
            <h2 class="h1">{_e(sl_hl)}</h2>
            <p class="body-2" style="margin-top: 8px; max-width: 480px;">{_e(sl_lede)}</p>
          </div>
        </td></tr>
        """
        shortlist_rows = "".join(_short_pick(p, locale=locale, paywall_url=issue.paywall_target_url) for p in issue.picks_shortlist)
        shortlist_html = shortlist_header + shortlist_rows

    glance_eb = i18n.t("glance.eyebrow", locale)
    glance_block = ""
    if issue.glance:
        glance_block = f"""
        <tr><td class="pad" style="padding-top: 8px; padding-bottom: 8px;">
          <hr class="rule" />
          <div style="margin-top: 24px;">
            <div class="eyebrow">{_e(glance_eb)}</div>
            <h2 class="h2">{_e(issue.commentary.glance_subhead)}</h2>
            <table class="glance" width="100%" role="presentation" style="margin-top: 16px;">
              {_glance_html(issue.glance)}
            </table>
          </div>
        </td></tr>
        """

    hero_block = f"""
    <tr><td class="pad" style="padding-top: 56px; padding-bottom: 36px;">
      <div class="eyebrow">{_e(issue.commentary.eyebrow_hero)}</div>
      <h1 class="h-hero">{_e(issue.commentary.headline_hero)}</h1>
      <hr class="rule-clay" style="margin: 8px 0 22px;" />
      <p class="lede" style="margin: 0 0 18px; max-width: 540px;">{_e(issue.commentary.lede_hero)}</p>
      {_filter_chips_html(issue.commentary.filter_chips)}
    </td></tr>
    """

    header_strip = f"""
    <tr><td class="pad-sm" style="border-bottom: 1px solid var(--line);">
      <table width="100%" role="presentation"><tr>
        <td style="vertical-align: middle;">
          <span class="display" style="font-size: 24px; font-weight: 500; letter-spacing: -0.02em; color: #1F3D31; line-height: 1;">pulpo</span>
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
    {glance_block}
    {rich_html}
    {_paywall_banner_html(issue)}
    {shortlist_html}
    {_skip_block_html(issue)}
    {_market_html(issue)}
    {_one_number_html(issue)}
    {_next_issue_html(issue)}
    {_footer_html(issue)}
  </table>
</div>
</body>
</html>
"""
