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
- "description": optimized commercial description, max 150 words.
- "usps": list of 3 to 5 short unique selling points.
- "latlong":
  - if coordinates appear explicitly in the text, extract them directly;
  - otherwise estimate coordinates from municipality, department, roads, distances, landmarks, or nearby places mentioned in the text;
  - assume the property is in El Salvador.

Quality rules:
- Do not invent highly specific facts that are not supported by the source text.
- If location evidence is weak, still provide the best approximation you can, but lower the confidence.
- Output must be valid JSON only."""


USER_PROMPT_TEMPLATE = """LAND DESCRIPTION:
\"\"\"
{original_description}
\"\"\"

Return the JSON object now."""


def render_user_prompt(original_description: str | None) -> str:
    """Render the per-listing user prompt.

    Empty/None descriptions are passed through as an empty triple-quoted
    block. The model still gets the JSON shape from the system prompt and
    can return a low-confidence latlong response — the validator
    downstream will reject obviously broken outputs (e.g. usps not a
    list, lat not a number).
    """
    return USER_PROMPT_TEMPLATE.format(original_description=original_description or "")
