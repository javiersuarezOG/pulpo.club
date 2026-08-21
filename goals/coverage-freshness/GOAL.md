# coverage-freshness — exhaustive, up-to-date listings

Supply-side loop over the crawl + validation layer. Objective: maximize
kept catalog size (within the nightly canary ceiling) while keeping
sources green and the nightly inside its runtime budget. Reads
nightly-committed `web/data` — iterates every 2–3 nights.

A discrete action also belongs to this loop (not a numeric variable):
when a zone/coverage gap persists, onboard one new source per week via
the existing scraper-agent autoresearch flow (~$0.01/source, see
project memory `project_scraper_agent_autoresearch`).

```json goal-spec
{
  "name": "coverage-freshness",
  "status": "active",
  "owner_goal": 3,
  "surface": "scraper-pipeline",
  "cadence": "nightly",
  "human_ack_required": false,
  "metric": {
    "source": "supply",
    "direction": "maximize",
    "unit": "listings",
    "series": ["listing_total", "sources_green_pct", "visible_total"]
  },
  "guardrails": [
    {"name": "canary_ceiling", "source": "supply", "series": "listing_total", "op": "<=", "threshold": 3500},
    {"name": "canary_floor", "source": "supply", "series": "listing_total", "op": ">=", "threshold": 1000},
    {"name": "sources_green", "source": "supply", "series": "sources_green_pct", "op": ">=", "threshold": 60},
    {"name": "nightly_runtime", "source": "supply", "series": "nightly_duration_s", "op": "<=", "threshold": 14400}
  ],
  "variables": [
    {"id": "per_source_limit", "file": ".github/workflows/pulpo-nightly.yml", "symbol": "PULPO_LIMIT", "kind": "env", "current": 1000, "range": [1000, 2000], "step": 250, "notes": "corrected 2026-08-21 (iter 1): registry said current=30/range=[30,100], deployed value is 1000 — moved there for e24 rollout, unrelated to this loop. Workflow comment reserves raising toward 2000 for after the e24 photo/detail-crawl cost is reduced (see PULPO_E24_LIMIT comment) — do not hill-climb this until that precondition is confirmed cleared."},
    {"id": "scrape_concurrency", "file": ".github/workflows/pulpo-nightly.yml", "symbol": "PULPO_SCRAPE_CONCURRENCY", "kind": "env", "current": 6, "range": [6, 7], "step": 0, "notes": "corrected 2026-08-21 (iter 1): registry said current=1/range=[1,2] with '2 is the ban-risk ceiling' — deployed default (vars.PULPO_SCRAPE_CONCURRENCY, workflow line 185) is already 6, contradicting that claim. Last 30 source_health_history rows show 0 red sources, but that is not a ban-risk audit. Range frozen to the observed value until someone validates the actual ceiling with real evidence; do not hill-climb on the old, disproven '2' claim."},
    {"id": "days_drop_max", "file": "automation/validation_bounds.py", "symbol": "DAYS_DROP_MAX", "kind": "code", "current": 3650, "range": [1825, 3650], "step": 365, "notes": "hard-drop listings older than this; lowering trades count for freshness — canary-aligned edits only. 2026-08-21 (iter 1): 0 of 1849 kept listings sit in [1825,3650) days_listed today, so any move within this range is a content-free no-op against the current catalog — hold until a future run's distribution actually reaches this band."}
  ],
  "decision": {"method": "one-at-a-time", "min_sample": 1, "window_days": 3},
  "verification": [
    "PULPO_OFFLINE=1 pytest -q tests/test_canary_validation_alignment.py",
    "ruff check automation scripts"
  ]
}
```

## /goal condition (paste to run one iteration)

```
/goal one iteration of goals/coverage-freshness is complete per goals/README.md: supply
metric JSON printed (scripts/goal_supply_metrics.py --goal coverage-freshness), last change
evaluated with a keep/revert/hold decision printed with justification, journal.jsonl
appended (entry shown), and either a PR URL printed or a hold recorded — or stop after 15 turns
```

## Notes

- `days_drop_max` moves must respect the canary-vs-validation alignment
  contract (`tests/test_canary_validation_alignment.py`, PR #618
  precedent) — the workflow canary and `validation_bounds.py` change
  together or not at all.
- Env-kind variables (`PULPO_LIMIT`, `PULPO_SCRAPE_CONCURRENCY`) are set
  in `.github/workflows/pulpo-nightly.yml`'s env block; the `file` here
  names where the default is consumed.
- The 2026-08-05 registration baseline: 1887 kept listings, 15
  registered sources, encuentra24 coverage 1% of discovered (2947 PRD
  target) — the single biggest coverage lever is `per_source_limit`
  against encuentra24.
- **Iter 1 (2026-08-21): registry-correction, no tunable moved.**
  Metric: listing_total=1849, sources_green_pct=93.33, all guardrails
  pass with large headroom (runtime at 26% of the 14400s ceiling).
  `per_source_limit` and `scrape_concurrency`'s registered `current`/
  `range` had drifted 10x/6x from deployed reality — both variables
  moved for documented reasons unrelated to this loop's iterations
  (encuentra24 rollout cost, an undocumented concurrency bump).
  Hill-climbing from the stale baselines would have been meaningless;
  the CI registry test only checks file+symbol existence, not that
  `current` matches deployed reality, so this kind of drift is
  silent by construction. Corrected all three variables' metadata to
  observed truth (see each `notes` field) and recorded `hold` in the
  journal — no PR opens a pipeline edit this iteration. `days_drop_max`
  remains the only variable both accurate AND safely in-range, but
  today's catalog has zero listings anywhere near its boundary, so
  moving it now would be a no-op experiment; revisit once distribution
  data shows listings actually approaching the band.
