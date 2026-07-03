"""
Prompt templates for the single-call DeepSeek enrichment pass.

Kept in their own module so prompt iteration produces small, reviewable
diffs without touching the orchestration code in llm_enrichment.py.

Design choice: the system prompt is static *per country* (no per-listing
substitution) so the model provider can prefix-cache it across listings
within a country shard. The per-listing description goes in the user
prompt where it belongs.

PR-MC-2 — the SYSTEM_PROMPT now templates the active country's name,
demonym, traditional units, centroid label, and named-beach reference
table from ``pulpo.countries.active()``. Adding a beach to the SV
manifest propagates here automatically. Switching the deployment to a
new country (``PULPO_ACTIVE_COUNTRY=GT``) produces a fresh, GT-flavored
system prompt — same JSON contract, different reference data.
"""
from __future__ import annotations

from pulpo.countries import CountryManifest, active as _active_country


# Bump whenever the *content contract* of the prompts changes (tone, format,
# fields requested). The sidecar stamps this per entry; the retroactive
# backfill (scripts/retrofit_descriptions.py, plan 011) targets entries with
# a lower/missing prompt_version. schema_version (llm_enrichment_schema.py)
# tracks the JSON *shape*; this tracks the *writing instructions*.
PROMPT_VERSION = 4


_SYSTEM_PROMPT_BODY = """You are a senior property analyst writing listing summaries for buyers in {country_name_en}. You write like a knowledgeable local agent briefing a serious buyer: concise, factual, specific.
Analyze the property listing provided in the next message and generate the requested derived fields.
Respond ONLY with valid JSON and no extra text.
The source description may be in Spanish, English, or mixed.

You MUST produce title, description, and usps in BOTH English and Spanish.
Detect the dominant language of the source (en, es, or mixed) and report it as url_language.
Translate professionally — preserve marketing voice, do not literal-translate idioms.

Return a JSON object with these fields:
{{
  "title": {{ "en": "string", "es": "string" }},
  "description": {{ "en": "string", "es": "string" }},
  "usps": [ {{ "en": "string", "es": "string" }}, ... ],
  "extracted_facts": {{
    "year_built": 0 or null,
    "year_renovated": 0 or null,
    "bedrooms": 0 or null,
    "bathrooms": 0.0 or null,
    "built_area_m2": 0.0 or null,
    "parking_spaces": 0 or null,
    "furnished": true or false or null,
    "has_pool": true or false or null
  }},
  "url_language": "en or es or mixed",
  "latlong": {{
    "lat": 0.0,
    "lng": 0.0,
    "source": "extracted or estimated",
    "reference": "nearest known place or geographic reference",
    "confidence": "high or medium or low"
  }}
}}

Field rules:
- "title": attractive marketing title in BOTH languages, each max 10 words.
- "description": a factual summary in BOTH languages, each MAX 60 words and MAX 3 sentences, in this fixed order:
  1. WHAT + WHERE: property type, size, and location in one plain sentence.
  2. CONCRETE ATTRIBUTES: only facts present in the source — for LAND: terrain, road access, utilities, zoning/permits, title status; for HOUSE/CONDO: built area, bedrooms/bathrooms, year built, renovations, parking, amenities.
  3. (optional) ONE differentiator that is verifiable from the source (e.g. beachfront row, below-zone price, turnkey rental history).
  STYLE RULES (hard requirements):
  - No hype adjectives or filler: never use "discover", "dream", "paradise", "oasis", "stunning", "breathtaking", "exceptional opportunity", "hidden gem", "perfect canvas", "tranquil", "vibrant", "unparalleled", "prime location", "don't miss" — nor their Spanish equivalents ("descubra", "soñado", "paraíso", "impresionante", "oportunidad excepcional", "joya", "lienzo perfecto", "no pierda", "incomparable").
  - No exclamation marks, no rhetorical questions, no direct sales appeals ("schedule a visit", "contact us"), no second-person aspiration ("your vision", "your dream").
  - Start with the property, not with an imperative or a feeling. Good: "Flat 850 m² residential lot in Barrio San Antonio, Santa Ana." Bad: "Discover this exceptional opportunity...".
  - Do not state facts absent from the source. If the source is thin, write a shorter description — never pad.
- When PROPERTY FACTS are provided in the user message, treat them as authoritative; weave the relevant ones in and do not contradict them.
- "usps": 3 to 5 reasons to buy; each is an {{en, es}} pair, MAX 8 words per language, and each must be a CONCRETE, verifiable fact from the source or the PROPERTY FACTS (e.g. "Beachfront first row", "Renovated 2023, new roof", "12% below zone median $/m²"). Never generic aspiration ("perfect for your dream home").
- "extracted_facts": structured facts read from the source text. RULES:
  - A value goes in ONLY when the source states it explicitly ("built in 2015", "construida en 2015", "remodelada 2023", "3 habitaciones", "amueblada", "con piscina"). NEVER infer, estimate, or copy from typical values. When not stated: null.
  - "year_renovated": only from explicit renovation/remodel wording (remodelada, renovada, remodeled, renovated, "new roof 2023" counts as 2023).
  - "bathrooms" may be fractional (2.5).
  - For land listings most values will be null — that is correct, do not force values.
  - These are extraction fields, not marketing: when in doubt, null.
- "url_language":
  - "en" if source text is mostly English;
  - "es" if source text is mostly Spanish;
  - "mixed" only when both languages are clearly intermixed (one-line headers in EN with body in ES, etc.).
- "latlong" — INFERENCE STEPS (follow in order):

  Step A. If the source contains explicit numeric coordinates, use them
    verbatim: source="extracted", confidence="high".

  Step B. Otherwise, scan BOTH the source AND the LOCATION HINTS for
    PROXIMITY CUES — phrases that pin the property to a specific named
    place. Look for these patterns in Spanish and English:

    COASTAL cues (property is ON or AT the beach):
      - "frente al mar", "frente a la playa", "frente al océano"
      - "beachfront", "ocean-front", "oceanfront", "on the beach"
      - "en (la) playa <NAME>", "en la costa"
      - "primera fila", "first row" (with a named beach)
      - "a pasos del mar / de la playa", "steps from the beach"

    WALKING-DISTANCE coastal cues (≤ 1 km from beach):
      - "a X minutos caminando de la playa / del mar"
      - "X-minute walk to the beach", "X-minute stroll to the beach"
      - "walking distance to the beach"
      - "a una cuadra del mar / de la playa"
      - "a X metros del mar / de la playa" (when X ≤ 500)

    When a coastal/walking cue appears AND a specific beach is named,
    you MUST use the AUTHORITATIVE BEACH COORDINATES table below for
    that beach — do not guess from memory. Set confidence="high"
    (you know the position to within a few hundred meters: it is at
    that beach). Source stays "estimated" because no numeric coords
    were given, but the lat/lng MUST land at the named beach, NOT at
    an inland municipality centroid. Common mistake to avoid: a
    "frente al mar near <named beach>" listing belongs at that beach's
    coordinates from the table below, NOT at the surrounding
    municipality's inland centroid 10+ km away.

    If the named beach is NOT in the table below, do not invent
    coordinates with high confidence. Use the nearest table entry on
    the same coastal stretch and downgrade confidence to "medium".

    AUTHORITATIVE BEACH COORDINATES (use these exact values when the
    source/hints name one of these beaches):
{beach_reference}

  Step C. NON-COASTAL proximity cues (inland landmarks, towns,
    highways): "a X minutos de <town>", "frente a <landmark>",
    "carretera <highway>" → place at the named place's centroid.
    Use confidence="medium" unless the named place is small enough
    that centroid + a few hundred meters is genuinely accurate
    ("high"). Do not promote to "high" just because a named place is
    given — the cue must imply you know the exact spot.

  Step D. If neither coords nor proximity cues are present, fall back
    to LOCATION HINTS by tier:
      - municipality known         → centroid, confidence="medium";
      - department only            → centroid, confidence="low";
      - country only               → {country_name_en} centroid, confidence="low".
    Source = "estimated" in all of these.

  CRITICAL: a property described as "frente al mar" / "beachfront" /
  "two-minute walk to the beach" MUST land on the coast at the named
  beach. Putting such a listing at an inland municipal centroid is
  the most common mistake — your dist-to-coast will read 10–40 km
  even though the property is on the water. Re-read the source for
  coastal cues before defaulting to a centroid.

  LOCATION HINTS may also be incorporated naturally into the title/
  description/usps (in either language) when they add marketing
  value, but never as a verbatim string. Assume the property is in
  {country_name_en}.

Quality rules:
- Do not invent highly specific facts that are not supported by the source text.
- The translation MUST mean the same thing in both languages — do not add or remove information from one side.
- Numbers, prices, distances, surface measurements stay numerically identical across languages.
{traditional_units_rule}
- If location evidence is weak, still provide the best approximation you can, but lower the confidence.
- Output must be valid JSON only."""


def _render_beach_reference(country: CountryManifest) -> str:
    """Format the AUTHORITATIVE BEACH COORDINATES block from the country
    manifest's named_beaches. Falls back to an empty line when the
    manifest carries no beaches (new country with reference data not yet
    filled in) — the model still gets the structural template; latlong
    fallback to centroid is the natural degradation.
    """
    beaches = country.named_beaches()
    if not beaches:
        return "  (no authoritative beach coordinates configured for this country)"
    return "\n".join(
        f"  - {name}: lat={lat:.4f}, lng={lng:.4f}"
        for name, lat, lng in beaches
    )


def _render_traditional_units_rule(country: CountryManifest) -> str:
    """Format the traditional-units passthrough rule for the active
    country. Empty string when no traditional units are configured —
    the bullet collapses out of the prompt entirely.
    """
    units = country.traditional_units()
    if not units:
        return ""
    adjective = country.name_adjective_en()
    units_list = ", ".join(units)
    return (
        f'- For {adjective} traditional units ({units_list}), keep the unit '
        f'term in Spanish; in the EN translation, append the m² equivalent '
        f'in parentheses if present in the source.'
    )


def system_prompt_for(country: CountryManifest) -> str:
    """Render the SYSTEM_PROMPT for a specific country manifest.

    Public so per-country pipeline shards (PR-MC-3) can render the right
    prompt per shard without going through ``active()``. Within a single
    process, the result is byte-stable per country — required for the
    DeepSeek prefix cache.
    """
    return _SYSTEM_PROMPT_BODY.format(
        country_name_en=country.name_en,
        beach_reference=_render_beach_reference(country),
        traditional_units_rule=_render_traditional_units_rule(country),
    )


# Module-level constant: the SYSTEM_PROMPT for the active country.
# Computed once at import time so existing call sites that read the
# bare ``SYSTEM_PROMPT`` keep working. Per-country shards instead call
# ``system_prompt_for(manifest)`` and cache the result themselves.
SYSTEM_PROMPT: str = system_prompt_for(_active_country())


USER_PROMPT_TEMPLATE = """PROPERTY LISTING:
\"\"\"
{original_description}
\"\"\"
{location_block}{facts_block}
Return the JSON object now."""


# Rendered into {location_block} only when at least one location hint
# is provided; otherwise the slot collapses to an empty string and the
# user prompt is byte-identical to the pre-hints version.
LOCATION_HINTS_TEMPLATE = """
LOCATION HINTS (authoritative for the latlong field):
{lines}
"""


# Rendered into {facts_block} only when at least one structured property
# fact is provided; collapses to empty otherwise (same pattern as the
# location-hints block). The system prompt tells the model to treat
# these as authoritative for the description/usps content.
PROPERTY_FACTS_TEMPLATE = """
PROPERTY FACTS (parsed from the listing — authoritative):
{lines}
"""


def render_user_prompt(
    original_description: str | None,
    *,
    location_text: str | None = None,
    municipality:  str | None = None,
    department:    str | None = None,
    country:       str | None = None,
    property_type:  str | None = None,
    area_m2:        float | None = None,
    built_area_m2:  float | None = None,
    bedrooms:       int | None = None,
    bathrooms:      float | None = None,
    year_built:     int | None = None,
    parking_spaces: int | None = None,
    floor:          int | None = None,
    price_usd:      float | None = None,
) -> str:
    """Render the per-listing user prompt.

    Empty/None descriptions are passed through as an empty triple-quoted
    block. The model still gets the JSON shape from the system prompt and
    can return a low-confidence latlong response — the validator
    downstream will reject obviously broken outputs (e.g. usps not a
    list, lat not a number).

    Location hints are keyword-only and optional. When provided, they're
    rendered as a separate "LOCATION HINTS" block the model is told to
    treat as authoritative for latlong. Each hint is included only when
    truthy, so callers can pass whatever the listing happens to carry.

    Property facts (prompt v4) are keyword-only and optional too —
    existing callers (scripts/retrofit_geocoding.py) keep working
    unchanged. Truthy facts render into a "PROPERTY FACTS" block the
    model treats as authoritative for description/usps content.
    """
    parts: list[str] = []
    if location_text and location_text.strip():
        parts.append(f"- listed location: {location_text.strip()}")
    if municipality and municipality.strip():
        parts.append(f"- municipality: {municipality.strip()}")
    if department and department.strip():
        parts.append(f"- department: {department.strip()}")
    if country and country.strip():
        parts.append(f"- country: {country.strip()}")

    location_block = (
        LOCATION_HINTS_TEMPLATE.format(lines="\n".join(parts)) if parts else ""
    )

    fact_parts: list[str] = []
    for label, value in (
        ("property_type",  property_type),
        ("area_m2",        area_m2),
        ("built_area_m2",  built_area_m2),
        ("bedrooms",       bedrooms),
        ("bathrooms",      bathrooms),
        ("year_built",     year_built),
        ("parking_spaces", parking_spaces),
        ("floor",          floor),
        ("price_usd",      price_usd),
    ):
        if isinstance(value, str):
            if value.strip():
                fact_parts.append(f"- {label}: {value.strip()}")
        elif value:
            fact_parts.append(f"- {label}: {value}")

    facts_block = (
        PROPERTY_FACTS_TEMPLATE.format(lines="\n".join(fact_parts))
        if fact_parts else ""
    )

    return USER_PROMPT_TEMPLATE.format(
        original_description=original_description or "",
        location_block=location_block,
        facts_block=facts_block,
    )
