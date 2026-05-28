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
    "hero.eyebrow.unnamed":        {"en": "Hand-picked this fortnight",                   "es": "Selección de esta quincena"},
    "hero.eyebrow.anon":           {"en": "The 10 best, this fortnight",                  "es": "Las 10 mejores, esta quincena"},
    "hero.headline.default":       {"en": "The 10 best, this fortnight.",                 "es": "Las 10 mejores, esta quincena."},
    "hero.lede.with_prefs":        {"en": f"Pulpo scanned {{n_scanned}} active beach and lake properties across {_country_en} this fortnight. These ten matched your filter closely enough to make the cut.",
                                     "es": f"Pulpo revisó {{n_scanned}} propiedades activas frente al mar y al lago en {_country_es} esta quincena. Estas diez encajan con tu filtro lo suficiente para entrar."},
    "hero.lede.no_prefs":          {"en": "Pulpo scanned {n_scanned} active properties this fortnight and ranked them by value, location and momentum. You'll get a sharper edition once you set a filter — link at the bottom.",
                                     "es": "Pulpo revisó {n_scanned} propiedades esta quincena y las clasificó por valor, ubicación y momentum. Recibirás una edición más afinada cuando configures un filtro — enlace al final."},
    # ── At a glance ──
    "glance.eyebrow":              {"en": "At a glance",                                  "es": "Vistazo rápido"},
    "glance.subhead.with_skip":    {"en": "{kept} to consider. One to skip.",             "es": "{kept} para considerar. Una para saltar."},
    "glance.subhead.no_skip":      {"en": "{kept} to consider.",                          "es": "{kept} para considerar."},
    # ── Pick / shortlist labels ──
    "pick.top_label":              {"en": "🏆 Top pick · {rank:02d}",                     "es": "🏆 Selección · {rank:02d}"},
    "pick.new_pill":               {"en": "New this fortnight",                           "es": "Nueva esta quincena"},
    "pick.repriced_pill":          {"en": "Price moved",                                  "es": "Precio movido"},
    # PR-NL-5 (v2.4 redesign): every pick CTA goes to pulpo.club, not the
    # external source. The dual CTA on hero picks is `cta_open` (solid
    # "See on Pulpo →") + `cta_save` (ghost "Save to favorites"). The
    # source-aware `cta_view_on` / `cta_view` from v2.2 are deleted —
    # the rich-pick CTA now points at pulpo_url, not listing_url.
    "pick.cta_open":               {"en": "See on Pulpo →",                               "es": "Ver en Pulpo →"},
    "pick.cta_save":               {"en": "Save to favorites",                            "es": "Guardar en favoritos"},
    # Price-anchored unlock — "$9.99/mo" matches the canonical pricing
    # source-of-truth (project_post_stripe_activation_series memory).
    "pick.cta_locked":             {"en": "Unlock this pick — $9.99/mo →",                "es": "Desbloquear esta selección — $9.99/mes →"},
    "pick.paywall_blurb":          {"en": "Pulpo Pro reveals the address, the broker file, and the full underwriting. Free members see the photo and the headline.",
                                     "es": "Pulpo Pro revela la dirección, la ficha del corredor y el análisis completo. Los miembros gratuitos ven foto y titular."},
    "shortlist.eyebrow":           {"en": "The shortlist",                                "es": "La lista corta"},
    "shortlist.headline":          {"en": "{n} more — situational picks.",                "es": "{n} más — selecciones situacionales."},
    "shortlist.lede":              {"en": "Each one is the right answer for a specific buyer. Read the frame first; skip if it isn't yours.",
                                     "es": "Cada una es la respuesta correcta para un comprador específico. Lee el marco primero; salta si no es el tuyo."},
    # ── Skip ──
    "skip.eyebrow":                {"en": "Skip this one",                                "es": "Esta sí, sáltala"},
    # ── Market context ──
    "market.eyebrow":              {"en": "Market context",                               "es": "Contexto del mercado"},
    "market.headline":             {"en": "Worth knowing this fortnight.",                "es": "Vale la pena saber esta quincena."},
    "one_number.eyebrow":          {"en": "One number worth knowing",                     "es": "Un número que vale la pena saber"},
    # ── Next issue ──
    "next.eyebrow":                {"en": "Next issue",                                   "es": "Próxima edición"},
    "next.body":                   {"en": "Pulpo will scan the next 14 days of inventory against your filter and ship the next ten. Adjust filters anytime — changes apply to the next issue.",
                                     "es": "Pulpo revisará los próximos 14 días de inventario contra tu filtro y enviará las próximas diez. Ajusta filtros cuando quieras — los cambios aplican a la siguiente edición."},
    # v2.2: product-language CTA tied to the editorial framing of the
    # newsletter ("the picks I see"), not generic settings-speak.
    "next.cta":                    {"en": "Tune what you see →",                          "es": "Ajusta lo que ves →"},
    "next.cta.anon":               {"en": "Set your filter →",                            "es": "Configura tu filtro →"},
    # ── Your Pulpo (PR-NL-8) — dark panel above the footer ──
    "yp.eyebrow":                  {"en": "Your Pulpo",                                   "es": "Tu Pulpo"},
    "yp.title":                    {"en": "Pick up where you left off.",                  "es": "Continúa donde lo dejaste."},
    "yp.saved.label":              {"en": "{n} saved listings from past issues",          "es": "{n} propiedades guardadas en ediciones anteriores"},
    "yp.saved.cta":                {"en": "Open your favorites →",                        "es": "Abrir tus favoritos →"},
    "yp.filter.cta":               {"en": "Edit your filter →",                           "es": "Editar tu filtro →"},
    "yp.browse.label":             {"en": "{n} listings in your filter right now",        "es": "{n} propiedades en tu filtro ahora"},
    "yp.browse.cta":               {"en": "Browse them all →",                            "es": "Explorar todas →"},
    # ── Paywall (free tier) ──
    "paywall.eyebrow":             {"en": "Free edition",                                 "es": "Edición gratuita"},
    "paywall.headline":            {"en": "You're seeing the public cut.",                "es": "Estás viendo el corte público."},
    "paywall.body":                {"en": "Pulpo Pro lifts the curtain on every pick — address, broker contact, full underwriting, and the negotiation lever the seller doesn't know we know about. Same fortnight cadence, eight times the depth.",
                                     "es": "Pulpo Pro levanta el telón en cada selección — dirección, contacto del corredor, análisis completo y la palanca de negociación que el vendedor no sabe que conocemos. Misma cadencia quincenal, ocho veces la profundidad."},
    # Aligned with the canonical $9.99/mo price (web/app/lib/pricing.ts +
    # web/app/config/legal-content.ts). The v2.1 newsletter shipped with
    # $19/month which was stale drift — fixed in v2.2.
    "paywall.cta":                 {"en": "Go Pro — $9.99/month →",                       "es": "Hazte Pro — $9.99/mes →"},
    # ── Footer ──
    "footer.tagline":              {"en": f"Every beach and lake home in {_country_en}, ranked by value.",
                                     "es": f"Cada casa frente al mar y al lago en {_country_es}, clasificada por valor."},
    "footer.you_get_this":         {"en": "You're getting this because your filter is set to {filter_summary}.",
                                     "es": "Recibes esto porque tu filtro está configurado en {filter_summary}."},
    "footer.you_get_this.no_prefs": {"en": "You're getting this because you signed up — we haven't captured your filter yet.",
                                     "es": "Recibes esto porque te suscribiste — aún no hemos capturado tu filtro."},
    "footer.change_filters":       {"en": "Change filters",                               "es": "Cambiar filtros"},
    "footer.change_cadence":       {"en": "Change cadence",                               "es": "Cambiar cadencia"},
    "footer.unsubscribe":          {"en": "Unsubscribe",                                  "es": "Cancelar suscripción"},
    "footer.no_commission":        {"en": "Pulpo doesn't take commission and doesn't list its own properties. We pick from what's already on the market and tell you which ones are worth your time.",
                                     "es": "Pulpo no cobra comisión ni publica sus propias propiedades. Elegimos de lo que ya está en el mercado y te decimos cuáles merecen tu tiempo."},
    "footer.copyright":            {"en": "© {year} Pulpo Club",
                                     "es": "© {year} Pulpo Club"},
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
    "facts.listed_new":            {"en": "New this fortnight",                           "es": "Nueva esta quincena"},
    "facts.listed_days":           {"en": "{n} days on market",                           "es": "{n} días en el mercado"},
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
