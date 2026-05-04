"""
PRD WS2 — Day 3 — AI enrichment dry-run harness.

Implements PRD §8 prompts (title_canonical / short_description_canonical /
reasons_to_buy) for GPT-4o-mini. Two modes:

    python3 automation/ai_enrichment_dryrun.py
        Dry-run: builds the three prompts per listing, counts tokens roughly,
        projects total cost. NO API calls. Writes:
            samples/ai_dryrun_inputs.jsonl   — input fields + full prompts
            samples/ai_dryrun_summary.md     — cost projection + distribution

    python3 automation/ai_enrichment_dryrun.py --execute
        Calls GPT-4o-mini for real (requires OPENAI_API_KEY env var). Writes:
            samples/ai_dryrun_outputs.jsonl  — model responses
            samples/ai_dryrun_summary.md     — same as above + actual outputs

Why dry-run first: PRD §OQ-4 estimates $0.0003 per listing; PRD non-functional
caps spend at $50/month. Before any production wire-up we want a real cost
projection from real prompt sizes against real listings — back-of-envelope
math against PRD's example listings can be 2-3× off when descriptions are
1,000+ chars (bienesraices avg = 932 chars).
"""
from __future__ import annotations
import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from statistics import mean, median

REPO = Path(__file__).resolve().parents[1]
DEFAULT_INPUT      = REPO / "web" / "data" / "ranked.json"
DEFAULT_INPUTS_OUT = REPO / "samples" / "ai_dryrun_inputs.jsonl"
DEFAULT_OUTPUTS    = REPO / "samples" / "ai_dryrun_outputs.jsonl"
DEFAULT_SUMMARY    = REPO / "samples" / "ai_dryrun_summary.md"

DEFAULT_N = 100

# GPT-4o-mini pricing per PRD §FR-6.2 (cross-checked against §OQ-4)
PRICE_INPUT_PER_M_TOKENS  = 0.15   # USD per million input tokens
PRICE_OUTPUT_PER_M_TOKENS = 0.60   # USD per million output tokens

# Rough token-count estimate when no tokenizer is available. GPT-4-family
# tokenizers run ~3.6-4.2 chars/token on mixed English/Spanish; we use 3.8 as
# a slight safety margin (over-estimates cost rather than under-).
CHARS_PER_TOKEN_ESTIMATE = 3.8

# Expected output token budget per task (used for cost projection in dry-run).
# Real outputs typically come in lower; this is an upper bound.
OUTPUT_TOKEN_BUDGET = {
    "title_canonical":              30,    # 80-char max title
    "short_description_canonical":  150,   # 60-90 words ≈ 90-130 tokens
    "reasons_to_buy":               90,    # 3 bullets × ~25 tokens each
}


# ── PRD §8 system prompts (verbatim) ──────────────────────────────────────
SYSTEM_TITLE = (
    "You are a listing editor for Pulpo, a Latin American land investment "
    "marketplace. Generate a listing title in exactly this format: "
    "[Land Type] · [Size] · [Zone] · [Top Feature]. Use the English land type "
    "labels provided. Format size as: ≥10,000m² → ha; else → m². Use "
    "zone_name as Zone. Pick Top Feature from the priority list in the spec. "
    "Max 80 characters. No exclamation marks. No marketing language. "
    "Output the title only."
)

SYSTEM_DESCRIPTION = (
    "You are a listing editor for Pulpo, a Latin American land investment "
    "marketplace. Write a short description in English of 60-90 words using "
    "the PQAB structure: P (Property): size, type, location — 1-2 sentences. "
    "Q (Quality of Access): road access, views, proximity to infrastructure "
    "— 1-2 sentences. Only include confirmed attributes. A (Answers): "
    "address title status, zoning, utilities — 1-2 sentences. If data is "
    "absent, omit the point. B (Buyer Frame): one sentence on why this "
    "parcel is worth evaluating as an investment. "
    "Rules: English only. No superlatives. No invented facts. Write for a "
    "sophisticated land investor, not a residential homebuyer. "
    "Output the description only. No headers."
)

SYSTEM_USPS = (
    "You are a listing editor for Pulpo, a Latin American land investment "
    "marketplace. Generate exactly 3 USP bullet lines for this land listing. "
    "Each bullet: 10-15 words maximum. Starts with one emoji from the "
    "approved set. Pattern: [Concrete Feature] + [Investor Benefit or "
    "Implication]. Use only facts from the input fields. Do not invent "
    "figures. Apply the trigger table in priority order — use the first 3 "
    "applicable triggers. Output: 3 lines only. No numbering. No headers. "
    "Approved emoji set: 🏖 🏔 🛣 💧 ⚡ 🌳 ✈ 🌅 ⏱ 📍 ✂ 📈"
)

# Land-type labels per PRD §8.1
LAND_TYPE_LABELS = {
    "residential":  "Residential Lot",
    "agricultural": "Farm / Agricultural Land",
    "commercial":   "Commercial Land",
    "recreational": "Recreational Land",
    "mixed":        "Mixed-Use Land",
    "raw":          "Raw Land",
    "land":         "Raw Land",   # current default property_type
    "lot":          "Residential Lot",
    "finca":        "Farm / Agricultural Land",
}

# Fields scored for data_quality_score per PRD §FR-7.4
SCOREABLE_CORE_FIELDS = [
    "property_type", "area_m2", "price_usd", "zone", "department",
    "first_seen_at", "url", "broker_name", "broker_phone",
    "is_in_development", "is_beachfront", "photo_urls",
]


@dataclass
class ListingInput:
    """The compact dict passed to the model — nulls omitted per §FR-6.6."""
    listing_id:     str
    populated:      dict
    omitted_keys:   list[str]
    content_quality: str   # "high" | "medium" | "low" per §FR-6.6 logic


@dataclass
class TaskCost:
    task:          str
    in_tokens:     int
    out_tokens:    int
    cost_usd:      float


@dataclass
class ListingProjection:
    listing_id:     str
    content_quality: str
    tasks:          list[TaskCost] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return round(sum(t.cost_usd for t in self.tasks), 6)

    @property
    def total_in(self) -> int:
        return sum(t.in_tokens for t in self.tasks)


def _content_quality(li: dict) -> str:
    """PRD §FR-6.6 — null/short description = low quality flag."""
    desc = (li.get("description") or "").strip()
    if not desc or len(desc) < 20:
        return "low"
    if len(desc) < 100:
        return "medium"
    return "high"


def _build_input(li: dict) -> ListingInput:
    """Construct the populated_fields dict per PRD §8 (omit nulls)."""
    candidate = {
        "land_type":            li.get("property_type"),
        "land_type_label":      LAND_TYPE_LABELS.get(li.get("property_type") or "", "Raw Land"),
        "area_m2":              li.get("area_m2"),
        "price_usd":            li.get("price_usd"),
        "price_per_m2":         li.get("price_per_m2"),
        "zone_name":            li.get("zone"),
        "department":           li.get("department"),
        "title_raw":            li.get("title"),
        "description_raw":      li.get("description"),
        "is_beachfront":        li.get("is_beachfront"),
        "is_in_development":    li.get("is_in_development"),
        "development_name":     li.get("development_name"),
        "is_repriced":          li.get("is_repriced"),
        "first_seen_at":        li.get("first_seen_at"),
        "days_listed":          li.get("days_listed"),
        "broker_name":          li.get("broker_name"),
    }
    populated:    dict = {}
    omitted_keys: list[str] = []
    for k, v in candidate.items():
        is_null = v is None or v == "" or v is False
        if is_null and k not in {"land_type_label"}:
            omitted_keys.append(k)
        else:
            populated[k] = v

    return ListingInput(
        listing_id     = f"{li.get('source')}|{li.get('source_id')}",
        populated      = populated,
        omitted_keys   = omitted_keys,
        content_quality= _content_quality(li),
    )


def _user_prompt(task: str, inp: ListingInput) -> str:
    """Per-task user prompt body."""
    populated_json = json.dumps(inp.populated, ensure_ascii=False, default=str)
    if task == "title_canonical":
        return (
            "Generate the title for this listing. "
            f"Input fields (null fields omitted): {populated_json}"
        )
    if task == "short_description_canonical":
        return (
            f"Input fields (null fields omitted): {populated_json}"
        )
    if task == "reasons_to_buy":
        return (
            f"Input fields (null fields omitted): {populated_json}"
        )
    raise ValueError(f"unknown task: {task}")


def _system_prompt(task: str) -> str:
    return {
        "title_canonical":              SYSTEM_TITLE,
        "short_description_canonical":  SYSTEM_DESCRIPTION,
        "reasons_to_buy":                SYSTEM_USPS,
    }[task]


def _est_tokens(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN_ESTIMATE))


def _project_costs(inp: ListingInput) -> ListingProjection:
    proj = ListingProjection(listing_id=inp.listing_id, content_quality=inp.content_quality)
    for task in ("title_canonical", "short_description_canonical", "reasons_to_buy"):
        in_tokens  = _est_tokens(_system_prompt(task)) + _est_tokens(_user_prompt(task, inp))
        out_tokens = OUTPUT_TOKEN_BUDGET[task]
        cost       = (in_tokens  * PRICE_INPUT_PER_M_TOKENS  / 1_000_000
                      + out_tokens * PRICE_OUTPUT_PER_M_TOKENS / 1_000_000)
        proj.tasks.append(TaskCost(task, in_tokens, out_tokens, round(cost, 8)))
    return proj


def _execute_one(inp: ListingInput, client) -> dict:
    """Real GPT-4o-mini call; only runs in --execute mode."""
    out: dict = {"listing_id": inp.listing_id, "content_quality": inp.content_quality}
    for task in ("title_canonical", "short_description_canonical", "reasons_to_buy"):
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": _system_prompt(task)},
                {"role": "user",   "content": _user_prompt(task, inp)},
            ],
            temperature=0.3,
        )
        choice = resp.choices[0].message.content or ""
        usage  = resp.usage
        out[task] = {
            "output":     choice.strip(),
            "in_tokens":  usage.prompt_tokens     if usage else None,
            "out_tokens": usage.completion_tokens if usage else None,
        }
    return out


def _summary_md(projections: list[ListingProjection], n_total: int,
                executed: bool, exec_outputs: list[dict] | None) -> str:
    total_cost = sum(p.total_cost for p in projections)
    per_listing = [p.total_cost for p in projections]
    lines: list[str] = []
    lines.append("# AI Enrichment — Cost & Quality Dry-Run")
    lines.append("")
    lines.append(f"Mode: **{'EXECUTED (real API calls)' if executed else 'DRY-RUN (no API calls)'}**  ")
    lines.append(f"Listings sampled: **{len(projections)}** of {n_total} catalog total  ")
    lines.append("Model: GPT-4o-mini  ")
    lines.append(f"Pricing assumed: ${PRICE_INPUT_PER_M_TOKENS}/M input, "
                 f"${PRICE_OUTPUT_PER_M_TOKENS}/M output (PRD §FR-6.2)")
    lines.append("")

    lines.append("## Cost projection")
    lines.append("")
    lines.append(f"- **Total for sample**: ${total_cost:.4f}")
    if per_listing:
        lines.append(f"- **Per-listing mean**: ${mean(per_listing):.6f}")
        lines.append(f"- **Per-listing median**: ${median(per_listing):.6f}")
        lines.append(f"- **Per-listing max**: ${max(per_listing):.6f}")
        lines.append(f"- **Per-listing min**: ${min(per_listing):.6f}")
    full_catalog = round(mean(per_listing) * n_total, 4) if per_listing else 0
    lines.append(f"- **Projected to full catalog ({n_total} listings)**: ${full_catalog}")
    lines.append("")
    lines.append(f"PRD §OQ-4 estimate: $0.00024/listing × {n_total} = "
                 f"${0.00024 * n_total:.4f}")
    lines.append("")

    lines.append("## Per-task breakdown (mean tokens)")
    lines.append("")
    lines.append("| Task | Mean in | Mean out | Mean cost | Output budget |")
    lines.append("|---|---:|---:|---:|---:|")
    for task in ("title_canonical", "short_description_canonical", "reasons_to_buy"):
        ins  = [t.in_tokens  for p in projections for t in p.tasks if t.task == task]
        outs = [t.out_tokens for p in projections for t in p.tasks if t.task == task]
        cs   = [t.cost_usd   for p in projections for t in p.tasks if t.task == task]
        if ins:
            lines.append(f"| `{task}` | {round(mean(ins))} | {round(mean(outs))} | "
                         f"${mean(cs):.6f} | {OUTPUT_TOKEN_BUDGET[task]} |")

    lines.append("")
    lines.append("## Content-quality distribution (PRD §FR-6.6)")
    lines.append("")
    qcounts = {"high": 0, "medium": 0, "low": 0}
    for p in projections:
        qcounts[p.content_quality] = qcounts.get(p.content_quality, 0) + 1
    n = len(projections)
    for q in ("high", "medium", "low"):
        c = qcounts.get(q, 0)
        pct = 100 * c / n if n else 0
        lines.append(f"- **{q}**: {c} ({pct:.0f}%)")
    lines.append("")
    if qcounts.get("low", 0) > 0:
        lines.append(f"⚠️ {qcounts['low']} listings have `content_quality=low` "
                     "(empty or <20 char descriptions) and would be flagged in production.")
        lines.append("")

    if executed and exec_outputs:
        lines.append("## Sample outputs (first 5 listings)")
        lines.append("")
        for o in exec_outputs[:5]:
            lines.append(f"### `{o['listing_id']}` ({o['content_quality']})")
            for task in ("title_canonical", "short_description_canonical", "reasons_to_buy"):
                v = o.get(task) or {}
                lines.append(f"**{task}**:")
                lines.append("")
                lines.append("```")
                lines.append((v.get("output") or "").strip()[:1000])
                lines.append("```")
                lines.append("")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="PRD WS2 AI enrichment dry-run")
    p.add_argument("--input",  type=Path, default=DEFAULT_INPUT)
    p.add_argument("--n",      type=int,  default=DEFAULT_N,
                   help=f"how many listings to sample (default {DEFAULT_N})")
    p.add_argument("--execute", action="store_true",
                   help="actually call GPT-4o-mini (requires OPENAI_API_KEY)")
    p.add_argument("--seed",   type=int, default=20260504)
    p.add_argument("--out-inputs",  type=Path, default=DEFAULT_INPUTS_OUT)
    p.add_argument("--out-outputs", type=Path, default=DEFAULT_OUTPUTS)
    p.add_argument("--out-summary", type=Path, default=DEFAULT_SUMMARY)
    args = p.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found", file=sys.stderr)
        return 1
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not data:
        print("ERROR: ranked.json is empty", file=sys.stderr)
        return 1
    import random
    rng = random.Random(args.seed)
    sample = data if len(data) <= args.n else rng.sample(data, args.n)

    inputs       = [_build_input(li) for li in sample]
    projections  = [_project_costs(inp) for inp in inputs]
    n_total      = len(data)

    args.out_inputs.parent.mkdir(parents=True, exist_ok=True)
    with args.out_inputs.open("w", encoding="utf-8") as fh:
        for inp, proj in zip(inputs, projections):
            fh.write(json.dumps({
                "listing_id":      inp.listing_id,
                "content_quality": inp.content_quality,
                "populated":       inp.populated,
                "omitted_keys":    inp.omitted_keys,
                "system_prompts":  {t: _system_prompt(t)
                                    for t in ("title_canonical",
                                              "short_description_canonical",
                                              "reasons_to_buy")},
                "user_prompts":    {t: _user_prompt(t, inp)
                                    for t in ("title_canonical",
                                              "short_description_canonical",
                                              "reasons_to_buy")},
                "projection":      asdict(proj),
            }, ensure_ascii=False, default=str) + "\n")

    exec_outputs: list[dict] | None = None
    if args.execute:
        try:
            from openai import OpenAI    # type: ignore
        except ImportError:
            print("ERROR: openai package not installed. "
                  "Install with `pip install openai`.", file=sys.stderr)
            return 1
        if not os.environ.get("OPENAI_API_KEY"):
            print("ERROR: OPENAI_API_KEY env var not set.", file=sys.stderr)
            return 1
        client = OpenAI()
        exec_outputs = []
        with args.out_outputs.open("w", encoding="utf-8") as fh:
            for i, inp in enumerate(inputs, 1):
                try:
                    out = _execute_one(inp, client)
                except Exception as e:
                    out = {"listing_id": inp.listing_id, "error": repr(e)}
                exec_outputs.append(out)
                fh.write(json.dumps(out, ensure_ascii=False) + "\n")
                if i % 10 == 0:
                    print(f"[ai_dryrun] executed {i}/{len(inputs)}")

    args.out_summary.write_text(
        _summary_md(projections, n_total, args.execute, exec_outputs),
        encoding="utf-8",
    )
    total = sum(p.total_cost for p in projections)
    print(f"[ai_dryrun] mode={'execute' if args.execute else 'dry-run'} "
          f"sample={len(projections)} total_cost_projected=${total:.4f} "
          f"per_listing_mean=${total/max(1,len(projections)):.6f}")
    print(f"[ai_dryrun] wrote {args.out_inputs} and {args.out_summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
