"""
PRD WS2 — Day 2 — Precision gold-set builder & evaluator.

Two modes:

    python3 automation/precision_goldset.py --sample
        Picks 50 listings (seeded random, stratified by source) from
        web/data/ranked.json and writes samples/precision_goldset.csv with the
        keyword-extractor's prediction pre-filled and empty truth_ columns
        ready for hand-labeling.

    python3 automation/precision_goldset.py --evaluate samples/precision_goldset.csv
        Reads back a labeled CSV and computes precision/recall per field
        against the PRD's ≥80% precision gate (PRD §OQ-3).

Why: PRD §OQ-3 requires "≥80% precision on a manually labelled holdout test of
50 listings per field per market" before a field is promoted to UI filter
status. This script generates that holdout deterministically and scores it.
"""
from __future__ import annotations
import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

# Reuse the keyword dictionary from the Day 1 feasibility probe.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from automation.prd_feasibility import KEYWORDS, _text_blob   # type: ignore  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULT_INPUT  = REPO / "web" / "data" / "ranked.json"
DEFAULT_OUTPUT = REPO / "samples" / "precision_goldset.csv"

SAMPLE_SIZE = 50
RNG_SEED    = 20260504   # date-based; bump only if regenerating intentionally

# Boolean fields from KEYWORDS that we ask the labeler to ground-truth.
# `is_repriced_text` and `has_sewage` excluded — too rare to generate signal
# at n=50.
BOOL_LABEL_FIELDS = [
    "has_water",
    "has_power",
    "has_paved_access",
    "is_flat",
    "has_ocean_view",
    "has_mountain_view",
    "has_water_body",
    "is_beachfront_text",
]

# Enum field — labeler picks one value (or "unknown" for nothing visible).
ENUM_LAND_TYPE_VALUES = (
    "residential", "agricultural", "commercial",
    "recreational", "mixed", "raw", "unknown",
)


@dataclass
class FieldMetrics:
    field:        str
    n_labeled:    int
    n_pred_true:  int
    n_truth_true: int
    tp:           int
    fp:           int
    fn:           int

    @property
    def precision(self) -> float | None:
        denom = self.tp + self.fp
        return self.tp / denom if denom else None

    @property
    def recall(self) -> float | None:
        denom = self.tp + self.fn
        return self.tp / denom if denom else None


def _predict_bool(li: dict, field: str) -> bool:
    """Run the field's KEYWORDS regex against the listing's text blob."""
    rx = re.compile("|".join(KEYWORDS[field]), re.IGNORECASE)
    return bool(rx.search(_text_blob(li)))


def _predict_land_type(li: dict) -> str:
    """First matching land_type from KEYWORDS dictionary, else 'raw'."""
    blob = _text_blob(li)
    for enum_val in ("agricultural", "commercial", "recreational"):
        rx = re.compile("|".join(KEYWORDS[f"land_{enum_val}"]), re.IGNORECASE)
        if rx.search(blob):
            return enum_val
    if re.compile("|".join(KEYWORDS["zoning_residential"]), re.IGNORECASE).search(blob):
        return "residential"
    return "raw"


def _stratified_sample(data: list[dict], k: int, seed: int) -> list[dict]:
    """Approximately uniform sample with at least 1 listing per source.

    First reserves one listing per source (round-robin), then fills the
    remainder uniformly at random from the full pool. This avoids the
    case where rare sources (n=15 century21) contribute zero rows.
    """
    by_source: dict[str, list[dict]] = defaultdict(list)
    for li in data:
        by_source[li.get("source") or "unknown"].append(li)

    rng = random.Random(seed)
    reserved: list[dict] = []
    for src in sorted(by_source):
        items = by_source[src]
        if items:
            reserved.append(rng.choice(items))

    remainder_pool = [li for li in data if li not in reserved]
    rng.shuffle(remainder_pool)
    fill = remainder_pool[: max(0, k - len(reserved))]
    return (reserved + fill)[:k]


def cmd_sample(args: argparse.Namespace) -> int:
    if not args.input.exists():
        print(f"ERROR: {args.input} not found — run automation/run.py first", file=sys.stderr)
        return 1

    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not data:
        print("ERROR: ranked.json is empty", file=sys.stderr)
        return 1

    sample = _stratified_sample(data, args.size, args.seed)
    print(f"[goldset] sampled {len(sample)} listings (seed={args.seed}) from {len(data)}")

    cols = ["row", "source", "source_id", "listing_id", "url", "title",
            "description_excerpt"]
    for f in BOOL_LABEL_FIELDS:
        cols += [f"pred_{f}", f"truth_{f}"]
    cols += ["pred_land_type", "truth_land_type", "labeler_notes"]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for i, li in enumerate(sample, 1):
            row = {
                "row":                 i,
                "source":              li.get("source") or "",
                "source_id":           li.get("source_id") or "",
                "listing_id":          f"{li.get('source')}|{li.get('source_id')}",
                "url":                 li.get("url") or "",
                "title":               (li.get("title") or "")[:120],
                "description_excerpt": (li.get("description") or "")[:400].replace("\n", " "),
                "labeler_notes":       "",
                "truth_land_type":     "",
                "pred_land_type":      _predict_land_type(li),
            }
            for f in BOOL_LABEL_FIELDS:
                row[f"pred_{f}"]  = "1" if _predict_bool(li, f) else "0"
                row[f"truth_{f}"] = ""    # blank for hand-labeling
            w.writerow(row)

    legend = args.output.with_suffix(".LEGEND.md")
    legend.write_text(_legend_md(), encoding="utf-8")
    print(f"[goldset] wrote {args.output} and {legend}")
    print(f"[goldset] hand-label the truth_* columns, then re-run with "
          f"--evaluate {args.output.relative_to(REPO)}")
    return 0


def _legend_md() -> str:
    return f"""# Precision Gold-set — Labeling Legend

This CSV holds **{SAMPLE_SIZE} listings** randomly sampled (seeded, stratified
by source) for hand-labeling. The goal: measure whether the keyword-based NLP
extractor in `automation/prd_feasibility.py` hits the **≥ 80% precision gate**
required by PRD §OQ-3 before a field can surface as a UI filter.

## Columns

- `row`, `source`, `source_id`, `listing_id`, `url` — identity & traceability.
- `title`, `description_excerpt` — what to read when labeling.
- `pred_<field>` — the extractor's current prediction. **Do not edit.**
- `truth_<field>` — your hand-label. Edit this.
- `pred_land_type` / `truth_land_type` — same idea for the enum.

## How to label

For each row, read `title` + `description_excerpt`. Then for every
`truth_<field>` column, fill in:

- **`1`** — the listing clearly states this attribute is present (or implies it
  unambiguously).
- **`0`** — the listing clearly states this attribute is absent OR there's no
  mention at all (default-False is the PRD spec — see §FR-2.4).
- **leave blank** — only if the listing text is unreadable / corrupted /
  non-Spanish-non-English / contradicts itself. Blank rows are excluded from
  scoring rather than counting against either side.

For `truth_land_type`, pick one of: `{', '.join(ENUM_LAND_TYPE_VALUES)}`.
Use `unknown` if the listing text doesn't say.

## Re-run after labeling

```
python3 automation/precision_goldset.py --evaluate {DEFAULT_OUTPUT.relative_to(REPO)}
```

Output: precision and recall per field, with a green/amber/red verdict against
PRD §OQ-3's ≥ 80% precision gate.
"""


def cmd_evaluate(args: argparse.Namespace) -> int:
    path: Path = args.labeled
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 1

    with path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        print("ERROR: labeled CSV is empty", file=sys.stderr)
        return 1

    metrics: list[FieldMetrics] = []

    # Boolean fields
    for field in BOOL_LABEL_FIELDS:
        n_labeled = n_pt = n_tt = tp = fp = fn = 0
        pred_col, truth_col = f"pred_{field}", f"truth_{field}"
        for r in rows:
            t_raw = (r.get(truth_col) or "").strip()
            if t_raw == "":
                continue   # un-labeled, exclude from scoring
            n_labeled += 1
            pred  = (r.get(pred_col) or "").strip() == "1"
            truth = t_raw == "1"
            if pred:
                n_pt += 1
            if truth:
                n_tt += 1
            if pred and truth:
                tp += 1
            elif pred and not truth:
                fp += 1
            elif not pred and truth:
                fn += 1
        metrics.append(FieldMetrics(field, n_labeled, n_pt, n_tt, tp, fp, fn))

    # Enum field (land_type) — score as exact-match precision per predicted class
    enum_per_class: dict[str, FieldMetrics] = {}
    for cls in [v for v in ENUM_LAND_TYPE_VALUES if v != "unknown"]:
        n_labeled = n_pt = n_tt = tp = fp = fn = 0
        for r in rows:
            t_raw = (r.get("truth_land_type") or "").strip()
            if t_raw == "":
                continue
            n_labeled += 1
            pred  = (r.get("pred_land_type") or "").strip() == cls
            truth = t_raw == cls
            if pred:
                n_pt += 1
            if truth:
                n_tt += 1
            if pred and truth:
                tp += 1
            elif pred and not truth:
                fp += 1
            elif not pred and truth:
                fn += 1
        enum_per_class[cls] = FieldMetrics(f"land_type={cls}", n_labeled,
                                           n_pt, n_tt, tp, fp, fn)

    # Render
    lines: list[str] = []
    lines.append("# Precision Gold-set — Evaluation")
    lines.append("")
    lines.append(f"_Source: `{path.relative_to(REPO)}`_")
    lines.append(f"_Labeled rows: {sum(1 for r in rows if any((r.get('truth_'+f) or '').strip() for f in BOOL_LABEL_FIELDS))} of {len(rows)}_")
    lines.append("")
    lines.append("PRD §OQ-3 gate: **≥ 80% precision** before a field promotes to UI filter.")
    lines.append("")
    lines.append("## Boolean fields")
    lines.append("")
    lines.append("| Field | Labeled | Pred=1 | Truth=1 | Precision | Recall | Verdict |")
    lines.append("|---|---:|---:|---:|---:|---:|---|")
    for m in metrics:
        p, r = m.precision, m.recall
        ps   = f"{p*100:.0f}%" if p is not None else "—"
        rs   = f"{r*100:.0f}%" if r is not None else "—"
        if m.n_labeled == 0:
            verdict = "⏳ no labels yet"
        elif p is None:
            verdict = "⚪ no positive predictions"
        elif p >= 0.80:
            verdict = "🟢 passes gate"
        elif p >= 0.60:
            verdict = "🟡 close — tune keywords"
        else:
            verdict = "🔴 below gate"
        lines.append(f"| `{m.field}` | {m.n_labeled} | {m.n_pred_true} | "
                     f"{m.n_truth_true} | {ps} | {rs} | {verdict} |")

    lines.append("")
    lines.append("## land_type (enum, exact-match per class)")
    lines.append("")
    lines.append("| Class | Pred=class | Truth=class | Precision | Recall |")
    lines.append("|---|---:|---:|---:|---:|")
    for cls, m in enum_per_class.items():
        p, r = m.precision, m.recall
        ps = f"{p*100:.0f}%" if p is not None else "—"
        rs = f"{r*100:.0f}%" if r is not None else "—"
        lines.append(f"| `{cls}` | {m.n_pred_true} | {m.n_truth_true} | {ps} | {rs} |")
    lines.append("")

    out_md = path.with_name(path.stem + "_evaluation.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[goldset] wrote {out_md}")

    # Console one-liner per field for CI grep-ability
    for m in metrics:
        ps = f"{m.precision*100:.0f}%" if m.precision is not None else "n/a"
        print(f"[goldset] {m.field:<22} prec={ps:>6}  labeled={m.n_labeled:>3}  "
              f"tp={m.tp} fp={m.fp} fn={m.fn}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="PRD WS2 precision gold-set builder/evaluator")
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("sample", help="generate a fresh unlabeled gold-set CSV")
    s.add_argument("--input",  type=Path, default=DEFAULT_INPUT)
    s.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    s.add_argument("--size",   type=int,  default=SAMPLE_SIZE)
    s.add_argument("--seed",   type=int,  default=RNG_SEED)
    s.set_defaults(func=cmd_sample)

    e = sub.add_parser("evaluate", help="score a hand-labeled gold-set CSV")
    e.add_argument("labeled", type=Path,
                   help="path to a labeled CSV (truth_* columns filled)")
    e.set_defaults(func=cmd_evaluate)

    # Default to "sample" if no subcommand given
    args = p.parse_args()
    if not getattr(args, "cmd", None):
        s_args = s.parse_args([])
        return cmd_sample(s_args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
