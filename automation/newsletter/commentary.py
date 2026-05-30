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
    # v3.1.1 (2026-05-29): lede_hero is the warm two-sentence intro
    # that names the scan size + location context, then sets the
    # structural shape (full reads vs quick scans). Pre-picks redundancy
    # was the bug the first v3 take introduced — this version threads
    # `n_scanned` and `pref` through so the lede reads concrete without
    # repeating per-pick detail. Falls back to the static i18n template
    # when the picks list is empty.
    if picks:
        lede = deterministic_welcome_teaser(
            picks, locale, n_scanned=n_scanned, pref=pref
        )
    else:
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
    # v3.1 (2026-05-29): collapsed to ONE paragraph. The v2.8 send
    # surfaced four paragraphs — a warm framing line plus three data
    # stats — and Sebas's review called the data-stat paragraphs
    # redundant filler. The single paragraph now names the most
    # striking 1–2 picks of the week (with links the renderer wires
    # in), and stops.
    market: list[str] = []
    if picks:
        market.append(deterministic_market_note(picks, locale))

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
            else "Usalo como ancla cuando un corredor te cotice fuera de la banda."
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

    # v3.2 (2026-05-29) — DROPPED the "Price story" callout entirely.
    # Sebas: "never repeat numbers." The same X% was getting stamped
    # three times per pick:
    #   1. cool-toned "−X% under area average" chip above the title
    #   2. "Priced X% below the area average" bullet in the Why list
    #      (also dropped in deterministic_why_for_pick — see that fn)
    #   3. "Listed at X% below the zone median per m²" body in the
    #      "Price story" callout right below the Why list
    # The chip wins; the why-list and price-story echoes are gone.
    # zone_pct stays addressable in the listing dict for downstream
    # use, but no longer renders a callout here.

    rank_reasons = listing.get("rank_reasons") or []
    if rank_reasons:
        out.append({
            "label": "Why Pulpo ranked it" if locale == "en" else "Por qué Pulpo lo clasifica",
            "body": " · ".join(rr.split(" (")[0] for rr in rank_reasons[:3]),
        })

    return out[:2]  # keep the email scannable


def deterministic_why_for_pick(listing: dict, locale: Locale = "en") -> list[str]:
    """Three plain-English bullets answering "why did Pulpo pick this?".

    Replaces the v2.x callout that surfaced the analyst-y rank-reasons
    string ("value 100 · location 100 · momentum 50"). Each bullet maps
    1:1 to a real Listing field — never to a rank score, never to
    fabricated content — so any claim a reader makes about the bullet
    is verifiable.

    Priority order (we keep up to three):
      1. **Price** — `price_vs_zone_pct` below the area average. Lead
         with this when the discount is meaningful (≥ 15%); it's the
         single most common reason a buyer cares.
      2. **Price drop** — `is_repriced` + `previous_price`. A fresh
         seller move is more interesting than a stale list price.
      3. **Coastal proximity** — `is_walk_to_beach`, `is_beachfront`,
         or `dist_beach_km < 25` with a minute-walk estimate.
      4. **Build-ready** — `readiness_score >= 3`. "Power and water
         already in" is plain-language gold for raw-land buyers.
      5. **Year-round water** — coffee/mountain land with a river or
         well surfaced through `has_water` + mountain heuristics.
      6. **Fresh listing** — `_is_new_window` / `days_listed <= 7`.
      7. **Property-type fit** — beds/baths/built area for houses,
         lot size for land. Last-resort fact so the why_block never
         renders empty.

    The output is locale-aware. Bullets are kept short (one phrase,
    no leading "Has" / "It's") because the renderer wraps them in a
    `<ul>` with a `✓` glyph — sentence-style copy would feel heavy.
    """
    en = locale == "en"
    out: list[str] = []

    # 1) v3.2 (2026-05-29) — DROPPED the "Priced N% below the area
    # average" bullet. Same number already lives on the cool-toned
    # "−N% under area average" chip above the listing title; emitting
    # it again in the why-list bullets AND a third time in the "Price
    # story" callout (also dropped in pick_callouts_for_listing) was
    # the loudest dedupe issue in the v3.1 send. The chip is the
    # canonical surface; this section now focuses on the OTHER reasons
    # Pulpo picked the listing (beach proximity, readiness, freshness,
    # property fit). If those signals are absent, the property-fit
    # fallback at the bottom keeps the why-list from rendering empty.

    # 2) Recent price drop — concrete number, not "momentum".
    if listing.get("is_repriced"):
        prev = listing.get("previous_price")
        cur = listing.get("price_usd")
        if isinstance(prev, (int, float)) and isinstance(cur, (int, float)) and prev > cur:
            delta_pct = (prev - cur) / prev * 100
            delta_usd = int(prev - cur)
            if delta_pct >= 10:
                line = (f"Price just dropped {delta_pct:.0f}% — usually not the last cut"
                        if en
                        else f"El precio bajó {delta_pct:.0f}% — rara vez es el último ajuste")
            else:
                line = (f"Price just dropped ${delta_usd:,} — first move on this listing"
                        if en
                        else f"El precio bajó ${delta_usd:,} — primer movimiento en la ficha")
            out.append(line)

    # 3) Coastal proximity.
    if listing.get("is_beachfront"):
        out.append("Beachfront — no walk, no drive" if en else "Frente al mar — sin caminata, sin carro")
    elif listing.get("is_walk_to_beach"):
        beach = listing.get("nearest_beach") or listing.get("named_beach_nearest")
        beach_km = listing.get("dist_beach_km")
        if isinstance(beach_km, (int, float)):
            mins = max(1, int(round(beach_km * 12)))
            if isinstance(beach, str) and beach:
                out.append(
                    f"{mins}-minute walk to {beach} — no car needed"
                    if en
                    else f"A {mins} minutos a pie de {beach} — sin necesidad de carro"
                )
            else:
                out.append(
                    f"{mins}-minute walk to the beach — no car needed"
                    if en
                    else f"A {mins} minutos a pie de la playa — sin necesidad de carro"
                )
        else:
            out.append(
                "Walking distance to the beach — no car needed"
                if en
                else "A pie de la playa — sin necesidad de carro"
            )
    else:
        beach_km = listing.get("dist_beach_km")
        if isinstance(beach_km, (int, float)) and beach_km < 15:
            mins = max(1, int(round(beach_km * 1.1)))
            out.append(
                f"{mins} min to the nearest beach"
                if en
                else f"A {mins} min de la playa más cercana"
            )

    # 4) Build-ready — power+water+road already in.
    readiness = listing.get("readiness_score")
    if isinstance(readiness, int) and readiness >= 3:
        out.append(
            "Power, water and road already in — no infrastructure project"
            if en
            else "Luz, agua y carretera ya en el lote — sin obra de infraestructura"
        )
    elif isinstance(readiness, int) and readiness == 2:
        has = []
        if listing.get("has_power"):
            has.append("power" if en else "luz")
        if listing.get("has_water"):
            has.append("water" if en else "agua")
        if has:
            joined = " and ".join(has) if en else " y ".join(has)
            out.append(
                f"{joined.capitalize()} already at the lot — you just add the road"
                if en
                else f"{joined.capitalize()} ya en el lote — falta solo la carretera"
            )

    # 5) Fresh inventory.
    dom = listing.get("days_listed")
    if listing.get("_is_new_window") or (isinstance(dom, int) and dom <= 7):
        out.append(
            "Brand new this week — early window matters"
            if en
            else "Nueva esta semana — la ventana temprana importa"
        )

    # 6) Property-fit fallback so the why_block never renders empty.
    if not out:
        pt = listing.get("property_type")
        if pt == "land" and listing.get("area_m2"):
            area = int(listing["area_m2"])
            out.append(
                f"{area:,} m² lot at this price — uncommon for the area"
                if en
                else f"{area:,} m² a este precio — poco común para el área"
            )
        elif pt in ("house", "condo"):
            beds = listing.get("bedrooms")
            baths = listing.get("bathrooms")
            built = listing.get("built_area_m2")
            if isinstance(beds, int) and isinstance(baths, (int, float)):
                line = (f"{beds}-bed, {int(baths)}-bath" if en
                        else f"{beds} habitaciones, {int(baths)} baños")
                if isinstance(built, (int, float)):
                    line += (f" · {int(built)} m² built" if en
                             else f" · {int(built)} m² construidos")
                out.append(line)

    # Cap at 3 — the renderer's `.why-list` is sized for three lines.
    return out[:3]


def deterministic_shortlist_frame(listing: dict, locale: Locale = "en") -> str:
    """Single "For the buyer who…" line for one shortlist entry.

    v3.2 (2026-05-29): the v3.1 send rendered all seven shortlist cards
    with the IDENTICAL "wants the coastal vibe without the beachfront
    price" line because the near-beach-land branch caught everything in
    a typical La-Libertad coastal filter. This rewrite:

      1. Drops the `<em>` wrapping. Italics are banned from copy.
      2. Adds finer-grained branches inside the near-beach-land bucket
         so listings differentiate on real signals — area, distance,
         repriced state, days-on-market — instead of all collapsing to
         the same fallback.
      3. Falls through to a deterministic-by-source_id tie-breaker so
         even when multiple listings share a branch, they still print
         distinct wording. The tie-breaker keeps the output stable
         across renders (same listing → same line) without needing
         issue-position state threaded through.

    The frame answers "who is this the right answer for?" — keeps the
    shortlist scannable for a buyer skimming for relevance. Every
    branch maps to real Listing fields; no invented buyer personas.

    Empty string is allowed (renderer falls back to `blurb`) so a
    listing missing the fields to support a frame still renders cleanly.

    Return value is plain text (post-v3.2). Renderer historically read
    it as trusted HTML for the <em>...</em> span — with the span gone,
    plain text is the safer contract.
    """
    en = locale == "en"
    pt = listing.get("property_type")
    pct = listing.get("price_vs_zone_pct")
    beach_km = listing.get("dist_beach_km")
    days = listing.get("days_listed")
    area = listing.get("area_m2")
    is_repriced = bool(listing.get("is_repriced"))
    is_walk_to_beach = bool(listing.get("is_walk_to_beach"))
    is_beachfront = bool(listing.get("is_beachfront"))
    beach = listing.get("nearest_beach") or listing.get("named_beach_nearest")

    # Beachfront — its own tier. Rare enough to deserve a unique frame.
    if is_beachfront:
        return (
            "For the buyer who wants the sand at the front gate, not a drive away."
            if en
            else "Para quien quiere la arena en la puerta, no a unos minutos en carro."
        )

    # Repriced + slow seller → the "waiting for sellers to blink" buyer.
    if is_repriced and isinstance(days, int) and days >= 60:
        return (
            "For the buyer waiting for sellers to blink — this one already did."
            if en
            else "Para quien espera a que el vendedor parpadee — este ya lo hizo."
        )

    # Long days on market without a price move yet → patience pays.
    if isinstance(days, int) and days >= 90 and not is_repriced:
        return (
            "For the buyer betting the seller's patience runs out before theirs."
            if en
            else "Para quien apuesta a que la paciencia del vendedor se agota antes que la suya."
        )

    # Deep discount + walk-to-surf — surf-side land at a striking price.
    if is_walk_to_beach and isinstance(pct, (int, float)) and pct <= -30:
        if isinstance(beach, str) and beach:
            return (
                f"For the buyer who wants {beach}-area land at a striking price."
                if en
                else f"Para quien busca terreno cerca de {beach} a precio destacado."
            )
        return (
            "For the buyer who wants surf-side land without paying surf-side prices."
            if en
            else "Para quien quiere terreno cerca del mar sin pagar precio de mar."
        )

    # House / condo → move-in-ready buyer.
    if pt in ("house", "condo"):
        return (
            "For the buyer who doesn't want to build — move-in ready, no project."
            if en
            else "Para quien no quiere construir — listo para entrar, sin obra."
        )

    # Far-from-beach raw land → developer-mindset acreage buyer.
    if pt == "land" and isinstance(beach_km, (int, float)) and beach_km >= 25:
        if isinstance(area, (int, float)) and area >= 5000:
            return (
                "For the buyer with a build budget — the land alone is the deal."
                if en
                else "Para quien tiene presupuesto de construcción — el valor está en el terreno."
            )
        return (
            "For the buyer who's after acreage, not a build site."
            if en
            else "Para quien busca hectáreas, no un sitio para construir."
        )

    # Near-beach land — the v3.1 catch-all bucket. v3.2 splits this
    # into FOUR distinct frames based on real listing facts (area,
    # distance, named-beach proximity) so listings that share the
    # bucket still get different wording.
    if pt == "land":
        # Large-acreage cliff/view land → developer mindset.
        if isinstance(area, (int, float)) and area >= 5000:
            return (
                "For the developer-minded buyer with a vision big enough for several thousand square meters."
                if en
                else "Para el comprador con visión suficiente para varios miles de metros cuadrados."
            )
        # Tiny lot near a named beach → smallest footprint, biggest view.
        if isinstance(area, (int, float)) and area <= 800 and isinstance(beach_km, (int, float)) and beach_km < 10:
            return (
                "For the buyer who wants the smallest possible footprint with the biggest possible view."
                if en
                else "Para quien busca la huella más pequeña con la vista más amplia."
            )
        # Close to the surf (≤ 5 km), not walking distance → drive crowd.
        if isinstance(beach_km, (int, float)) and beach_km <= 5 and not is_walk_to_beach:
            if isinstance(beach, str) and beach:
                return (
                    f"For the buyer who wants {beach} proper — minutes away, not towns over."
                    if en
                    else f"Para quien quiere {beach} de verdad — a minutos, no a pueblos de distancia."
                )
            return (
                "For the buyer who wants the surf within a ten-minute drive, not on it."
                if en
                else "Para quien quiere el mar a diez minutos en carro, no encima."
            )
        # Mid-distance lot in a named beach corridor → frontier coast buyer.
        if isinstance(beach_km, (int, float)) and 5 < beach_km < 15:
            return (
                "For the buyer betting on the next stretch of coast before the road catches up."
                if en
                else "Para quien apuesta al siguiente tramo de costa antes de que llegue la vía."
            )
        # Default near-beach: coastal-feel-without-beachfront-price.
        return (
            "For the buyer who wants the coastal feel without paying for the beachfront."
            if en
            else "Para quien quiere el ambiente costero sin pagar precio de primera línea."
        )

    return ""


# ── PR-NL-6 · deterministic story paragraphs ────────────────────────
#
# Fallback for the warm hero-pick paragraph used when:
#   • PULPO_NEWSLETTER_USE_LLM is off
#   • LLM cost cap is exceeded
#   • DeepSeek returns an error (network, schema, finish_reason=length)
#
# Templates are picked by archetype (coastal land / mountain land /
# dropped-price / stale / built / generic). Each template wraps the
# emotional center sentence in <em>...</em>, which the renderer styles
# clay-deep italic so the eye lands there.
#
# Hard rule: every claim made by these templates must map to a real
# Listing field. No invented features. If we don't have the data, the
# template either skips the line or falls back to a more generic
# phrasing.


def _has_named_beach_nearby(listing: dict) -> str:
    """Return the named beach if the listing is close to one, else ''."""
    if not listing.get("is_walk_to_beach"):
        return ""
    # The pipeline tags walk-to-beach against the nearest named beach in
    # automation/distance_fields.py. Surface it when present so the story
    # can say "walk to El Tunco" instead of just "walk to the beach".
    nearest = listing.get("nearest_beach") or listing.get("named_beach_nearest")
    return nearest if isinstance(nearest, str) else ""


def _utility_phrase(listing: dict, locale: Locale) -> str:
    """Plain-language utility status — never hide the gap."""
    readiness = listing.get("readiness_score")
    has_power = listing.get("has_power")
    has_water = listing.get("has_water")
    has_road = listing.get("has_paved_access")
    if readiness == 3:
        return ("Water, power and a paved road are already there." if locale == "en"
                else "Agua, luz y carretera pavimentada ya en el lote.")
    if has_power and has_water:
        return ("Power and water are at the lot; you'd add the road." if locale == "en"
                else "Luz y agua en el lote; vos le ponés la carretera.")
    if has_power and has_road:
        return ("Power and the road are there; water you'd bring from a well." if locale == "en"
                else "Luz y carretera ya están; el agua la traés de un pozo.")
    if has_water and has_road:
        return ("Water and the road are at the lot; you'd run power from the nearest connection."
                if locale == "en"
                else "Agua y carretera ya en el lote; la luz la traés de la conexión más cercana.")
    if has_power:
        return ("Power runs to the boundary; water and the road are on you." if locale == "en"
                else "Luz hasta el límite; agua y carretera quedan por hacer.")
    if has_water:
        return ("Water is on site; you'd add power and the road." if locale == "en"
                else "Agua en el lote; falta meter luz y carretera.")
    return ("Bring a build budget — none of the utilities are in yet." if locale == "en"
            else "Traé presupuesto para construir — todavía no hay servicios.")


def _archetype(listing: dict) -> str:
    """Decide the listing's voice-target archetype."""
    if listing.get("is_repriced") and listing.get("previous_price"):
        return "dropped_price"
    if (listing.get("days_listed") or 0) > 180 and not listing.get("is_repriced"):
        return "stale"
    if listing.get("property_type") in ("house", "condo"):
        return "built"
    if listing.get("is_walk_to_beach") or listing.get("is_beachfront"):
        return "coastal"
    dept = (listing.get("department") or "").lower()
    if dept in ("morazán", "morazan", "chalatenango") or "highland" in dept:
        return "mountain"
    # Default for "raw land" — call coastal vs mountain by beach distance.
    beach_km = listing.get("dist_beach_km")
    if isinstance(beach_km, (int, float)) and beach_km <= 15:
        return "coastal"
    return "mountain"


def _price_under_phrase(listing: dict, locale: Locale) -> str:
    """How the deterministic templates name a below-zone price."""
    pct = listing.get("price_vs_zone_pct")
    if not isinstance(pct, (int, float)) or pct >= -15:
        return ""
    if pct <= -50:
        return ("well under what nearby lots are asking" if locale == "en"
                else "muy por debajo de lo que piden los lotes vecinos")
    if pct <= -30:
        return ("noticeably under the neighbors" if locale == "en"
                else "claramente debajo de los lotes vecinos")
    return ("a little under the area average" if locale == "en"
            else "un poco debajo del promedio del área")


def _drop_phrase(listing: dict, locale: Locale) -> str:
    """Concrete framing for a recent price drop."""
    prev = listing.get("previous_price")
    cur = listing.get("price_usd")
    if not (isinstance(prev, (int, float)) and isinstance(cur, (int, float)) and prev > cur):
        return ""
    delta_usd = int(prev - cur)
    delta_pct = (prev - cur) / prev * 100
    if delta_pct >= 10:
        return (f"the seller just lowered the price by {delta_pct:.0f}% — their first move on this listing"
                if locale == "en"
                else f"el vendedor acaba de bajar el precio un {delta_pct:.0f}% — su primer movimiento en esta ficha")
    return (f"the seller just lowered the price by ${delta_usd:,} — their first move on this listing"
            if locale == "en"
            else f"el vendedor acaba de bajar el precio en ${delta_usd:,} — su primer movimiento en esta ficha")


def deterministic_story_for_pick(listing: dict, locale: Locale = "en") -> str:
    """Per-archetype warm paragraph using only listing-data fields.

    Templates wrap a single emotional-center sentence in <em>...</em>
    so the renderer's `em` styling lands the reader's eye there.

    This is the safety net under llm_story.py — every error path in
    the LLM module funnels here. Operators can read this function to
    understand the worst-case voice quality."""
    arch = _archetype(listing)
    locale_en = locale == "en"

    # Sentence A — open with the dream / hook (NEVER price, NEVER rank).
    beach = _has_named_beach_nearby(listing)
    if arch == "coastal":
        if beach:
            line_a = (f"A short walk to {beach}." if locale_en
                      else f"A pie de la playa de {beach}.")
        elif listing.get("is_beachfront"):
            line_a = ("Right at the beach." if locale_en else "Justo en la playa.")
        else:
            km = listing.get("dist_beach_km")
            if isinstance(km, (int, float)) and km <= 15:
                mins = max(5, int(round(km * 1.3)))
                line_a = (f"A {mins}-minute drive to the surf." if locale_en
                          else f"A {mins} minutos del mar.")
            else:
                line_a = ("A property close to the coast." if locale_en
                          else "Una propiedad cerca de la costa.")
    elif arch == "mountain":
        line_a = ("Land in the highlands — the kind of place where the morning fog comes in low."
                  if locale_en else
                  "Tierra en las montañas — del tipo donde la niebla baja con la mañana.")
    elif arch == "dropped_price":
        drop = _drop_phrase(listing, locale)
        line_a = (f"On this one, {drop}." if drop else
                  ("The seller is moving on price." if locale_en else
                   "El vendedor está moviendo el precio."))
    elif arch == "stale":
        dom = listing.get("days_listed") or 0
        line_a = (f"The seller has been waiting {dom} days." if locale_en
                  else f"El vendedor lleva {dom} días esperando.")
    elif arch == "built":
        bd = listing.get("bedrooms")
        ba = listing.get("bathrooms")
        if bd and ba:
            line_a = (f"{bd} bedrooms and {int(ba)} bathrooms — room for a family."
                      if locale_en
                      else f"{bd} habitaciones y {int(ba)} baños — espacio para una familia.")
        else:
            line_a = ("A built property ready to live in." if locale_en
                      else "Una propiedad construida lista para habitar.")
    else:
        line_a = ("A property worth a closer look." if locale_en
                  else "Una propiedad que vale la pena revisar de cerca.")

    # Sentence B — the editorial center. v3.2 (2026-05-29) dropped the
    # <em> wrapping. The v3.1 emit wrapped this sentence in <em>...</em>
    # which the renderer styled clay-deep italic. Sebas: italics in copy
    # add noise — the sentence carries its own weight without typographic
    # emphasis. The italic-clay CSS rule is dropped in the same change.
    under_phrase = _price_under_phrase(listing, locale)
    drop_phrase = _drop_phrase(listing, locale)
    if drop_phrase and arch != "dropped_price":
        line_b = drop_phrase if drop_phrase.endswith((".", "!", "?")) else f"{drop_phrase}."
    elif under_phrase:
        line_b = (f"The price is {under_phrase}." if locale_en
                  else f"El precio está {under_phrase}.")
    elif arch == "mountain":
        line_b = ("Quiet, slow, the kind of land you build a life on." if locale_en
                  else "Tranquilo, sin prisa — del tipo de tierra donde se construye una vida.")
    elif arch == "stale":
        line_b = ("That usually means the seller will negotiate." if locale_en
                  else "Eso normalmente significa que el vendedor va a negociar.")
    elif arch == "built":
        line_b = ("Move-in ready, with the work already done." if locale_en
                  else "Listo para habitar, con el trabajo ya hecho.")
    else:
        line_b = ("Worth a closer look." if locale_en
                  else "Vale la pena verla más de cerca.")

    # Sentence C — the honest trade-off (utility / road / terrain).
    line_c = ""
    pt = listing.get("property_type")
    if pt == "land":
        line_c = _utility_phrase(listing, locale)
    elif pt in ("house", "condo"):
        # Built property — name the year / built area if useful, else
        # skip rather than fabricate.
        ba = listing.get("built_area_m2")
        if isinstance(ba, (int, float)) and ba > 0:
            line_c = (f"{int(ba)} m² of built area on the lot."
                      if locale_en else f"{int(ba)} m² construidos en el lote.")

    sentences = [line_a, line_b]
    if line_c:
        sentences.append(line_c)
    return " ".join(s.strip() for s in sentences if s)


# ── PR-NL-7a · welcome teaser + warm market note ────────────────────
#
# Two deterministic generators that match the v2.4 mockup voice.
# Together with PR-NL-6's per-pick stories, they cover all the warm
# editorial copy in the hero block.
#
# Each has an LLM upgrade in llm_commentary.py that's preferred when
# PULPO_NEWSLETTER_USE_LLM is on (default). These deterministic
# versions are the safety net — same shape, less personality.


def _welcome_pick_hook(pick: dict, locale: Locale) -> str:
    """Build a single-clause hook for one pick — the kind of phrasing
    the welcome teaser strings together as 'Start with #01… #02 is…'.

    Picks the strongest signal in the listing data:
      1. Price drop (most recent action wins)
      2. Strong below-zone discount (cool signal)
      3. Walk-to-beach (location hook)
      4. Build-ready (readiness=3, cool signal)
      5. Generic fallback that names the location

    The hook is a clause, not a full sentence — it slots after
    "Start with #01" or "#02 is" with proper grammar.
    """
    en = locale == "en"

    # Price-drop hook
    prev = pick.get("previous_price")
    cur = pick.get("price_usd")
    if pick.get("is_repriced") and isinstance(prev, (int, float)) and isinstance(cur, (int, float)) and prev > cur:
        drop_pct = (prev - cur) / prev * 100
        if drop_pct >= 10:
            return (f"just had a price drop of {drop_pct:.0f}%" if en
                    else f"acaba de tener una baja de precio del {drop_pct:.0f}%")
        return ("just had its first price drop in two weeks" if en
                else "acaba de tener su primera baja de precio en dos semanas")

    # Strong below-zone
    pct = pick.get("price_vs_zone_pct")
    if isinstance(pct, (int, float)) and pct <= -50:
        return ("priced like the seller actually wants to sell" if en
                else "con precio de vendedor que sí quiere vender")

    # Walk to beach / location
    if pick.get("is_walk_to_beach"):
        beach = pick.get("nearest_beach") or pick.get("named_beach_nearest")
        if beach:
            return (f"a short walk from {beach}" if en
                    else f"a pie de la playa de {beach}")
        return ("a short walk from the beach" if en
                else "a pie de la playa")

    # Mountain land — sense of place
    pt = pick.get("property_type")
    dept = (pick.get("department") or "").lower()
    if pt == "land" and (
        (isinstance(pick.get("dist_beach_km"), (int, float)) and pick["dist_beach_km"] > 25)
        or "morazán" in dept or "morazan" in dept or "chalatenango" in dept
    ):
        if pick.get("has_water_body"):
            return ("a mountain plot with a river — hard to look away from" if en
                    else "un terreno de montaña con río — difícil dejar de mirar")
        return ("a mountain plot the kind of land you build a life on" if en
                else "un terreno de montaña del tipo en el que se construye una vida")

    # Build-ready
    if pick.get("readiness_score") == 3:
        return ("move-in ready with water, power and a paved road" if en
                else "lista para construir con agua, luz y carretera pavimentada")

    # Coffee farm — built atmosphere hook
    desc = (pick.get("short_description_canonical") or {}).get("en", "") if isinstance(pick.get("short_description_canonical"), dict) else ""
    if isinstance(desc, str) and ("coffee" in desc.lower() or "café" in desc.lower()):
        return ("a coffee farm in the mountains, hard to look away from" if en
                else "una finca de café en las montañas, difícil dejar de mirar")

    # Generic location-only fallback
    muni = pick.get("municipality")
    if muni:
        return (f"a property worth a closer look in {muni}" if en
                else f"una propiedad que vale la pena ver en {muni}")
    return ("a property worth a closer look" if en
            else "una propiedad que vale la pena ver")


def deterministic_welcome_teaser(
    picks: list[dict],
    locale: Locale = "en",
    *,
    n_scanned: Optional[int] = None,
    pref: Optional[Preference] = None,
) -> str:
    """Three-sentence lede that orients the reader to this week's issue.

    v3.2 (2026-05-29, post-Sebas-feedback): the v3.1 "Pulpo combed
    through 863 listings across La Libertad" copy conflated Pulpo's
    coverage scope (every beach + lake property in El Salvador) with
    the recipient's filter (e.g. La Libertad land < $500k). That
    confused readers — "why does it say La Libertad if Pulpo combs
    through way more places?". The v3.2 lede separates the two:

      1. Pulpo's scope (static): every active beach + lake listing in
         El Salvador this week.
      2. Filter narrowing + standout count: of the N that match your
         filter, these K stood out.
      3. Issue shape: first three get a full profile (photo, our take,
         why we picked them); the rest are quick reads.

    `n_scanned` is the recipient's filter-match count, NOT the global
    inventory. Falls back gracefully when missing.

    No `<em>` wrapping — Sebas: "never use italics in copy, it adds
    noise." The italic-clay CSS rule that styled the v3.1 emphasis is
    dropped from render_html.py in the same v3.2 change. The `pref`
    argument is preserved for API compatibility with v3.1 callers but
    is no longer consulted — Pulpo's scope is global, not filter-shaped.
    """
    if not picks:
        return ""
    en = locale == "en"
    n = len(picks)
    rich = min(3, n)
    rest = max(0, n - rich)
    _ = pref  # v3.2: preserved for API compatibility, not consulted.

    # Sentence 1 — Pulpo's honest scope. Coastal + the two serviced
    # lakes (Coatepeque, Ilopango). Static copy, no filter leak.
    sent1 = (
        "Pulpo combed through every active beach and lake listing in El Salvador this week."
        if en
        else "Pulpo revisó todas las propiedades activas de playa y lago en El Salvador esta semana."
    )

    # Sentence 2 — filter narrowing → standout count. Drops the count
    # entirely when n_scanned is missing rather than fabricating one.
    if isinstance(n_scanned, int) and n_scanned > 0:
        sent2 = (
            f"Of the {n_scanned:,} that match your filter, these {n} stood out."
            if en
            else f"De las {n_scanned:,} que coinciden con tu filtro, estas {n} destacaron."
        )
    else:
        sent2 = (
            f"These {n} stood out."
            if en
            else f"Estas {n} destacaron."
        )

    # Sentence 3 — issue shape. Telegraphs what the rich vs short
    # treatment contains so the reader knows what scroll depth to expect.
    if rest:
        if en:
            sent3 = (
                f"The first {_num_word(rich)} get a full profile: photo, our take, "
                f"and why we picked them. The next {_num_word(rest)} are quick reads."
            )
        else:
            sent3 = (
                f"Las {_num_word(rich, en=False, fem=True)} primeras llevan un perfil completo: "
                f"foto, nuestra lectura, y por qué las elegimos. "
                f"Las {_num_word(rest, en=False, fem=True)} siguientes son lecturas rápidas."
            )
    else:
        if en:
            sent3 = (
                f"All {_num_word(rich)} get a full profile: photo, our take, and why we picked them."
            )
        else:
            sent3 = (
                f"Las {_num_word(rich, en=False, fem=True)} llevan un perfil completo: "
                f"foto, nuestra lectura, y por qué las elegimos."
            )

    return f"{sent1} {sent2} {sent3}"


def _num_word(n: int, en: bool = True, *, fem: bool = False) -> str:
    """Natural-language numeral up to a dozen for editorial copy.

    "The first three…" beats "The first 3…" in an editorial newsletter;
    digits look like a stat strip, words read like a sentence. Falls
    back to `str(n)` past 12 so the function stays safe at any size.
    `fem` controls Spanish gender agreement for "una/uno" / "ninguna/ninguno".
    """
    if en:
        return {
            0: "none", 1: "one", 2: "two", 3: "three", 4: "four",
            5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
            10: "ten", 11: "eleven", 12: "twelve",
        }.get(n, str(n))
    return {
        0: "ninguna" if fem else "ninguno",
        1: "una" if fem else "uno",
        2: "dos", 3: "tres", 4: "cuatro", 5: "cinco",
        6: "seis", 7: "siete", 8: "ocho", 9: "nueve",
        10: "diez", 11: "once", 12: "doce",
    }.get(n, str(n))


def _market_property_phrase(pick: dict, locale: Locale, *, with_link: bool = True) -> str:
    """A short descriptive phrase for one pick, optionally wrapped in a
    PICK_URL placeholder anchor.

    Examples (EN):
      • 76,259 m² lot in El Zonte at $19.67/m² — 84% below the area average
      • beachfront home in La Libertad at $900,000

    Engineered to read naturally inside the market-note sentence (no
    leading article — caller adds "a"/"the" so noun-article agreement
    stays clean across locales). The renderer replaces `PICK_URL_<rank>`
    with the real pulpo_url at render time.
    """
    en = locale == "en"
    rank = pick.get("_issue_rank") if isinstance(pick.get("_issue_rank"), int) else None
    municipality = pick.get("municipality") or pick.get("department") or ""
    pt = pick.get("property_type")
    pct = pick.get("price_vs_zone_pct")
    price_usd = pick.get("price_usd")
    ppm = pick.get("price_per_m2")
    area = pick.get("area_m2")
    is_beachfront = bool(pick.get("is_beachfront"))

    # v3.2 (2026-05-29) — phrase is now PURELY QUALITATIVE.
    # The v3.1 version stamped literal "$47.48/m² — 78% below the area
    # average" into the market paragraph. Every one of those numbers
    # already appears on the per-pick card just below (chip + meta row +
    # big price), so the market paragraph was repeating itself two
    # paragraphs early. Sebas: "never repeat numbers."
    #
    # The phrase now reads as a noun-phrase the reader can click —
    # "a 1,263 m² lot in Tamanique" — and the per-pick card carries the
    # numeric breakdown. `pct`, `price_usd`, `ppm` and `is_beachfront`
    # are intentionally kept in scope (above) so future copy can opt
    # back into a number when it earns its place — but the default
    # path emits no $$ or %.
    _ = (pct, price_usd, ppm, is_beachfront)  # kept for future-proofing; not used here

    bits: list[str] = []
    if pt == "land" and isinstance(area, (int, float)) and area >= 100:
        bits.append(f"{int(area):,} m² lot" if en else f"lote de {int(area):,} m²")
    elif pick.get("is_beachfront") and pt in ("house", "condo"):
        bits.append("beachfront home" if en else "casa frente al mar")
    elif pt in ("house", "condo"):
        bits.append(("home" if pt == "house" else "condo") if en else ("casa" if pt == "house" else "condominio"))
    else:
        bits.append("property" if en else "propiedad")

    if municipality:
        bits.append(f"in {municipality}" if en else f"en {municipality}")

    phrase = " ".join(bits)

    if with_link and isinstance(rank, int) and 1 <= rank <= 10:
        # PICK_URL_<rank> is a template token; render_html replaces it
        # with the actual pulpo_url before the email goes out.
        return f'<a href="PICK_URL_{rank}">{phrase}</a>'
    return phrase


def deterministic_market_note(picks: list[dict], locale: Locale = "en") -> str:
    """One data-rich market paragraph that names the most striking 1–2
    picks of the week, with each property mention wrapped in a
    `PICK_URL_<rank>` placeholder the renderer replaces with the real
    pulpo_url before mailing.

    v3.1 (2026-05-29): collapsed the v2.8 multi-paragraph structure
    (warm framing + freshness stat + median delta + repricing count)
    into a single concrete paragraph. Sebas's review of the v2.8 send
    flagged the earlier "Pulpo scanned 863 properties…" + "If you're
    looking for a deal…" paragraphs as redundant filler. The single
    paragraph below leads with the most striking discount, optionally
    names a second distinct pick (beachfront, slow-mover, etc.), and
    stops. The intro lede tells the reader the shape of the issue;
    this paragraph tells them the headline of the data.

    Every claim maps to a real Listing field — no invented stats.
    Picks must be tagged with `_issue_rank` (1..N) so the placeholder
    substitution can look up the matching pulpo_url; build_issue does
    this tagging right before calling here.
    """
    if not picks:
        return ""
    en = locale == "en"

    # Pick #1 — deepest discount that's concrete enough to describe.
    discount_pick = None
    deepest_pct = 0.0
    for p in picks:
        pct = p.get("price_vs_zone_pct")
        if isinstance(pct, (int, float)) and pct < deepest_pct:
            deepest_pct = pct
            discount_pick = p

    # Pick #2 — most distinct pick that ISN'T the discount one.
    distinct_pick = None
    for p in picks:
        if p is discount_pick:
            continue
        if p.get("is_beachfront"):
            distinct_pick = p
            break
    if distinct_pick is None:
        for p in picks:
            if p is discount_pick:
                continue
            if p.get("is_repriced") and (p.get("days_listed") or 0) >= 60:
                distinct_pick = p
                break

    if discount_pick is None:
        # No striking discount — give a calm read of inventory state.
        new_listings = sum(1 for p in picks if p.get("_is_new_window"))
        if new_listings >= max(2, len(picks) // 3):
            return (
                f"Fresh inventory landed this week — {new_listings} of these "
                f"{len(picks)} listings are less than seven days old. "
                "The early window matters; listings priced to move don't stay around."
                if en
                else
                f"Llegó inventario fresco esta semana — {new_listings} de estas "
                f"{len(picks)} propiedades tienen menos de siete días. "
                "La ventana temprana importa; las propiedades bien valoradas no se quedan."
            )
        return (
            "A quieter week than usual — inventory is steady, prices are holding. "
            "Worth saving anything close to your filter so Pulpo can flag the next move."
            if en
            else
            "Una semana más tranquila — el inventario es estable, los precios se sostienen. "
            "Vale la pena guardar lo que se acerque a tu filtro para que Pulpo avise del siguiente movimiento."
        )

    discount_phrase = _market_property_phrase(discount_pick, locale, with_link=True)
    if distinct_pick is not None:
        distinct_phrase = _market_property_phrase(distinct_pick, locale, with_link=True)
        if en:
            return (
                f"The most aggressive discount this week is {discount_phrase}. "
                f"In a different lane, {distinct_phrase} is also worth a look."
            )
        return (
            f"El descuento más agresivo esta semana es {discount_phrase}. "
            f"En otro carril, {distinct_phrase} también vale la pena revisar."
        )

    if en:
        return (
            f"The most aggressive discount this week is {discount_phrase}. "
            "Worth a closer look before someone else moves on it."
        )
    return (
        f"El descuento más agresivo esta semana es {discount_phrase}. "
        "Vale la pena revisarla antes de que alguien más se mueva."
    )
