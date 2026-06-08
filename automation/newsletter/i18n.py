"""Server-side i18n for the newsletter renderer.

Mirror of the subset of web/app/i18n.jsx that the email touches. Kept here
(not imported from the JS bundle) because the cron is Python and the
newsletter copy is editorial-tone (different register than the app UI).

When the EN/ES copy diverges from app.jsx, the smoke-test guardrail in
preview-smoke.spec.ts still applies in spirit: never let an EN canary
word ("Save listing", "Open the file") leak into an ES render. The test
for that lives in tests/newsletter/test_render.py.
"""

from __future__ import annotations

import re
from typing import Literal

from pulpo.countries import active as _active_country

Locale = Literal["en", "es"]
DEFAULT_LOCALE: Locale = "en"

# PR-MC-newsletter — strings that mention the country / primary airport
# read from the active country's manifest at module load. SV deployment
# renders identically; a GT deployment swaps "El Salvador" → "Guatemala"
# and "min to SAL" → "min to <GT primary airport>" in one shot.
_country = _active_country()
_country_en = _country.name_en
_country_es = _country.name_es
# Pick the first declared airport as the "minutes to <airport>" anchor.
# SV's manifest lists SAL first (operational hub), so SV renders unchanged.
# A new country adds its primary airport first in the airports dict.
_airports = _country.airports()
_primary_airport_code = next(iter(_airports.keys()), "")

# Strings are grouped by surface (header / hero / glance / pick / shortlist /
# skip / market / footer) — mirror the section comments in web/app/i18n.jsx.
STRINGS: dict[str, dict[Locale, str]] = {
    # ── Header ──
    "header.issue":                {"en": "ISSUE {n} · {date}",                          "es": "EDICIÓN {n} · {date}"},
    # ── Hero ──
    "hero.eyebrow.named":          {"en": "Hand-picked for {name}",                       "es": "Selección para {name}"},
    "hero.eyebrow.unnamed":        {"en": "Hand-picked this week",                   "es": "Selección de esta semana"},
    "hero.eyebrow.anon":           {"en": "The 10 best, this week",                  "es": "Las 10 mejores, esta semana"},
    "hero.headline.default":       {"en": "The 10 best, this week.",                 "es": "Las 10 mejores, esta semana."},
    "hero.lede.with_prefs":        {"en": f"Pulpo scanned {{n_scanned}} active beach and lake properties across {_country_en} this week. These ten matched your filter closely enough to make the cut.",
                                     "es": f"Pulpo revisó {{n_scanned}} propiedades activas frente al mar y al lago en {_country_es} esta semana. Estas diez encajan con tu filtro lo suficiente para entrar."},
    "hero.lede.no_prefs":          {"en": "Pulpo scanned {n_scanned} active properties this week and ranked them by value, location and momentum. You'll get a sharper edition once you set a filter — link at the bottom.",
                                     "es": "Pulpo revisó {n_scanned} propiedades esta semana y las clasificó por valor, ubicación y momentum. Recibirás una edición más afinada cuando configures un filtro — enlace al final."},
    # ── At a glance ──
    "glance.eyebrow":              {"en": "At a glance",                                  "es": "Vistazo rápido"},
    "glance.subhead.with_skip":    {"en": "{kept} to consider. One to skip.",             "es": "{kept} para considerar. Una para saltar."},
    "glance.subhead.no_skip":      {"en": "{kept} to consider.",                          "es": "{kept} para considerar."},
    # ── Pick / shortlist labels ──
    "pick.top_label":              {"en": "🏆 Top pick · {rank:02d}",                     "es": "🏆 Selección · {rank:02d}"},
    "pick.new_pill":               {"en": "New this week",                           "es": "Nueva esta semana"},
    "pick.repriced_pill":          {"en": "Price moved",                                  "es": "Precio movido"},
    # PR-NL-5 (v2.4 redesign): every pick CTA goes to pulpo.club, not the
    # external source. The dual CTA on hero picks is `cta_open` (solid
    # "See on Pulpo →") + `cta_save` (ghost "Save to favorites"). The
    # source-aware `cta_view_on` / `cta_view` from v2.2 are deleted —
    # the rich-pick CTA now points at pulpo_url, not listing_url.
    "pick.cta_open":               {"en": "See on Pulpo →",                               "es": "Ver en Pulpo →"},
    # Free general template only — the ranks 04-10 ("7 more") CTA. The card
    # renders identically to the Pro card (photo, title, location, price,
    # "Why we picked it"); only the CTA changes from "See on Pulpo" to a
    # sign-up ask. Rendered by `_pick_card_html` when variant="free_general"
    # and the pick is NOT a top-3 deal.
    "pick.cta_signup":             {"en": "Sign up to Pro →",                              "es": "Regístrate en Pro →"},
    # v4 (2026-05-31): shortened from "Save to favorites" / "Guardar en
    # favoritos" — the long Spanish form was overflowing the card width
    # on mobile (375px in Gmail's narrow rendering) and breaking the
    # paired-CTA row layout. "Save" / "Guardar" fits at every viewport
    # and matches the locked mockup. The heart glyph is rendered by
    # `_pick_card_html` outside this string for layout flexibility.
    "pick.cta_save":               {"en": "Save",                                         "es": "Guardar"},
    # Price-anchored unlock — "$9.99/mo" matches the canonical pricing
    # source-of-truth (project_post_stripe_activation_series memory).
    "pick.cta_locked":             {"en": "Unlock this pick — $9.99/mo →",                "es": "Desbloquear esta selección — $9.99/mes →"},
    "pick.paywall_blurb":          {"en": "Pulpo Pro reveals the address, the broker file, and the full underwriting. Free members see the photo and the headline.",
                                     "es": "Pulpo Pro revela la dirección, la ficha del corredor y el análisis completo. Los miembros gratuitos ven foto y titular."},
    "shortlist.eyebrow":           {"en": "{n} more worth a look",                        "es": "{n} más que valen la pena"},
    "shortlist.headline":          {"en": "Each one suits a different kind of buyer.",
                                     "es": "Cada una le encaja a un comprador distinto."},
    "shortlist.lede":              {"en": "Pulpo ranked these inside your filter too. Skim the short reads below — each one tells you who the right buyer is.",
                                     "es": "Pulpo también las clasificó dentro de tu filtro. Leé los resúmenes cortos — cada uno te dice a quién le encaja."},
    # v3: "Why we picked it" label that sits above the 3 plain-English
    # bullets on each hero pick. Replaces the v2.x "Why Pulpo ranked it"
    # callout that exposed analyst-y rank-reasons strings.
    "pick.why_label":              {"en": "Why we picked it",                              "es": "Por qué la elegimos"},
    # ── Skip ──
    "skip.eyebrow":                {"en": "Skip this one",                                "es": "Esta sí, sáltala"},
    # ── Market context (v4) ──
    "market.eyebrow":              {"en": "Market context",                               "es": "Contexto del mercado"},
    "market.headline":             {"en": "What's moving this week.",                "es": "Qué se está moviendo esta semana."},
    # Surf City decoder line (italic, sits between H2 and body). Names the
    # two regional corridors for any reader who isn't fluent in gov-coined
    # coastal branding. Bold tags survive in italic body via inline color.
    "market.decoder":              {"en": "<strong style=\"color:#1A1916;\">Surf City 1</strong> = the La Libertad coast (El Tunco → El Sunzal → El Zonte). <strong style=\"color:#1A1916;\">Surf City 2</strong> = the eastern coast from Las Flores to El Cuco. We cover both.",
                                     "es": "<strong style=\"color:#1A1916;\">Surf City 1</strong> = la costa de La Libertad (El Tunco → El Sunzal → El Zonte). <strong style=\"color:#1A1916;\">Surf City 2</strong> = la costa este de Las Flores a El Cuco. Cubrimos ambas."},
    # ── v4 section intros (sit above picks 01 + picks 04) ─────────────
    "section.top3.title":          {"en": "Top 3 this week.",                              "es": "Top 3 esta semana."},
    "section.top3.body":           {"en": "Three picks, three different fits. One is move-in-ready beachfront — if you want the work already done. One is an underpriced lot with utilities — if you can run the build but don't want to deal with the infrastructure. One is a blank-canvas lot at a fair price — if you want both.",
                                     "es": "Tres selecciones, tres formas distintas. Una es frente al mar lista para mudarse — si querés el trabajo ya hecho. Una es un lote con bajo precio y servicios — si podés armar la construcción pero no querés lidiar con la infraestructura. Una es un lote en blanco a precio justo — si querés ambas."},
    "section.rest.title":          {"en": "{n} more this week.",                           "es": "{n} más esta semana."},
    "section.rest.body":           {"en": "Past the top 3. These each fit a clear segment — Bitcoin Beach move-in, trophy oceanfront, developer-scale lots, mid-range build sites. Skim the \"Why we picked it\" bullets and stop on the one that fits you.",
                                     "es": "Después del top 3. Cada una calza en un segmento — Bitcoin Beach lista para mudarse, frente al mar trofeo, lotes a escala de desarrollador, sitios de construcción de rango medio. Hojeá los puntos de \"por qué la elegimos\" y parate en la que te calza a vos."},
    # ── Weekly News Spotlight (v4) ────────────────────────────────────
    "spotlight.eyebrow":           {"en": "Weekly News Spotlight",                         "es": "Noticia de la semana"},
    # ── Free general template: the spotlight is Pro-LOCKED ────────────
    # The free edition shows the REAL headline, source citation and the
    # opening sentence of the real article (all from the committed
    # news_spotlight.json artifact — no fabricated copy), then withholds
    # the rest of the read behind a single sign-up panel. These strings are
    # the generic upsell wrapper around that real content; they must NOT
    # claim article-specific analysis that doesn't exist in the artifact.
    "spotlight.pro_badge":         {"en": "Pro",                                          "es": "Pro"},
    "spotlight.locked_label":      {"en": "The Pulpo read · Pro",                          "es": "El análisis de Pulpo · Pro"},
    "spotlight.locked_body":      {"en": "Pulpo Pro carries the full read — what the story means for prices and which of this week's picks it touches.",
                                     "es": "Pulpo Pro lleva el análisis completo — qué significa la noticia para los precios y a cuáles de las selecciones de esta semana les afecta."},
    "spotlight.locked_cta":        {"en": "Sign up to Pro to read the take →",             "es": "Regístrate en Pro para leer el análisis →"},
    # DEPRECATED (kept for parity; no longer rendered). The spotlight now
    # reads from the committed artifact (web/data/news_spotlight.json) with
    # nightly carry-forward, so a real cited article is always available —
    # the renderer omits the section entirely on a cold start rather than
    # ship this source-less filler. Safe to delete once no tooling reads it.
    "spotlight.fallback.title":    {"en": "What we're watching on the coast.",             "es": "Lo que estamos viendo en la costa."},
    "spotlight.fallback.body":     {"en": "No single headline drove the market this week. Surf City 1 (the La Libertad stretch) remains the most active corridor by listing volume; Surf City 2 (the eastern coast) is quieter. We'll surface a sourced story in next week's edition when one earns it.",
                                     "es": "Ningún titular en particular movió al mercado esta semana. Surf City 1 (la franja de La Libertad) sigue siendo el corredor más activo por volumen de listados; Surf City 2 (la costa este) está más tranquila. Sacaremos una historia con fuente en la próxima edición cuando se la gane."},
    "one_number.eyebrow":          {"en": "One number worth knowing",                     "es": "Un número que vale la pena saber"},
    # ── Next issue ──
    "next.eyebrow":                {"en": "Next issue",                                   "es": "Próxima edición"},
    "next.body":                   {"en": "Pulpo scans the next 7 days of inventory against your filter and ships the next ten. Adjust filters anytime — changes apply to the next issue.",
                                     "es": "Pulpo revisa los próximos 7 días de inventario contra tu filtro y envía las próximas diez. Ajustá filtros cuando querás — los cambios aplican a la siguiente edición."},
    # v2.2: product-language CTA tied to the editorial framing of the
    # newsletter ("the picks I see"), not generic settings-speak.
    "next.cta":                    {"en": "Tune what you see →",                          "es": "Ajustá lo que ves →"},
    "next.cta.anon":               {"en": "Set your filter →",                            "es": "Configurá tu filtro →"},
    # ── Your Pulpo (v4 — 3 stacked cream action cards) ─────────────────
    # Eyebrow text = small-caps context line; CTA text = bold action
    # (no trailing arrow — the arrow renders as its own right-aligned
    # column in `_your_pulpo_html` for visual consistency across cards).
    "yp.eyebrow":                  {"en": "Your Pulpo",                                   "es": "Tu Pulpo"},
    "yp.title":                    {"en": "Pick up where you left off.",                  "es": "Retomá donde lo dejaste."},
    "yp.saved.label":              {"en": "{n} saved listings",                           "es": "{n} propiedades guardadas"},
    "yp.saved.cta":                {"en": "Open your favorites",                          "es": "Abrir tus favoritos"},
    "yp.filter.label":             {"en": "Filter: {filter}",                             "es": "Filtro: {filter}"},
    "yp.filter.cta":               {"en": "Edit your filter",                             "es": "Editar tu filtro"},
    "yp.browse.label":             {"en": "{n} listings match",                           "es": "{n} propiedades coinciden"},
    "yp.browse.cta":               {"en": "Browse them all",                              "es": "Verlas todas"},
    # Anonymous-cohort-only welcome card.
    "yp.welcome.label":            {"en": "No filter set yet",                            "es": "Aún no configuraste tu filtro"},
    "yp.welcome.cta":              {"en": "Set your filter",                              "es": "Configurá tu filtro"},
    # ── Paywall (free tier) ──
    # v1.1 (2026-06-07): rewritten for the free-general design. Free
    # readers now see all 10 FULL picks (photo, title, price, why), so the
    # old "you're seeing the public cut / photo and headline / eight times
    # the depth" framing contradicted what's on screen. The honest upsell:
    # you see the picks; Pro adds the address/broker/underwriting + the
    # full news read. Banner only renders for the free cohort.
    "paywall.eyebrow":             {"en": "Free edition",                                 "es": "Edición gratuita"},
    "paywall.headline":            {"en": "Pro goes deeper on every pick.",               "es": "Pro profundiza en cada selección."},
    "paywall.body":                {"en": "You're seeing all 10 picks, ranked. Pulpo Pro adds what closes a deal — the address, the broker contact, the full underwriting, the negotiation lever the seller doesn't know we know about, plus the full read on this week's news. Same weekly cadence, the complete file.",
                                     "es": "Estás viendo las 10 selecciones, clasificadas. Pulpo Pro suma lo que cierra un trato — la dirección, el contacto del corredor, el análisis completo, la palanca de negociación que el vendedor no sabe que conocemos, y el análisis completo de la noticia de la semana. Misma cadencia semanal, el archivo completo."},
    # Aligned with the canonical $9.99/mo price (web/app/lib/pricing.ts +
    # web/app/config/legal-content.ts). The v2.1 newsletter shipped with
    # $19/month which was stale drift — fixed in v2.2.
    "paywall.cta":                 {"en": "Go Pro — $9.99/month →",                       "es": "Hacete Pro — $9.99/mes →"},
    # ── Footer ──
    "footer.tagline":              {"en": f"Every beach and lake home in {_country_en}, ranked by value.",
                                     "es": f"Cada casa frente al mar y al lago en {_country_es}, clasificada por valor."},
    "footer.you_get_this":         {"en": "You're getting this because your filter is set to {filter_summary}.",
                                     "es": "Recibís esto porque tu filtro está configurado en {filter_summary}."},
    "footer.you_get_this.no_prefs": {"en": "You're getting this because you signed up — we haven't captured your filter yet.",
                                     "es": "Recibís esto porque te suscribiste — aún no capturamos tu filtro."},
    "footer.change_filters":       {"en": "Change filters",                               "es": "Cambiar filtros"},
    "footer.change_cadence":       {"en": "Change cadence",                               "es": "Cambiar cadencia"},
    "footer.unsubscribe":          {"en": "Unsubscribe",                                  "es": "Cancelar suscripción"},
    "footer.no_commission":        {"en": "Pulpo doesn't take commission and doesn't list its own properties. We pick from what's already on the market and tell you which ones are worth your time.",
                                     "es": "Pulpo no cobra comisión ni publica sus propias propiedades. Elegimos de lo que ya está en el mercado y te decimos cuáles merecen tu tiempo."},
    # v4.1 (2026-05-31): footer copyright signals Pulpo Pro since this
    # newsletter is the personalised Pro product (audience scoped to
    # Pro recipients per PR-NL-9). Matches the PRO pills next to the
    # `pulpo` wordmark in the header + footer.
    "footer.copyright":            {"en": "© {year} Pulpo Pro",
                                     "es": "© {year} Pulpo Pro"},
    # ── Generic facts ──
    "facts.beach":                 {"en": "{km} km to beach",                             "es": "{km} km a la playa"},
    "facts.walk_to_beach":         {"en": "Walk to the beach",                            "es": "A pie de la playa"},
    "facts.beachfront":            {"en": "Beachfront",                                   "es": "Frente al mar"},
    "facts.airport":               {"en": f"{{km}} km · {{min}} min to {_primary_airport_code}" if _primary_airport_code else "{km} km · {min} min to airport",
                                     "es": f"{{km}} km · {{min}} min a {_primary_airport_code}" if _primary_airport_code else "{km} km · {min} min al aeropuerto"},
    "facts.land":                  {"en": "Land",                                         "es": "Terreno"},
    "facts.house":                 {"en": "House",                                        "es": "Casa"},
    "facts.condo":                 {"en": "Condo",                                        "es": "Apartamento"},
    "facts.power_water_road":      {"en": "Power · water · road",                         "es": "Luz · agua · acceso"},
    "facts.power_water":           {"en": "Power · water",                                "es": "Luz · agua"},
    "facts.power":                 {"en": "Power on site",                                "es": "Luz disponible"},
    "facts.vs_zone_below":         {"en": "−{pct}% per m² vs zone",                       "es": "−{pct}% por m² vs zona"},
    "facts.vs_zone_above":         {"en": "+{pct}% per m² vs zone",                       "es": "+{pct}% por m² vs zona"},
    "facts.bed_bath":              {"en": "{beds} bed · {baths} bath",                    "es": "{beds} hab · {baths} baño"},
    "facts.built_m2":              {"en": "{n} m² built",                                 "es": "{n} m² construidos"},
    "facts.lot_m2":                {"en": "{n} m² lot",                                   "es": "{n} m² terreno"},
    "facts.listed_new":            {"en": "New this week",                           "es": "Nueva esta semana"},
    "facts.listed_days":           {"en": "{n} days on market",                           "es": "{n} días en el mercado"},
    # ── Pro Welcome (one-shot, fires after first successful Stripe payment) ──
    # Email subject — Resend `subject` field. Kept short so it doesn't
    # truncate in narrow inbox previews (Gmail mobile snippet is ~38 chars).
    "welcome.email.subject":       {"en": "Welcome to Pulpo Pro — your first 10",          "es": "Bienvenido a Pulpo Pro — tus primeras 10"},
    # Hero
    "welcome.hero.eyebrow":        {"en": "Welcome to Pulpo Pro",                         "es": "Bienvenido a Pulpo Pro"},
    "welcome.hero.headline.named": {"en": "Welcome, {name}.",                              "es": "Bienvenido, {name}."},
    "welcome.hero.headline.unnamed": {"en": "Welcome aboard.",                             "es": "Bienvenido a bordo."},
    "welcome.hero.lede":           {"en": "Pulpo covers the coast and the lakes — Coatepeque, Ilopango, the surf strip from El Tunco to El Cuco — and that's all we cover. Ranked by value, refreshed weekly. Your first 10 are below; same shape every Sunday from here.",
                                     "es": "Pulpo cubre la costa y los lagos — Coatepeque, Ilopango, la franja surfera de El Tunco a El Cuco — y nada más. Clasificada por valor, revisada cada semana. Tus primeras 10 están abajo; mismo formato cada domingo."},
    # NOTE: the welcome is the General master with ONLY the hero swapped
    # (render_html variant="welcome"), so the body's editorial blocks come
    # from the shared `section.*` / `spotlight.*` / `yp.*` keys — there are
    # no welcome-only how-it-works / cadence / start-here / picks-intro
    # strings anymore. Only welcome.email.subject + welcome.hero.* above are
    # welcome-specific; the welcome-back derives from them via welcome_text.

    # ── Pulpo Pro Welcome BACK (resubscribe) ──────────────────────────────
    # NO stored welcome_back.* copy. The welcome-back email is the SAME
    # email as the first-time welcome (one shared template, toggled by
    # `variant="welcome_back"`) AND its copy is DERIVED from the `welcome.*`
    # strings at render time by `welcome_text()` below — never hand-kept in
    # parallel. Editing any `welcome.*` string automatically flows to the
    # welcome-back; the two are identical save the "welcome → welcome back"
    # (and "first 10 → next 10") rewrite. They cannot drift because there
    # is one source of copy, not two. See `welcome_text` + the parity test
    # in tests/newsletter/components/test_welcome_back_render.py.
}


def t(key: str, locale: Locale = DEFAULT_LOCALE, **fmt) -> str:
    row = STRINGS.get(key)
    if row is None:
        return key
    text = row.get(locale) or row.get(DEFAULT_LOCALE) or key
    if fmt:
        try:
            return text.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return text
    return text


# ── Welcome → Welcome-back copy derivation ────────────────────────────────
# The resubscribe "welcome-back" email is the first-time welcome with the
# greeting reworded. Rather than store a parallel set of welcome_back.*
# strings (which would silently drift the moment someone edits one side),
# the welcome-back copy is DERIVED from the `welcome.*` strings at render
# time: exactly two locale-aware rewrites turn a welcome string into its
# welcome-back form. One source of copy → the two emails are guaranteed
# identical save these rewrites.
#
# The rewrites are deliberately narrow so they touch ONLY the greeting +
# the "first 10" framing and never mangle body copy:
#   1. Leading greeting word → its "back" form (anchored at string start,
#      so a mid-sentence "welcome"/"bienvenido" is never touched).
#   2. The literal "first 10" / "primeras 10" count → "next 10" /
#      "próximas 10".
# `welcome_text` is applied ONLY to the hero strings + picks-intro title +
# subject — the surgical set where "welcome"/"first 10" can appear. Shared
# blocks (how-it-works, cadence, picks body, start-here, footer) render
# through plain `t()`, untouched, so they're byte-identical in both emails.
_WELCOMEBACK_REWRITES: dict[str, list] = {
    "en": [
        (re.compile(r"^Welcome\b"), "Welcome back"),
        ("first 10", "next 10"),
    ],
    "es": [
        (re.compile(r"^Bienvenido\b"), "Bienvenido de nuevo"),
        ("primeras 10", "próximas 10"),
    ],
}


def welcome_text(key_suffix: str, locale: Locale = DEFAULT_LOCALE, *,
                 variant: str = "welcome", **fmt) -> str:
    """Resolve a `welcome.<key_suffix>` string, applying the welcome-back
    rewrite when `variant == "welcome_back"`.

    This is the single entry point for welcome / welcome-back hero +
    subject + picks-title copy. There is no separate welcome_back.* table —
    the welcome-back string is a pure function of the welcome string, so
    the two emails can never diverge beyond the documented rewrite."""
    base = t(f"welcome.{key_suffix}", locale, **fmt)
    if variant != "welcome_back":
        return base
    rules = _WELCOMEBACK_REWRITES.get(locale) or _WELCOMEBACK_REWRITES[DEFAULT_LOCALE]
    out = base
    for pattern, repl in rules:
        if isinstance(pattern, str):
            out = out.replace(pattern, repl)
        else:
            out = pattern.sub(repl, out, count=1)
    return out


def filter_summary(pref, locale: Locale = DEFAULT_LOCALE) -> str:
    """Render a Preference as a human filter line ("La Libertad · Under $500k · Land OK")."""
    parts: list[str] = []
    if pref.departments:
        parts.extend(d.title() for d in pref.departments[:2])
    elif pref.zones:
        parts.extend(z.replace("-", " ").title() for z in pref.zones[:2])
    if pref.max_price_usd:
        if locale == "es":
            parts.append(f"hasta ${int(pref.max_price_usd):,}")
        else:
            parts.append(f"under ${int(pref.max_price_usd):,}")
    if pref.property_types:
        if "land" in pref.property_types:
            parts.append(t("facts.land", locale) + " OK")
        if "house" in pref.property_types:
            parts.append(t("facts.house", locale))
        if "condo" in pref.property_types:
            parts.append(t("facts.condo", locale))
    if not parts:
        return "default"
    return " · ".join(parts)
