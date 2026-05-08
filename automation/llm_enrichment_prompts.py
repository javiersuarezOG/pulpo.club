"""
Prompt templates for the single-call DeepSeek enrichment pass.

Kept in their own module so prompt iteration produces small, reviewable
diffs without touching the orchestration code in llm_enrichment.py.

Design choice: the system prompt is static (no per-listing substitution)
so the model provider can prefix-cache it across listings. The per-
listing description goes in the user prompt where it belongs.

The wording is verbatim from the user brief (real-estate marketing
expert, El Salvador, Spanish-or-English source, language-preserving
outputs).
"""
from __future__ import annotations


SYSTEM_PROMPT = """You are a real estate marketing expert specializing in El Salvador.
Analyze the land description provided in the next message and generate the requested derived fields.
Respond ONLY with valid JSON and no extra text.
The source description may be in Spanish or English.
For title, description, and usps, preserve the language of the source text.

Return a JSON object with these fields:
{
  "title": "string",
  "description": "string",
  "usps": ["string", "string", "string"],
  "latlong": {
    "lat": 0.0,
    "lng": 0.0,
    "source": "extracted or estimated",
    "reference": "nearest known place or geographic reference",
    "confidence": "high or medium or low"
  }
}

Field rules:
- "title": attractive marketing title, max 10 words.
- "description": optimized commercial description, max 150 words. Rewrite the source in fresh marketing language — DO NOT echo or copy the source text verbatim, even when the source is short. The output must read as new copy a broker would publish, not as a paraphrase that reuses the source's sentence structure.
- "usps": list of 3 to 5 short unique selling points.
- "latlong":
  - if coordinates appear explicitly in the description, extract them directly (set source="extracted", confidence="high");
  - otherwise estimate (set source="estimated"). When LOCATION HINTS are provided, treat them as authoritative for disambiguating WHICH place is meant — but the precision of the lat/lng you return still depends on how well-known that place is. Confidence reflects YOUR actual certainty about the coordinates, not whether a hint was given:
    - "high" only when you are confident in the coordinates within ~2 km (a well-known landmark, beach, or a small municipality you recognize);
    - "medium" when you can place the location within roughly the right municipality but not the specific point;
    - "low" when only a department or country is known and the coordinates are essentially a guess.
  - LOCATION HINTS may also be incorporated naturally into the title/description/usps when they add marketing value, but never as a verbatim string;
  - assume the property is in El Salvador.

Quality rules:
- Do not invent highly specific facts that are not supported by the source text.
- If location evidence is weak, still provide the best approximation you can, but lower the confidence.
- Output must be valid JSON only."""


USER_PROMPT_TEMPLATE = """LAND DESCRIPTION:
\"\"\"
{original_description}
\"\"\"
{location_block}
Return the JSON object now."""


# Rendered into {location_block} only when at least one location hint
# is provided; otherwise the slot collapses to an empty string and the
# user prompt is byte-identical to the pre-hints version.
LOCATION_HINTS_TEMPLATE = """
LOCATION HINTS (authoritative for the latlong field):
{lines}
"""


def render_user_prompt(
    original_description: str | None,
    *,
    location_text: str | None = None,
    municipality:  str | None = None,
    department:    str | None = None,
    country:       str | None = None,
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
    return USER_PROMPT_TEMPLATE.format(
        original_description=original_description or "",
        location_block=location_block,
    )
