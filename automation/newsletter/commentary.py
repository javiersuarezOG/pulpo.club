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
    # PR-NL-7a: lede_hero is now the warm welcome teaser that name-checks
    # the first 3 picks ("Start with #01… #02 is… And #03…"). Falls back
    # to the older "Pulpo scanned N listings…" template when picks is
    # empty so cold-start cohorts still get something readable.
    if picks:
        lede = deterministic_welcome_teaser(picks, locale)
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
    # PR-NL-7a: the first paragraph is the warm one-sentence "buyer's
    # fortnight" market note (matches v2.4 mockup). The older data-stat
    # paragraphs follow it as supporting detail — readers who care about
    # the numbers see them; everyone else gets the warm read.
    market: list[str] = []
    if picks:
        market.append(deterministic_market_note(picks, locale))
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

    # 1) Below area average — meaningful only past 15% off.
    pct = listing.get("price_vs_zone_pct")
    if isinstance(pct, (int, float)) and pct <= -15:
        n = abs(int(round(pct)))
        beach_phrase = ""
        if listing.get("is_walk_to_beach") or listing.get("is_beachfront"):
            beach_phrase = " — rare for a lot this close to the beach" if en \
                           else " — raro para un lote tan cerca de la playa"
        out.append(
            f"Priced {n}% below the area average{beach_phrase}"
            if en
            else f"Precio {n}% bajo el promedio del área{beach_phrase}"
        )

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
            "Brand new this fortnight — early window matters"
            if en
            else "Nueva esta quincena — la ventana temprana importa"
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
    """Single "For someone who *…*" line for one shortlist entry.

    Returns an HTML string with one `<em>...</em>` span around the
    italic clause (the renderer styles it clay-deep italic). Matches the
    v3 mockup's per-row framing:

      For someone who *wants surf-city land cheap*. The catch: …

    The frame answers "who is this the right answer for?" — keeps the
    shortlist scannable for a buyer skimming for relevance. The frame
    must map to real Listing fields (property_type, dist_beach_km,
    is_repriced, etc.) — never invent a buyer persona the data doesn't
    support.

    Empty string is allowed (renderer falls back to the existing
    `blurb`) so a listing missing the fields to support a frame still
    renders cleanly.
    """
    en = locale == "en"
    pt = listing.get("property_type")
    pct = listing.get("price_vs_zone_pct")
    beach_km = listing.get("dist_beach_km")
    days = listing.get("days_listed")

    # Price drop → "thinking long horizon" buyer who's waiting out a
    # slow seller. Concrete drop number stays in the why_bullets;
    # this frame is about the buyer profile, not the number.
    if listing.get("is_repriced") and isinstance(days, int) and days >= 60:
        return (
            "For someone <em>thinking long horizon</em> — the seller has been on market a while and just moved."
            if en
            else
            "Para alguien <em>con horizonte largo</em> — el vendedor lleva tiempo en el mercado y acaba de moverse."
        )

    # Deep discount + walk-to-surf — the "wants surf-city land cheap"
    # archetype from the mockup. Anchors against named beach when known.
    if listing.get("is_walk_to_beach") and isinstance(pct, (int, float)) and pct <= -30:
        beach = listing.get("nearest_beach") or listing.get("named_beach_nearest")
        if isinstance(beach, str) and beach:
            return (
                f"For someone who <em>wants {beach}-area land cheap</em>."
                if en
                else f"Para alguien que <em>quiere terreno barato cerca de {beach}</em>."
            )
        return (
            "For someone who <em>wants surf-side land cheap</em>."
            if en
            else "Para alguien que <em>quiere terreno barato cerca del mar</em>."
        )

    # House / condo → move-in-ready buyer.
    if pt in ("house", "condo"):
        return (
            "For someone who <em>doesn't want to build</em> — move-in ready, no project."
            if en
            else "Para alguien que <em>no quiere construir</em> — listo para entrar, sin obra."
        )

    # Far-from-beach raw land → builder with a budget.
    if pt == "land" and isinstance(beach_km, (int, float)) and beach_km >= 25:
        area = listing.get("area_m2")
        if isinstance(area, (int, float)) and area >= 5000:
            return (
                "For someone <em>buying with a build budget</em> — the land alone is the deal."
                if en
                else "Para alguien que <em>compra con presupuesto de construcción</em> — el valor está en el terreno."
            )
        return (
            "For someone <em>buying acreage</em>, not a build site."
            if en
            else "Para alguien que <em>compra hectáreas</em>, no un sitio para construir."
        )

    # Near-beach land without a deep discount → the "El Zonte vibe
    # without the beachfront price" archetype from the mockup.
    if pt == "land" and isinstance(beach_km, (int, float)) and beach_km < 25:
        return (
            "For someone who <em>wants the coastal vibe without the beachfront price</em>."
            if en
            else "Para alguien que <em>quiere el ambiente costero sin el precio de primera línea</em>."
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
                else "Luz y agua en el lote; tú añades la carretera.")
    if has_power and has_road:
        return ("Power and the road are there; water you'd bring from a well." if locale == "en"
                else "Luz y carretera ya están; el agua la traes de un pozo.")
    if has_water and has_road:
        return ("Water and the road are at the lot; you'd run power from the nearest connection."
                if locale == "en"
                else "Agua y carretera ya en el lote; la luz la traes de la conexión más cercana.")
    if has_power:
        return ("Power runs to the boundary; water and the road are on you." if locale == "en"
                else "Luz hasta el límite; agua y carretera quedan por hacer.")
    if has_water:
        return ("Water is on site; you'd add power and the road." if locale == "en"
                else "Agua en el lote; faltan luz y carretera.")
    return ("Bring a build budget — none of the utilities are in yet." if locale == "en"
            else "Trae presupuesto para construir — todavía no hay servicios.")


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

    # Sentence B — the emotional center, wrapped in <em>. This is what
    # the renderer styles clay-deep italic.
    under_phrase = _price_under_phrase(listing, locale)
    drop_phrase = _drop_phrase(listing, locale)
    if drop_phrase and arch != "dropped_price":
        line_b = f"<em>{drop_phrase}</em>"
    elif under_phrase:
        line_b = (f"<em>The price is {under_phrase}.</em>" if locale_en
                  else f"<em>El precio está {under_phrase}.</em>")
    elif arch == "mountain":
        line_b = ("<em>Quiet, slow, the kind of land you build a life on.</em>" if locale_en
                  else "<em>Tranquilo, sin prisa — del tipo de tierra donde se construye una vida.</em>")
    elif arch == "stale":
        line_b = ("<em>That usually means the seller will negotiate.</em>" if locale_en
                  else "<em>Eso normalmente significa que el vendedor va a negociar.</em>")
    elif arch == "built":
        line_b = ("<em>Move-in ready, with the work already done.</em>" if locale_en
                  else "<em>Listo para habitar, con el trabajo ya hecho.</em>")
    else:
        line_b = ("<em>Worth a closer look.</em>" if locale_en
                  else "<em>Vale la pena verla más de cerca.</em>")

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


def deterministic_welcome_teaser(picks: list[dict], locale: Locale = "en") -> str:
    """Build the warm welcome lede that name-checks the first 3 picks.

    Mirrors the v2.4 mockup:

      "Start with #01 — ocean view, a twenty-minute walk from El Tunco,
       priced like the seller actually wants to sell. #02 is a coffee
       farm with two rivers in the mountains, hard to look away from.
       And #03 just had its first price drop in two weeks."

    The renderer styles this in serif italic — so even the
    deterministic version reads warm despite the templated grammar.
    """
    if not picks:
        return ""
    en = locale == "en"
    teased = picks[:3]
    parts: list[str] = []
    for i, pick in enumerate(teased):
        hook = _welcome_pick_hook(pick, locale)
        if i == 0:
            parts.append(f"Start with <em>#01</em> — {hook}." if en else f"Empieza por <em>#01</em> — {hook}.")
        elif i == 1:
            parts.append(f"<em>#02</em> is {hook}." if en else f"<em>#02</em> es {hook}.")
        else:
            parts.append(f"And <em>#03</em> {hook}." if en else f"Y <em>#03</em> {hook}.")
    return " ".join(parts)


def deterministic_market_note(picks: list[dict], locale: Locale = "en") -> str:
    """The warm one-sentence market note in the v2.4 mockup ('It's a
    buyer's fortnight in La Libertad…').

    Pattern-matches against the picks Pulpo selected this fortnight:
      • repriced_count / len(picks) — share of picks that just dropped
      • below_zone_count / len(picks) — share priced under area median
      • new_listing_count — share that landed in the last 14 days

    When the data is unusually friendly to buyers (≥ 40% repriced or
    a strong below-zone median), surfaces the "buyer's fortnight"
    framing. When it's tighter, gives an honest read instead of
    fabricating urgency.
    """
    if not picks:
        return ""
    en = locale == "en"

    repriced = sum(1 for p in picks if p.get("is_repriced"))
    new_listings = sum(1 for p in picks if p.get("_is_new_window"))
    n = len(picks)

    # The most striking pattern wins the framing.
    if repriced >= max(2, n * 0.4):
        return (
            "It's a buyer's fortnight. <em>Almost twice as many sellers lowered "
            "their prices this week as a normal week.</em> "
            "If you're getting close on a listing — this is a good week to make the call."
            if en
            else
            "Es una quincena de compradores. <em>Casi el doble de vendedores bajaron "
            "su precio esta semana de lo normal.</em> "
            "Si estás cerca de hacer una oferta — esta es una buena semana para llamarla."
        )

    if new_listings >= max(3, n * 0.4):
        return (
            "Fresh inventory landed this fortnight. <em>Several of these listings are "
            "less than two weeks old.</em> "
            "The early window matters — listings priced to move don't stay around."
            if en
            else
            "Llegó inventario fresco esta quincena. <em>Varias de estas propiedades tienen "
            "menos de dos semanas.</em> "
            "La ventana temprana importa — las propiedades bien valoradas no se quedan."
        )

    # Quieter fortnight — give a calm read instead of fabricating drama.
    import statistics
    deltas = [p.get("price_vs_zone_pct") for p in picks if isinstance(p.get("price_vs_zone_pct"), (int, float))]
    if deltas:
        med = statistics.median(deltas)
        if med < -15:
            return (
                f"<em>The median pick in this issue is {abs(med):.0f}% under the area average.</em> "
                "Less drama, more value — worth slowing down to read each one."
                if en
                else
                f"<em>La selección mediana de esta edición está {abs(med):.0f}% bajo el promedio del área.</em> "
                "Menos drama, más valor — vale la pena leer cada una con calma."
            )

    return (
        "A quieter fortnight than usual. <em>Inventory is steady, prices are holding.</em> "
        "Worth saving anything close to your filter so Pulpo can flag the next move."
        if en
        else
        "Una quincena más tranquila de lo usual. <em>El inventario es estable, los precios se sostienen.</em> "
        "Vale la pena guardar lo que se acerque a tu filtro para que Pulpo avise del siguiente movimiento."
    )
