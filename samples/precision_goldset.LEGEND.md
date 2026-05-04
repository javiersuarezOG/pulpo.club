# Precision Gold-set — Labeling Legend

This CSV holds **50 listings** randomly sampled (seeded, stratified
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

For `truth_land_type`, pick one of: `residential, agricultural, commercial, recreational, mixed, raw, unknown`.
Use `unknown` if the listing text doesn't say.

## Re-run after labeling

```
python3 automation/precision_goldset.py --evaluate samples/precision_goldset.csv
```

Output: precision and recall per field, with a green/amber/red verdict against
PRD §OQ-3's ≥ 80% precision gate.
