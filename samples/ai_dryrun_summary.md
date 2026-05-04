# AI Enrichment — Cost & Quality Dry-Run

Mode: **DRY-RUN (no API calls)**  
Listings sampled: **100** of 811 catalog total  
Model: GPT-4o-mini  
Pricing assumed: $0.15/M input, $0.6/M output (PRD §FR-6.2)

## Cost projection

- **Total for sample**: $0.0347
- **Per-listing mean**: $0.000347
- **Per-listing median**: $0.000338
- **Per-listing max**: $0.000467
- **Per-listing min**: $0.000257
- **Projected to full catalog (811 listings)**: $0.2817

PRD §OQ-4 estimate: $0.00024/listing × 811 = $0.1946

## Per-task breakdown (mean tokens)

| Task | Mean in | Mean out | Mean cost | Output budget |
|---|---:|---:|---:|---:|
| `title_canonical` | 387 | 30 | $0.000076 | 30 |
| `short_description_canonical` | 448 | 150 | $0.000157 | 150 |
| `reasons_to_buy` | 401 | 90 | $0.000114 | 90 |

## Content-quality distribution (PRD §FR-6.6)

- **high**: 69 (69%)
- **medium**: 0 (0%)
- **low**: 31 (31%)

⚠️ 31 listings have `content_quality=low` (empty or <20 char descriptions) and would be flagged in production.
