"""
A/B test: current vs proposed LLM prompt for the latlong field.

Targets the listings flagged by scripts/audit_beach_distance_consistency.py
(description claims walking-distance / beachfront, but dist_beach_km > 2km
because the LLM placed the listing at an inland zone centroid).

For each offender, calls DeepSeek twice — once with the current SYSTEM_PROMPT,
once with a candidate prompt that adds a "proximity cues" section telling
the model to anchor lat/lng at the NAMED beach when the source mentions
walking distance / frente al mar / beachfront.

Prints a side-by-side diff including the recomputed dist_beach_km for both.

Usage:
    DEEPSEEK_API_TOKEN=sk-... python3 scripts/test_prompt_proximity_cues.py
    # or, if .env contains the token:
    python3 scripts/test_prompt_proximity_cues.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Load .env if env var isn't set yet — keeps the script standalone.
if not os.environ.get("DEEPSEEK_API_TOKEN"):
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from automation.distance_fields import compute_dist_beach_km  # type: ignore  # noqa: E402
from automation.llm_enrichment_prompts import (  # type: ignore  # noqa: E402
    SYSTEM_PROMPT as PROPOSED_SYSTEM_PROMPT,
    render_user_prompt,
)


# ── Baseline prompt (before this PR's prompt edit) ──────────────────────
# Pasted here verbatim so we can A/B against it without reverting the
# production module. This is what shipped before the proximity-cues +
# named-beach-table change. The PROPOSED_SYSTEM_PROMPT is whatever
# automation/llm_enrichment_prompts.py exports today.
CURRENT_SYSTEM_PROMPT = """You are a real estate marketing expert specializing in El Salvador.
Analyze the land description provided in the next message and generate the requested derived fields.
Respond ONLY with valid JSON and no extra text.
The source description may be in Spanish, English, or mixed.

You MUST produce title, description, and usps in BOTH English and Spanish.
Detect the dominant language of the source (en, es, or mixed) and report it as url_language.
Translate professionally — preserve marketing voice, do not literal-translate idioms.

Return a JSON object with these fields:
{
  "title": { "en": "string", "es": "string" },
  "description": { "en": "string", "es": "string" },
  "usps": [ { "en": "string", "es": "string" }, ... ],
  "url_language": "en or es or mixed",
  "latlong": {
    "lat": 0.0,
    "lng": 0.0,
    "source": "extracted or estimated",
    "reference": "nearest known place or geographic reference",
    "confidence": "high or medium or low"
  }
}

Field rules:
- "title": attractive marketing title in BOTH languages, each max 10 words.
- "description": optimized commercial description in BOTH languages, each max 150 words. Rewrite the source in fresh marketing language — DO NOT echo or copy the source text verbatim, even when the source is short. The output must read as new copy a broker would publish, not as a paraphrase that reuses the source's sentence structure.
- "usps": list of 3 to 5 short unique selling points; each USP is a {en, es} pair.
- "url_language":
  - "en" if source text is mostly English;
  - "es" if source text is mostly Spanish;
  - "mixed" only when both languages are clearly intermixed (one-line headers in EN with body in ES, etc.).
- "latlong":
  - if coordinates appear explicitly in the description, extract them directly (set source="extracted", confidence="high");
  - otherwise estimate (set source="estimated"). When LOCATION HINTS are provided, treat them as authoritative for disambiguating WHICH place is meant — but the precision of the lat/lng you return still depends on how well-known that place is. Confidence reflects YOUR actual certainty about the coordinates, not whether a hint was given:
    - "high" only when you are confident in the coordinates within ~2 km (a well-known landmark, beach, or a small municipality you recognize);
    - "medium" when you can place the location within roughly the right municipality but not the specific point;
    - "low" when only a department or country is known and the coordinates are essentially a guess.
  - LOCATION HINTS may also be incorporated naturally into the title/description/usps (in either language) when they add marketing value, but never as a verbatim string;
  - assume the property is in El Salvador.

Quality rules:
- Do not invent highly specific facts that are not supported by the source text.
- The translation MUST mean the same thing in both languages — do not add or remove information from one side.
- Numbers, prices, distances, surface measurements stay numerically identical across languages.
- For Salvadoran traditional units (manzanas, varas), keep the unit term in Spanish; in the EN translation, append the m² equivalent in parentheses if present in the source.
- If location evidence is weak, still provide the best approximation you can, but lower the confidence.
- Output must be valid JSON only."""


# ── Test fixtures: top offenders from the audit ──────────────────────────
# These source_ids were picked because they (a) have a clear walking/
# beachfront claim in the source text and (b) exhibit a wildly wrong
# dist_beach_km in production today. Mix of zones (west / east / central
# coast) and sources to avoid over-fitting to one scraper.
OFFENDER_IDS: list[tuple[str, str]] = [
    # (source, source_id) — picked from audit_beach_distance_consistency output
    ("goodlife", "2-bed-condominium-at-zonset-el-zonte-445694"),       # the Zonset case the user flagged
    ("goodlife", "newly-built-condo-with-partial-ocean-view-at-zonset-el-zonte-340000"),
    ("bienesraices", "2317"),  # Barra de Santiago, far west
    ("bienesraices", "1626"),  # Playa Torola, Conchagua, far east
    ("bienesraices", "1062"),  # Playa Maculís, Conchagua
    ("bienesraices", "1334"),  # Playa Cuevitas, La Unión
    ("bienesraices", "1272"),  # Playa La Perla
    ("century21", "935694"),   # Oceanfront, La Libertad
]


def _load_listings() -> dict[tuple[str, str], dict]:
    data = json.loads((REPO / "web" / "data" / "ranked.json").read_text())
    return {(li["source"], li["source_id"]): li for li in data}


def _call_deepseek(client, system_prompt: str, user_prompt: str) -> dict:
    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=2000,
    )
    raw = (resp.choices[0].message.content or "").strip()
    return json.loads(raw)


def main() -> None:
    if not os.environ.get("DEEPSEEK_API_TOKEN"):
        print("ERROR: DEEPSEEK_API_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        print("ERROR: pip install openai", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(
        base_url="https://api.deepseek.com",
        api_key=os.environ["DEEPSEEK_API_TOKEN"],
    )
    listings = _load_listings()

    rows: list[dict] = []
    for src, sid in OFFENDER_IDS:
        li = listings.get((src, sid))
        if not li:
            print(f"!! not found: {src}/{sid}")
            continue

        user_prompt = render_user_prompt(
            li.get("description"),
            location_text=li.get("location_text"),
            municipality=li.get("municipality"),
            department=li.get("department"),
            country=li.get("country"),
        )

        try:
            old = _call_deepseek(client, CURRENT_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            print(f"old call failed for {src}/{sid}: {e!r}")
            old = {}
        try:
            new = _call_deepseek(client, PROPOSED_SYSTEM_PROMPT, user_prompt)
        except Exception as e:
            print(f"new call failed for {src}/{sid}: {e!r}")
            new = {}

        old_ll = (old or {}).get("latlong") or {}
        new_ll = (new or {}).get("latlong") or {}

        old_dist = compute_dist_beach_km({"lat": old_ll.get("lat"), "lng": old_ll.get("lng")})
        new_dist = compute_dist_beach_km({"lat": new_ll.get("lat"), "lng": new_ll.get("lng")})

        rows.append({
            "src":    f"{src}/{sid}",
            "title":  (li.get("title") or "")[:80],
            "production": {
                "lat":    li.get("lat"),
                "lng":    li.get("lng"),
                "source": li.get("geocoding_source"),
                "conf":   li.get("geocoding_confidence"),
                "dist":   li.get("dist_beach_km"),
            },
            "old_prompt": {
                **{k: old_ll.get(k) for k in ("lat", "lng", "source", "confidence", "reference")},
                "dist_beach_km": old_dist,
            },
            "new_prompt": {
                **{k: new_ll.get(k) for k in ("lat", "lng", "source", "confidence", "reference")},
                "dist_beach_km": new_dist,
            },
        })

    # Pretty print
    print()
    print("=" * 100)
    for r in rows:
        prod = r["production"]
        old = r["old_prompt"]
        new = r["new_prompt"]
        print(f"\n[{r['src']}]")
        print(f"  title:  {r['title']}")
        print(f"  PROD:   lat={prod['lat']:.4f} lng={prod['lng']:.4f} "
              f"src={prod['source']} conf={prod['conf']} dist={prod['dist']}km")
        if "lat" in old and old.get("lat") is not None:
            print(f"  OLD:    lat={old['lat']:.4f} lng={old['lng']:.4f} "
                  f"src={old['source']} conf={old['confidence']} "
                  f"dist={old['dist_beach_km']}km  ref={old.get('reference')}")
        else:
            print("  OLD:    (failed)")
        if "lat" in new and new.get("lat") is not None:
            print(f"  NEW:    lat={new['lat']:.4f} lng={new['lng']:.4f} "
                  f"src={new['source']} conf={new['confidence']} "
                  f"dist={new['dist_beach_km']}km  ref={new.get('reference')}")
        else:
            print("  NEW:    (failed)")
        # Improvement signal
        if (
            isinstance(old.get("dist_beach_km"), (int, float))
            and isinstance(new.get("dist_beach_km"), (int, float))
        ):
            delta = old["dist_beach_km"] - new["dist_beach_km"]
            print(f"  Δ:      {delta:+.2f}km  ({'better' if delta > 0 else 'worse'} on new prompt)")
    print()
    print("=" * 100)

    # Also persist the raw rows for follow-up review.
    out = REPO / "scripts" / "_prompt_proximity_cues_results.json"
    out.write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"raw results → {out}")


if __name__ == "__main__":
    main()
