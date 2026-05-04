# PRD WS2 — Feasibility Decision Memo

_Day 5 of the 5-day feasibility study gating commitment to the WS2 schema-expansion PRD._
_Author: Sebastian (drafted by Claude Code, hand-edit before circulating)._
_Date: 2026-05-04. Catalog state: 811 listings, 7 active scrapers._

## TL;DR

**The PRD's overall shape is sound. Three of its population targets and one of its flagship UX claims are off — none catastrophic, but worth re-baselining before we commit a quarter to the wrong numbers.** The 12-week sequencing in §14 holds with **two adjustments**: insert a Phase 0 to fix description extraction on `century21` and `remax` (40% of catalog), and ship US-01 as "ANY 1 utility confirmed" rather than "ALL 3" until scraper coverage matures.

**Recommendation: green-light the PRD with the four amendments listed in §3 of this memo.**

## 1. What the data actually says

| Probe | Method | Result | PRD assumption | Verdict |
|---|---|---|---|---|
| Field population | Day-1 NLP keyword sweep over 811 listings | `has_water` 21.7%, `has_power` 20.0%, `has_paved_access` 1.7%, `is_beachfront` (text) 7.3%, `is_flat` 19.4%, `zoning_residential` 23.1% | targets ≥40% / ≥40% / ≥40% / ≥15% | 🟡 utility targets 2-3× optimistic; `has_paved_access` requires deeper extraction |
| US-01 cohort | Day-1 keyword sweep | "ALL 3 utility signals" → **4 listings (0.5%)**; "ANY 1 of 3" → 219 (27.0%) | flagship investor filter | 🔴 strict version returns ~zero; relaxed version is usable |
| NLP precision | Day-2 holdout — pending hand-labels | TBD (50-listing gold-set written, awaiting label pass) | ≥80% precision per §OQ-3 | ⏳ blocked on labeling |
| AI cost per listing | Day-3 dry-run, 100-listing GPT-4o-mini projection | $0.000347 mean (45% above PRD §OQ-4 estimate) | $0.00024 | 🟡 absolute cost still trivial vs $50/mo cap; PRD math optimistic |
| AI input quality | Day-3 content-quality classifier | **31% of listings classed `low`** (empty/<20 char description) | not stated | 🔴 nearly 1 in 3 listings would ship a flagged AI output until scrapers fixed |
| Geocoding free-tier | Day-4 live HTML probe of 50 listings | 44% extractable from HTML alone, 100% via `gmaps_q_param` for `remax` (38% of catalog), 0% for `bienesraices` (55%) | step-1/2 catch most listings | 🟢 Mapbox spend stays inside 100k/mo free tier even at 56% miss rate |
| Description availability | Day-1 / Day-3 cross-cut | `bienesraices` avg 932 chars, `oceanside` 1,422 — but `century21` **100% empty**, `remax` **74% short (<50 chars)** | description_raw populated and meaningful | 🔴 40% of catalog has no usable text input |

## 2. The three things the PRD got wrong

1. **Utility-population targets (§4) are 2-3× current ceiling.** Lifting `has_water`/`has_power` from 22% → 40% requires `century21` and `remax` to start emitting full descriptions. Until then, those targets are aspirational-only.

2. **US-01 (§5) doesn't survive contact with the data.** "Filter for water + power + paved road" returns 4 listings out of 811 today, and even with perfect text extraction would land in the low double digits. The user story is right; the filter spec needs to be "ANY 1 confirmed utility" or the build-ready cohort needs a different rule altogether.

3. **AI input assumes universal description.** §FR-6.6 has a `content_quality=low` flag, but the PRD doesn't account for **31% of listings being in that bucket**. Phase 1 ships AI to users; if a third of catalog ships flagged low-quality outputs, that's a UX problem we'd inherit at launch, not after.

## 3. Recommended PRD amendments

### Amendment 1 — Insert Phase 0 (1 week, before §14 Phase 1)

**Goal**: Fix description extraction on `century21` and `remax` so the shared NLP and AI layers in Phase 1 don't ship to broken inputs.

| Scraper | Today | Phase 0 target |
|---|---|---|
| `century21` | 100% empty descriptions | ≥80% non-empty after fix |
| `remax` | 74% short (<50 chars) | ≤20% short after fix |

This is mechanical scraper work — both sources' detail pages do contain descriptions; the current scrapers are reading from the index/list page. Likely 2-3 person-days each.

### Amendment 2 — Re-baseline §4 success metrics

| Field | Original target | Recommended target | Justification |
|---|---|---|---|
| `has_water` population | ≥ 40% | **≥ 25%** | 21.7% from current text; +Phase 0 should clear 25%; 40% requires real keyword tuning + new sources |
| `has_power` population | ≥ 40% | **≥ 25%** | Same reasoning as has_water |
| `has_paved_access` population | ≥ 40% | **≥ 15%** | 1.7% currently; Phase 0 + dedicated keyword tuning needed; 15% is the UI gate, not an aspirational target |
| `is_beachfront` population | ≥ 15% | **≥ 12%** | 7.3% from text + 0.5% existing flag; geometric upgrade in Phase 2 (FR-5.6) lifts to ~12% |

Targets that hold as written: `is_flat` (already 19.4%), `zoning_residential` (already 23.1%), `data_quality_score`, AI content coverage, `is_repriced` (gated by FR-3 not text), `source_type`.

### Amendment 3 — Soften US-01

Change the user story flagship filter from "**all** of (water + power + paved-road)" to "**at least 1 confirmed utility**". The relaxed cohort is 27% of catalog (219 listings) — meaningful surface area for the build-ready filter. The strict version can ship as a secondary "Fully Connected" toggle once Phase 0 lifts utility population.

This also matches the PRD's own §FR-7.2 `investment_signal` rules, which already give `readiness_score = 3` listings a "Build-Ready" label rather than relying on a filter intersection.

### Amendment 4 — Update §FR-6.2 cost projection

PRD §OQ-4 estimates $0.00024/listing × 10,000 listings = $2.40 to enrich. Real measurement against 100 of our actual listings: **$0.000347/listing × 811 = $0.28** per full re-enrichment. At weekly cadence with regeneration triggered only by description_raw md5 diff (per §FR-6.3), monthly spend stays well under $5/mo — **inside the $50 cap, but PRD's per-listing math should be rounded up to $0.0004 for budgeting**.

## 4. Phase ordering — recommended

```
Phase 0 (week 0)   — c21 + remax description fix         ← new, load-bearing
Phase 1 (1-4)      — schema v1 + price history + NLP +
                     AI enrichment + data_quality_score   (PRD §14 as written)
Phase 2 (5-8)      — Playwright photos + geocoding +
                     distance fields                      (PRD §14 as written)
Phase 3 (9-12)     — zone medians + signals + dynamic
                     filter gating                         (PRD §14 as written)
```

## 5. Open items before kicking off Phase 0

1. **Hand-label the precision gold-set** at `samples/precision_goldset.csv` — ~1 hour of work, yields the precision/recall numbers needed to confirm or kill the NLP layer per §OQ-3 (≥80% gate). Currently the sole blocker on the Day-2 deliverable.
2. **Decide on PRD §4 target re-baseline** (Amendment 2) — this needs PM sign-off before §FR-9 Data Quality Monitor starts alerting on missed targets.
3. **Provision OPENAI_API_KEY with a $50/mo spend limit** (PRD §10 non-functional) — same key powers the Day-3 dry-run's `--execute` mode for live quality validation before Phase 1 ships.
4. **Decide on US-01 filter rewording** (Amendment 3) — affects WS3 (UX) scoping.

## 6. Artefacts

All scripts and data live under `automation/` and `samples/` on the `feat/prd-ws2-feasibility` branch (PR #31):

| Artefact | What it does | Re-runnable |
|---|---|---|
| `automation/prd_feasibility.py` | Population-rate probe over current `ranked.json` | Yes — wire into nightly to track scraper drift |
| `automation/precision_goldset.py` | 50-listing holdout sampler + precision/recall scorer | Yes (sample is seeded; rerun to regenerate) |
| `automation/ai_enrichment_dryrun.py` | GPT-4o-mini cost projection + execute-mode harness | Yes — supports `--execute` once API key is set |
| `automation/geocoding_probe.py` | Live HTML coordinate extraction probe | Yes — be polite (1.5s default delay) |
| `web/data/prd_feasibility.{md,json}` | Day 1 output | regen on each run |
| `samples/precision_goldset.{csv,LEGEND.md}` | Day 2 output (unlabeled) | regen on each run |
| `samples/ai_dryrun_{inputs.jsonl,summary.md}` | Day 3 output | regen on each run |
| `samples/geocoding_probe.{csv,md}` | Day 4 output | regen on each run |
| `docs/PRD_WS2_FEASIBILITY_DECISION.md` | This memo (Day 5) | manual update |

## 7. Decision

**Proceed with the WS2 PRD as written, with the four amendments above.** The feasibility gate has done its job: re-baselined three population targets, identified one load-bearing scraper fix, surfaced one UX-flagship filter that needs revision, and confirmed the geocoding/AI cost models are within budget.

The original 12-week sequence holds; we're inserting one extra week up front (Phase 0) and shipping with three corrected targets and a relaxed flagship filter.

---

*Hand-edit this memo before circulating to PM/Javi. The numbers are real; the prose is a draft.*
