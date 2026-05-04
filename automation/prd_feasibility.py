"""
PRD WS2 feasibility probe — measures whether the proposed schema-expansion
fields can actually be populated given today's scraper output.

Reads `web/data/ranked.json` and writes:
    web/data/prd_feasibility.md    — human-readable verdict report
    web/data/prd_feasibility.json  — machine-readable, for trending

Three views in the report:
  1. Already-populated fields the PRD treats as expansion (i.e. wins to inventory)
  2. NLP keyword feasibility — would the PRD §FR-2.5 dictionary find anything?
  3. Description-quality breakdown — gates every NLP- and AI-dependent field
  4. US-01 cohort sizing — the flagship "build-ready" filter

Usage:
    python3 automation/prd_feasibility.py
    python3 automation/prd_feasibility.py --input path/to/ranked.json

Exit code 0 on success, 1 on missing/empty input.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


# ── PRD §FR-2.5 starting-point keyword dictionaries ───────────────────────
# These mirror the PRD verbatim. Extending these lifts hit-rates; the YAML
# migration noted in the PRD is deferred to Phase 1 of execution.
KEYWORDS: dict[str, list[str]] = {
    "has_water":          [r"\bagua\b", r"\bpozo\b", r"\bwell\b", r"\basada\b",
                           r"\baya\b", r"agua potable", r"water hookup", r"water supply"],
    "has_power":          [r"\bluz\b", r"electricidad", r"\bice\b", r"\bcnfl\b",
                           r"corriente", r"electric", r"\bpower\b", r"energ[ií]a el[eé]ctrica"],
    "has_paved_access":   [r"acceso asfaltado", r"asfalto", r"\bpaved\b",
                           r"carretera pavimentada", r"road paved", r"ruta asfaltada"],
    "has_ocean_view":     [r"vista al mar", r"vista oce[aá]nica", r"ocean view",
                           r"sea view", r"vistas al oc[eé]ano"],
    "has_mountain_view":  [r"vista monta[nñ]a", r"mountain view", r"vista cordillera",
                           r"vista a los cerros"],
    "has_water_body":     [r"\br[ií]o\b", r"quebrada", r"\bcreek\b", r"riachuelo",
                           r"\blaguna\b", r"\blago\b", r"arroyo", r"\briver\b",
                           r"\bstream\b"],
    "is_flat":            [r"\bplano\b", r"terreno plano", r"\bflat\b",
                           r"lote plano", r"topograf[ií]a plana", r"\bnivel\b"],
    "is_beachfront_text": [r"frente al mar", r"frente a la playa", r"beachfront",
                           r"ocean front", r"primera l[ií]nea de playa"],
    "has_sewage":          [r"alcantarillado", r"tanque s[eé]ptico", r"septic tank",
                            r"aguas negras", r"\bsewage\b"],
    "is_repriced_text":   [r"precio reducido", r"rebajado", r"price reduced",
                           r"new price", r"nuevo precio", r"price drop"],
    "zoning_residential": [r"uso residencial", r"\bresidencial\b",
                           r"zona residencial", r"residential"],
    "zoning_tourist":     [r"zona tur[ií]stica", r"uso tur[ií]stico", r"\bturismo\b",
                           r"tourist zone"],
    "land_agricultural":  [r"agr[ií]cola", r"agricultural", r"\bfinca\b",
                           r"\bcafetal\b", r"\bcacao\b", r"\bfarm\b"],
    "land_commercial":    [r"\bcomercial\b", r"\bcommercial\b"],
    "land_recreational":  [r"recreacional", r"recreational", r"vacation"],
}

# PRD §4 — 3-month-post-ship targets
TARGETS: dict[str, int] = {
    "has_water":          40,
    "has_power":          40,
    "has_paved_access":   40,
    "is_beachfront_text": 15,
}

# PRD §FR-2.6 / §OQ-1 — minimum population for a field to surface as a UI filter
UI_GATE_PCT = 15

# Existing-fields inventory: what the pipeline already populates today
EXISTING_FIELDS: list[tuple[str, str]] = [
    # (label, evaluator-spec)
    ("url",                "url"),
    ("title",              "title"),
    ("description>20",     "description>20"),
    ("price_usd",          "price_usd"),
    ("area_m2",            "area_m2"),
    ("price_per_m2",       "price_per_m2"),
    ("zone",               "zone"),
    ("zone_specific",      "zone_specific"),
    ("department",         "department"),
    ("first_seen_at",      "first_seen_at"),
    ("scraped_at",         "scraped_at"),
    ("lat",                "lat"),
    ("lng",                "lng"),
    ("photo_urls>0",       "photo_urls>0"),
    ("photos_count>0",     "photos_count>0"),
    ("broker_name",        "broker_name"),
    ("broker_phone",       "broker_phone"),
    ("broker_email",       "broker_email"),
    ("is_beachfront",      "is_beachfront"),
    ("is_in_development",  "is_in_development"),
    ("is_repriced",        "is_repriced"),
    ("property_type!=land","property_type!=land"),
    ("days_listed",        "days_listed"),
]


def _evaluate(spec: str, li: dict) -> bool:
    """Truthy-eval one EXISTING_FIELDS spec against a listing."""
    if spec == "description>20":
        return bool((li.get("description") or "").strip()) and len(li.get("description") or "") > 20
    if spec == "zone_specific":
        return li.get("zone_confidence") == "specific"
    if spec == "photo_urls>0":
        return bool(li.get("photo_urls"))
    if spec == "photos_count>0":
        return bool((li.get("photos_count") or 0) > 0)
    if spec == "property_type!=land":
        pt = li.get("property_type")
        return bool(pt and pt != "land")
    # Default: truthy on the field
    v = li.get(spec)
    return v is not None and v != "" and v is not False


def _text_blob(li: dict) -> str:
    """Concatenated text for keyword search — title + description + location."""
    return " ".join([
        li.get("title") or "",
        li.get("description") or "",
        li.get("location_text") or "",
        li.get("raw_size_text") or "",
        li.get("raw_price_text") or "",
    ]).lower()


def _verdict(pct: float, target: int) -> str:
    """Map population % + PRD target to a green/amber/red verdict."""
    if target > 0 and pct >= target:
        return "GREEN"
    if pct >= UI_GATE_PCT:
        return "GREEN" if target == 0 else "AMBER"   # surface-eligible
    if pct >= 5:
        return "AMBER"   # computed-only, not surfaceable
    return "RED"


def _verdict_label(verdict: str, pct: float, target: int) -> str:
    """Human-readable verdict tag for the markdown table."""
    if verdict == "GREEN" and target > 0:
        return "🟢 meets PRD target"
    if verdict == "GREEN":
        return "🟢 surface-eligible"
    if verdict == "AMBER" and pct >= UI_GATE_PCT:
        return f"🟡 above {UI_GATE_PCT}% gate, below PRD target"
    if verdict == "AMBER":
        return "🟡 computed only, below UI gate"
    return "🔴 below 5% — needs scraper depth"


def existing_inventory(data: list[dict], n: int) -> list[dict]:
    """Population rates of fields already produced by the pipeline today."""
    rows = []
    for label, spec in EXISTING_FIELDS:
        hits = sum(1 for li in data if _evaluate(spec, li))
        rows.append({
            "field": label,
            "hits": hits,
            "pct": round(100 * hits / n, 1) if n else 0,
        })
    return sorted(rows, key=lambda r: -r["hits"])


def nlp_feasibility(data: list[dict], n: int) -> list[dict]:
    """For each PRD field, does the §FR-2.5 keyword dictionary find anything?"""
    rows = []
    for field, patterns in KEYWORDS.items():
        rx = re.compile("|".join(patterns), re.IGNORECASE)
        hits = sum(1 for li in data if rx.search(_text_blob(li)))
        pct = round(100 * hits / n, 1) if n else 0
        target = TARGETS.get(field, 0)
        v = _verdict(pct, target)
        rows.append({
            "field": field,
            "hits": hits,
            "pct": pct,
            "prd_target": target,
            "verdict": v,
            "verdict_label": _verdict_label(v, pct, target),
        })
    return rows


def description_quality(data: list[dict], n: int) -> dict:
    """Length buckets overall + per-source averages with short-listing %."""
    bucket_keys = ["empty", "<50 chars", "50-200", "200-500", ">=500"]
    buckets = Counter({k: 0 for k in bucket_keys})
    for li in data:
        d = (li.get("description") or "").strip()
        n_chars = len(d)
        if n_chars == 0:    buckets["empty"] += 1
        elif n_chars < 50:  buckets["<50 chars"] += 1
        elif n_chars < 200: buckets["50-200"] += 1
        elif n_chars < 500: buckets["200-500"] += 1
        else:               buckets[">=500"] += 1

    by_source: dict[str, list[int]] = {}
    for li in data:
        src = li.get("source") or "?"
        by_source.setdefault(src, []).append(len(li.get("description") or ""))

    per_source = []
    for src, lens in sorted(by_source.items()):
        if not lens:
            continue
        per_source.append({
            "source":         src,
            "n":              len(lens),
            "avg_chars":      round(sum(lens) / len(lens)),
            "pct_short_lt50": round(100 * sum(1 for x in lens if x < 50) / len(lens), 1),
        })

    return {
        "buckets": [
            {"bucket": k, "count": buckets[k],
             "pct": round(100 * buckets[k] / n, 1) if n else 0}
            for k in bucket_keys
        ],
        "per_source": per_source,
    }


def us01_cohort(data: list[dict], n: int) -> dict:
    """US-01 'water + power + paved road' build-ready filter sizing."""
    rxs = [re.compile("|".join(KEYWORDS[k]), re.IGNORECASE)
           for k in ("has_water", "has_power", "has_paved_access")]
    any3 = sum(1 for li in data if any(rx.search(_text_blob(li)) for rx in rxs))
    all3 = sum(1 for li in data if all(rx.search(_text_blob(li)) for rx in rxs))
    return {
        "any_one_signal":   {"hits": any3, "pct": round(100 * any3 / n, 1) if n else 0},
        "all_three_signals":{"hits": all3, "pct": round(100 * all3 / n, 1) if n else 0},
    }


def render_md(r: dict) -> str:
    """Render the report as human-readable markdown."""
    out: list[str] = []
    out.append("# PRD WS2 — Feasibility Probe")
    out.append("")
    out.append(f"_Generated: {r['generated_at']}_  ")
    out.append(f"_Catalog size: **{r['total_listings']} listings**_  ")
    out.append(f"_UI filter gate: ≥ {r['ui_gate_pct']}% population (per PRD §OQ-1)_")
    out.append("")
    out.append("This report measures whether the PRD's proposed fields can actually be "
               "populated given today's scraper output. Green = ready to surface or meets "
               "PRD target. Amber = computed but below gate or PRD target. Red = needs "
               "deeper scraper extraction.")
    out.append("")

    # 1. Existing inventory
    out.append("## 1. Already populated today (no PRD work needed)")
    out.append("")
    out.append("| Field | Count | % |")
    out.append("|---|---:|---:|")
    for row in r["existing"]:
        out.append(f"| `{row['field']}` | {row['hits']} | {row['pct']}% |")
    out.append("")

    # 2. NLP feasibility
    out.append("## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)")
    out.append("")
    out.append("| Field | Hits | % | PRD Target | Verdict |")
    out.append("|---|---:|---:|---:|---|")
    for row in r["nlp"]:
        target = f"≥ {row['prd_target']}%" if row["prd_target"] else f"≥ {r['ui_gate_pct']}% (gate)"
        out.append(f"| `{row['field']}` | {row['hits']} | {row['pct']}% | {target} | {row['verdict_label']} |")
    out.append("")

    # 3. Description quality
    out.append("## 3. Description quality (gates NLP + AI feasibility downstream)")
    out.append("")
    out.append("**Length distribution:**")
    out.append("")
    out.append("| Bucket | Count | % |")
    out.append("|---|---:|---:|")
    for b in r["description_quality"]["buckets"]:
        out.append(f"| {b['bucket']} | {b['count']} | {b['pct']}% |")
    out.append("")
    out.append("**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**")
    out.append("")
    out.append("| Source | n | Avg chars | % short (<50) |")
    out.append("|---|---:|---:|---:|")
    for s in r["description_quality"]["per_source"]:
        out.append(f"| `{s['source']}` | {s['n']} | {s['avg_chars']} | {s['pct_short_lt50']}% |")
    out.append("")

    # 4. US-01 cohort
    out.append("## 4. US-01 flagship filter — \"water + power + paved road\"")
    out.append("")
    out.append("This is the PRD's most-load-bearing user story. The cohort size determines "
               "whether the filter is useful (returns enough results) or empty.")
    out.append("")
    out.append("| Definition | Hits | % |")
    out.append("|---|---:|---:|")
    out.append(f"| ANY 1 of 3 utility signals (relaxed) | "
               f"{r['us01_cohort']['any_one_signal']['hits']} | "
               f"{r['us01_cohort']['any_one_signal']['pct']}% |")
    out.append(f"| ALL 3 of 3 utility signals (PRD spec) | "
               f"{r['us01_cohort']['all_three_signals']['hits']} | "
               f"{r['us01_cohort']['all_three_signals']['pct']}% |")
    out.append("")

    # Footer
    out.append("---")
    out.append("")
    out.append("Re-run with `python3 automation/prd_feasibility.py`. Wire into "
               "`automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script "
               "to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description="PRD WS2 field-feasibility probe")
    p.add_argument("--input", type=Path,
                   default=REPO / "web" / "data" / "ranked.json",
                   help="ranked.json to probe (default: web/data/ranked.json)")
    p.add_argument("--out-md", type=Path,
                   default=REPO / "web" / "data" / "prd_feasibility.md")
    p.add_argument("--out-json", type=Path,
                   default=REPO / "web" / "data" / "prd_feasibility.json")
    args = p.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found — run automation/run.py first",
              file=sys.stderr)
        return 1
    data = json.loads(args.input.read_text(encoding="utf-8"))
    n = len(data)
    if n == 0:
        print("ERROR: ranked.json is empty", file=sys.stderr)
        return 1

    report = {
        "generated_at":        datetime.now(timezone.utc).isoformat(),
        "total_listings":      n,
        "ui_gate_pct":         UI_GATE_PCT,
        "existing":            existing_inventory(data, n),
        "nlp":                 nlp_feasibility(data, n),
        "description_quality": description_quality(data, n),
        "us01_cohort":         us01_cohort(data, n),
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    args.out_md.write_text(render_md(report), encoding="utf-8")

    # Console summary line so CI / dashboards can grep
    nlp_green = sum(1 for r in report["nlp"] if r["verdict"] == "GREEN")
    nlp_amber = sum(1 for r in report["nlp"] if r["verdict"] == "AMBER")
    nlp_red   = sum(1 for r in report["nlp"] if r["verdict"] == "RED")
    print(f"[prd_feasibility] catalog={n} "
          f"nlp_fields green={nlp_green} amber={nlp_amber} red={nlp_red}  "
          f"us01_strict={report['us01_cohort']['all_three_signals']['pct']}% "
          f"us01_relaxed={report['us01_cohort']['any_one_signal']['pct']}%")
    print(f"[prd_feasibility] wrote {args.out_md} and {args.out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
