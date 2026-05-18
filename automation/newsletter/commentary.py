"""Editorial commentary for one issue — paragraphs that aren't tied to a
single listing.

Two modes:
  • `deterministic`: builds copy from facts already in ranked.json (zone deltas,
    counts, repricing rate, freshest source). No external API. PR-NL-2 default.
  • `llm`: PR-NL-3 — calls DeepSeek with a temperature-0.2 seed of
    (issue_id, recipient_hash). Same provider as automation/llm_enrichment.py
    so we get the same prefix-cache + cost telemetry.

The deterministic path is intentionally a little dry — it's the safe baseline.
The LLM path inherits the editorial voice from the example draft.
"""

from __future__ import annotations

import statistics
from typing import Optional

from .types import Commentary, Locale, Preference
from . import i18n


def deterministic_commentary(
    *,
    cohort: str,
    locale: Locale,
    pref: Preference,
    display_name: Optional[str],
    n_scanned: int,
    picks: list[dict],
    skip_pick: Optional[dict],
) -> Commentary:
    # Hero block ────────────────────────────────────────────────────────
    if cohort == "anonymous":
        eyebrow = i18n.t("hero.eyebrow.anon", locale)
    elif display_name:
        eyebrow = i18n.t("hero.eyebrow.named", locale, name=display_name)
    else:
        eyebrow = i18n.t("hero.eyebrow.unnamed", locale)
    headline = i18n.t("hero.headline.default", locale)
    lede_key = "hero.lede.with_prefs" if (pref.zones or pref.departments or pref.max_price_usd or pref.categories or pref.property_types) else "hero.lede.no_prefs"
    lede = i18n.t(lede_key, locale, n_scanned=n_scanned)

    # Filter chips — render the same Preference summary the footer uses
    chips: list[str] = []
    for d in pref.departments[:1]:
        chips.append(d.title())
    for z in pref.zones[:2]:
        chips.append(z.replace("-", " ").title())
    if pref.max_price_usd:
        chips.append(("Hasta " if locale == "es" else "Under ") + f"${int(pref.max_price_usd):,}")
    if "land" in pref.property_types:
        chips.append(("Terreno OK" if locale == "es" else "Land OK"))
    for c in pref.categories[:2]:
        chips.append(c.replace("_", " ").title())

    # At-a-glance subhead ───────────────────────────────────────────────
    kept_n = len(picks)
    subhead = i18n.t(
        "glance.subhead.with_skip" if skip_pick else "glance.subhead.no_skip",
        locale,
        kept=kept_n,
    )

    # Skip block ────────────────────────────────────────────────────────
    skip_headline: Optional[str] = None
    skip_blurb: Optional[str] = None
    if skip_pick:
        tc = skip_pick.get("title_canonical") or {}
        skip_headline = tc.get(locale) or tc.get("en") or skip_pick.get("title", "—")
        dom = skip_pick.get("days_listed") or 0
        zone_pct = skip_pick.get("price_vs_zone_pct")
        dq = skip_pick.get("data_quality_score")
        bits: list[str] = []
        if dom >= 90:
            bits.append(
                f"{dom} días en el mercado" if locale == "es" else f"{dom} days on market"
            )
        if zone_pct is not None and zone_pct > 25:
            bits.append(
                f"+{zone_pct:.0f}% sobre la mediana de zona" if locale == "es" else f"+{zone_pct:.0f}% above zone median"
            )
        if dq is not None and dq < 0.55:
            bits.append("data quality borderline" if locale == "en" else "calidad de datos justa")
        if not bits:
            bits.append("no clear edge at ask" if locale == "en" else "sin clara ventaja al precio de lista")
        skip_blurb = " · ".join(bits).capitalize() + "."

    # Market context ─────────────────────────────────────────────────────
    market: list[str] = []
    if picks:
        # 1) freshness: how many of the kept picks are new this fortnight
        new_count = sum(1 for p in picks if p.get("_is_new_window"))
        if new_count:
            market.append(
                f"{new_count} of these {len(picks)} listings landed inside the last 14 days."
                if locale == "en"
                else f"{new_count} de estas {len(picks)} apareció en los últimos 14 días."
            )
        # 2) value spread: median price vs zone delta on the kept list
        deltas = [p.get("price_vs_zone_pct") for p in picks if isinstance(p.get("price_vs_zone_pct"), (int, float))]
        if deltas:
            med = statistics.median(deltas)
            if med < -10:
                market.append(
                    f"Median pick prices {abs(med):.0f}% below the zone median — the issue leans value over polish."
                    if locale == "en"
                    else f"Las selecciones están {abs(med):.0f}% bajo la mediana de zona — esta edición se inclina al valor sobre el acabado."
                )
            elif med > 10:
                market.append(
                    f"Median pick is priced {med:.0f}% above zone — quality over discount this fortnight."
                    if locale == "en"
                    else f"Las selecciones están {med:.0f}% sobre la zona — calidad por encima de descuento."
                )
        # 3) momentum hint: any repriced?
        repriced = sum(1 for p in picks if p.get("is_repriced"))
        if repriced:
            market.append(
                f"{repriced} listings have moved on price since first scan — the sellers are negotiable."
                if locale == "en"
                else f"{repriced} propiedades han movido el precio — los vendedores están abiertos."
            )

    # One-number block ──────────────────────────────────────────────────
    one_title: Optional[str] = None
    one_body: Optional[str] = None
    ppms = [p.get("price_per_m2") for p in picks if isinstance(p.get("price_per_m2"), (int, float))]
    if ppms:
        med_ppm = statistics.median(ppms)
        one_title = (
            f"${med_ppm:,.0f} per m² — the median across your top {len(picks)}."
            if locale == "en"
            else f"${med_ppm:,.0f} por m² — la mediana de tus {len(picks)} principales."
        )
        one_body = (
            "Use this as the anchor when a broker quotes outside the band."
            if locale == "en"
            else "Úsalo como ancla cuando un corredor cotice fuera de la banda."
        )

    return Commentary(
        eyebrow_hero=eyebrow,
        headline_hero=headline,
        lede_hero=lede,
        filter_chips=chips,
        glance_subhead=subhead,
        skip_headline=skip_headline,
        skip_blurb=skip_blurb,
        market_context=market,
        one_number_title=one_title,
        one_number_body=one_body,
    )


def pick_callouts_for_listing(listing: dict, locale: Locale) -> list[dict]:
    """A small set of structured callouts derived deterministically from
    listing facts. The LLM path (PR-NL-3) extends this with editorial copy
    like "Three things have to be true" and "The catch".
    """
    out: list[dict] = []
    reasons = listing.get("reasons_to_buy") or []
    if reasons:
        bullets = []
        for r in reasons[:3]:
            txt = r.get(locale) or r.get("en") if isinstance(r, dict) else None
            if txt:
                bullets.append(txt)
        if bullets:
            out.append({
                "label": "Reasons to buy" if locale == "en" else "Razones para comprar",
                "body": " · ".join(bullets),
            })

    zone_pct = listing.get("price_vs_zone_pct")
    if isinstance(zone_pct, (int, float)) and abs(zone_pct) >= 15:
        if zone_pct < 0:
            out.append({
                "label": "The price story" if locale == "en" else "El precio",
                "body": (
                    f"Listed at {abs(zone_pct):.0f}% below the zone median per m². "
                    "Compare against the comps before assuming it's mispriced."
                    if locale == "en"
                    else f"Listado a {abs(zone_pct):.0f}% bajo la mediana por m². "
                    "Compara con los comps antes de asumir mal precio."
                ),
            })

    rank_reasons = listing.get("rank_reasons") or []
    if rank_reasons:
        out.append({
            "label": "Why Pulpo ranked it" if locale == "en" else "Por qué Pulpo lo clasifica",
            "body": " · ".join(rr.split(" (")[0] for rr in rank_reasons[:3]),
        })

    return out[:2]  # keep the email scannable
