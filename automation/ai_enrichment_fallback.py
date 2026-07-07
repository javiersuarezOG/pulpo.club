"""
Deterministic fallbacks for two of three PRD §FR-6 AI tasks.

When OPENAI_API_KEY is missing, the key has no credits, the API rate-
limits us, or any other reason makes a live call impossible, we still
ship 2 of 3 Phase 1 AI fields populated:

- `title_canonical` — PRD §8.1 format is `[Land Type] · [Size] · [Zone]
  · [Top Feature]`. Top-Feature priority list is fully deterministic
  (beachfront → ocean view → water body → off-market → price reduced
  → utilities connected → flat → omitted). Build from existing fields.

- `reasons_to_buy` — PRD §8.3 USP trigger table has 14 deterministic
  rules. Pick the first 3 that apply, substitute placeholders, ship.

- `short_description_canonical` — PQAB structure (§8.2) genuinely needs
  natural-language flow. Cannot be templated cleanly. Stays None when
  AI is unavailable.

All three functions are pure: same inputs → same outputs, no I/O. They
read from a Listing dict (or any object with the same field names) so
they're equally usable in production (run.py) and in tests.
"""
from __future__ import annotations
from typing import Any

from automation.property_types import PROPERTY_TYPES


# PRD §8.1 — Land-type labels for the title.
# Legacy strings only — pre-PR-#64 normalize.detect_property_type emitted
# these as `property_type` values. Kept for backwards compat with old
# fixtures + already-shipped data. Canonical types (land/house/condo)
# read from PROPERTY_TYPES via _type_label() instead so the label stays
# in sync with property_types.py's title_canonical_template.
_LEGACY_TYPE_LABELS = {
    "residential":  "Residential Lot",
    "commercial":   "Commercial Land",
    "recreational": "Recreational Land",
    "mixed":        "Mixed-Use Land",
    "raw":          "Raw Land",
    "lot":          "Residential Lot",
}

# Backwards-compat alias for any external test/import that still uses the
# old name. New code should call _type_label() instead.
LAND_TYPE_LABELS = _LEGACY_TYPE_LABELS

# Spanish renderings of every English label this module can emit. The
# fallback templates are deterministic, so the Spanish side is templated
# too — the correct fix for a producer that must be bilingual (rather than
# round-tripping fixed strings through the translator). Keyed by the exact
# English label the EN helpers return; an unmapped label falls back to the
# English text on BOTH sides (safe: worst case is an untranslated label,
# never a crash — and the contract test in tests/ flags any gap).
_TYPE_LABEL_ES: dict[str, str] = {
    "Raw Land":        "Terreno",
    "Beach House":     "Casa de playa",
    "Beach Condo":     "Condominio de playa",
    "Residential Lot": "Lote residencial",
    "Commercial Land": "Terreno comercial",
    "Recreational Land": "Terreno recreativo",
    "Mixed-Use Land":  "Terreno de uso mixto",
}

_FEATURE_ES: dict[str, str] = {
    "Beachfront":          "Frente al mar",
    "Ocean View":          "Vista al mar",
    "Waterfront":          "Frente al agua",
    "Off-Market":          "Fuera de mercado",
    "Price Reduced":       "Precio rebajado",
    "Utilities Connected": "Servicios conectados",
    "Flat Terrain":        "Terreno plano",
}


def _type_label(pt: str) -> str:
    """Return the title-prefix label for a property_type.

    Resolution order:
      1. PROPERTY_TYPES[pt]: derive from title_canonical_template's
         leading segment ("Beach House · {zone}" → "Beach House"). This
         keeps the label in lockstep with property_types.py — change one,
         change both. Covers land/house/condo (the canonical 3 types).
      2. _LEGACY_TYPE_LABELS: pre-PR-#64 strings that historical data
         may carry (lot/finca/residential/etc.).
      3. "Raw Land" default.
    """
    cfg = PROPERTY_TYPES.get(pt)
    if cfg:
        template = cfg.get("title_canonical_template", "")
        # Templates are "{prefix} · {placeholder}" — split on the first
        # " · {" so the prefix survives even if the template gains more
        # placeholders later.
        prefix = template.split(" · {", 1)[0]
        return prefix or "Raw Land"
    return _LEGACY_TYPE_LABELS.get(pt) or "Raw Land"


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


# ── title_canonical fallback ───────────────────────────────────────────

def _format_size(area_m2: Any) -> str | None:
    """PRD §8.1: ≥10,000 m² → ha; else m². Comma-separate thousands."""
    if not isinstance(area_m2, (int, float)) or area_m2 <= 0:
        return None
    if area_m2 >= 10_000:
        ha = round(area_m2 / 10_000, 1)
        # Drop trailing .0 for whole numbers
        return f"{ha:g} ha"
    return f"{int(round(area_m2)):,} m²"


def _top_feature(li: Any) -> str | None:
    """PRD §8.1 priority order — first match wins."""
    if _g(li, "is_beachfront") is True:
        return "Beachfront"
    if _g(li, "has_ocean_view") is True:
        return "Ocean View"
    if _g(li, "has_water_body") is True:
        return "Waterfront"
    if _g(li, "source_type") == "off_market":
        return "Off-Market"
    if _g(li, "is_repriced") is True:
        return "Price Reduced"
    if _g(li, "readiness_score") == 3:
        return "Utilities Connected"
    if _g(li, "is_flat") is True:
        return "Flat Terrain"
    return None


def _zone_name(li: Any) -> str | None:
    """Prefer the canonical zone slug; fall back to municipality / department."""
    z = _g(li, "zone")
    if isinstance(z, str) and z:
        # Title-case the slug: "el-tunco" → "El Tunco"
        return " ".join(part.capitalize() for part in z.split("-"))
    m = _g(li, "municipality")
    if isinstance(m, str) and m:
        return m
    d = _g(li, "department")
    if isinstance(d, str) and d:
        return d
    return None


def _type_label_es(pt: str) -> str:
    """Spanish rendering of the title-prefix label; falls back to EN."""
    en = _type_label(pt)
    return _TYPE_LABEL_ES.get(en, en)


def fallback_title(li: Any) -> dict | None:
    """Build the bilingual [Type] · [Size] · [Zone] · [Top Feature] title.

    Returns ``{"en": ..., "es": ...}`` — bilingual so a Spanish-locale
    user never sees an English template title (the exact leak this closes;
    pre-fix the fallback wrote a single English string that ``tr()`` showed
    in every locale). Size + zone segments are language-neutral (numbers,
    place names); only the type and feature labels differ per language.

    Type label is type-aware — houses produce "Beach House · …" / "Casa de
    playa · …", condos "Beach Condo" / "Condominio de playa".
    """
    en_parts: list[str] = []
    es_parts: list[str] = []
    pt = (_g(li, "property_type") or "land")
    en_parts.append(_type_label(pt))
    es_parts.append(_type_label_es(pt))

    size = _format_size(_g(li, "area_m2"))
    if size:  # numeric + unit — identical in both languages
        en_parts.append(size)
        es_parts.append(size)

    zone = _zone_name(li)
    if zone:  # proper noun — identical in both languages
        en_parts.append(zone)
        es_parts.append(zone)

    feat_en = _top_feature(li)
    if feat_en:
        en_parts.append(feat_en)
        es_parts.append(_FEATURE_ES.get(feat_en, feat_en))

    # PRD §8.1 hard cap: 80 chars, applied per language.
    en = " · ".join(en_parts)[:80]
    es = " · ".join(es_parts)[:80]
    if not en:
        return None
    return {"en": en, "es": es}


# ── reasons_to_buy fallback ────────────────────────────────────────────

# PRD §8.3 USP trigger table — first 3 applicable wins. Each entry is
# (predicate, template). Templates use {placeholders} resolved from the
# listing dict via _fill_template().
def _trigger_rules() -> list:
    """Each entry: (predicate(li) -> bool, {"en": template, "es": template}).

    Templates are bilingual — both sides deterministic so a Spanish user
    never sees an English USP bullet. Placeholders ({zone}/{photos_count}/
    {development_name}) are filled identically on both sides.
    """
    return [
        (lambda li: _g(li, "is_beachfront") is True,
         {"en": "🏖 Direct beach access — oceanfront parcel on the {zone} coast",
          "es": "🏖 Acceso directo a la playa — parcela frente al mar en la costa de {zone}"}),
        (lambda li: _g(li, "source_type") == "off_market",
         {"en": "✂ Off-market deal — not listed on any public real estate portal",
          "es": "✂ Oferta fuera de mercado — no publicada en ningún portal inmobiliario"}),
        (lambda li: _g(li, "is_repriced") is True,
         {"en": "📉 Price recently reduced — potential motivated seller, negotiate from strength",
          "es": "📉 Precio rebajado recientemente — posible vendedor motivado, negocie con ventaja"}),
        (lambda li: _g(li, "readiness_score") == 3,
         {"en": "⚡ Fully connected — water, electricity, and paved road confirmed",
          "es": "⚡ Totalmente conectado — agua, electricidad y calle pavimentada confirmadas"}),
        (lambda li: _g(li, "readiness_score") == 2,
         {"en": "✓ Two of three utilities confirmed — lower development friction",
          "es": "✓ Dos de tres servicios confirmados — menor fricción para desarrollar"}),
        (lambda li: isinstance(_g(li, "days_listed"), int) and _g(li, "days_listed") <= 7,
         {"en": "🆕 Just listed — one of {zone}'s newest additions this week",
          "es": "🆕 Recién publicado — una de las novedades de {zone} esta semana"}),
        (lambda li: _g(li, "has_ocean_view") is True,
         {"en": "🌅 Ocean views — {zone} sea views from the parcel",
          "es": "🌅 Vistas al mar — vistas al océano de {zone} desde la parcela"}),
        (lambda li: _g(li, "is_flat") is True,
         {"en": "📐 Flat terrain — minimal earthwork needed, lower build costs",
          "es": "📐 Terreno plano — mínimo movimiento de tierra, menor costo de construcción"}),
        (lambda li: _g(li, "has_water_body") is True,
         {"en": "💧 Natural water feature on or bordering the parcel",
          "es": "💧 Cuerpo de agua natural en la parcela o colindante"}),
        (lambda li: _g(li, "has_paved_access") is True,
         {"en": "🛣 Paved road access — direct vehicle access, year-round usability",
          "es": "🛣 Acceso por calle pavimentada — acceso vehicular directo todo el año"}),
        (lambda li: isinstance(_g(li, "photos_count"), int) and _g(li, "photos_count") >= 10,
         {"en": "📸 Well-documented listing — {photos_count} photos available for review",
          "es": "📸 Anuncio bien documentado — {photos_count} fotos disponibles para revisar"}),
        (lambda li: _g(li, "is_in_development") is True
                    and isinstance(_g(li, "development_name"), str)
                    and len(_g(li, "development_name") or "") > 0,
         {"en": "🏘 Inside {development_name} — development infrastructure already in place",
          "es": "🏘 Dentro de {development_name} — infraestructura del desarrollo ya instalada"}),
        (lambda li: _g(li, "zone_confidence") == "specific",
         {"en": "📍 Located in {zone} — established zone with active comparable inventory",
          "es": "📍 Ubicado en {zone} — zona consolidada con inventario comparable activo"}),
    ]


def _fill_template(template: str, li: Any) -> str | None:
    """Substitute {zone} / {photos_count} / {development_name} from listing.

    When a template references {zone} but the listing has no resolvable
    zone/municipality/department, return None to skip the rule. Rendering
    with an empty zone produced broken bullets like "one of 's newest
    additions" or "on the  coast" — observed in the 2026-05-07 nightly's
    fallback path for two zone-unresolved bienesraices listings.
    """
    z = _zone_name(li)
    if "{zone}" in template and not z:
        return None
    pc = _g(li, "photos_count") or 0
    dn = _g(li, "development_name") or "this development"
    try:
        return template.format(
            zone           = z or "",
            photos_count   = pc,
            development_name = dn,
        )
    except (KeyError, IndexError):
        return None


def _cap_words(bullet: str, max_words: int = 18) -> str:
    """PRD §8.3 size cap: 10-15 words. Truncate at 18 for safety. Applied
    per language, so EN and ES may cut at different points — acceptable,
    each side is independently well-formed."""
    words = bullet.split()
    return " ".join(words[:max_words]) if len(words) > max_words else bullet


def fallback_reasons_to_buy(li: Any, max_n: int = 3) -> list[dict]:
    """Apply the §8.3 trigger table; return first max_n applicable bilingual
    bullets as ``[{"en": ..., "es": ...}, ...]``. A rule whose {zone}
    placeholder can't resolve is skipped on BOTH sides together (the EN and
    ES templates reference the same placeholders)."""
    out: list[dict] = []
    for predicate, template in _trigger_rules():
        try:
            if not predicate(li):
                continue
        except Exception:
            continue
        en = _fill_template(template["en"], li)
        es = _fill_template(template["es"], li)
        if not en or not es:
            continue
        out.append({"en": _cap_words(en), "es": _cap_words(es)})
        if len(out) >= max_n:
            break
    return out


# ── orchestrator ───────────────────────────────────────────────────────

def _is_bilingual_title(v: Any) -> bool:
    """A real (AI or already-upgraded) bilingual title we must NOT overwrite."""
    return isinstance(v, dict) and bool(v.get("en")) and bool(v.get("es"))


def _is_bilingual_reasons(v: Any) -> bool:
    """A reasons_to_buy list we must NOT overwrite: non-empty and every
    entry is a bilingual {en, es} dict."""
    return (
        isinstance(v, list) and len(v) > 0
        and all(isinstance(x, dict) and x.get("en") and x.get("es") for x in v)
    )


def apply_fallbacks(li: Any) -> dict:
    """Set (or UPGRADE) title_canonical and reasons_to_buy on the listing.

    Does NOT touch short_description_canonical — that field requires
    real natural-language generation and stays None when AI is
    unavailable.

    Overwrite policy (post-2026-07-06 bilingual fix): a field is written
    when it is missing, empty, OR carries a legacy MONOLINGUAL value (a
    plain string title, or a reasons list containing any string entry).
    A field already holding a complete bilingual ``{en, es}`` value (real
    AI enrichment, or a prior bilingual fallback) is preserved. This makes
    the pass self-healing — a listing that shipped a monolingual English
    fallback string upgrades to bilingual on the next run, deterministically
    and with no API call, so a Spanish-locale user stops seeing English copy.

    Returns a dict of what was written (for logging).
    """
    title = fallback_title(li)
    reasons = fallback_reasons_to_buy(li)
    written: dict[str, Any] = {}
    if title and not _is_bilingual_title(_g(li, "title_canonical")):
        if isinstance(li, dict):
            li["title_canonical"] = title
        else:
            setattr(li, "title_canonical", title)
        written["title_canonical"] = title
    if reasons and not _is_bilingual_reasons(_g(li, "reasons_to_buy")):
        if isinstance(li, dict):
            li["reasons_to_buy"] = reasons
        else:
            setattr(li, "reasons_to_buy", reasons)
        written["reasons_to_buy"] = reasons
    return written
