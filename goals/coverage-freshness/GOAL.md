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
    {"id": "per_source_limit", "file": "automation/run.py", "symbol": "PULPO_LIMIT", "kind": "env", "current": 30, "range": [30, 100], "step": 10, "notes": "listings crawled per source; raising widens coverage at bandwidth/runtime cost"},
    {"id": "scrape_concurrency", "file": "automation/run.py", "symbol": "PULPO_SCRAPE_CONCURRENCY", "kind": "env", "current": 1, "range": [1, 2], "step": 1, "notes": "parallel sources; per-host rate limiters unchanged, but 2 is the ban-risk ceiling"},
    {"id": "days_drop_max", "file": "automation/validation_bounds.py", "symbol": "DAYS_DROP_MAX", "kind": "code", "current": 3650, "range": [1825, 3650], "step": 365, "notes": "hard-drop listings older than this; lowering trades count for freshness — canary-aligned edits only"}
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
- The 2026-08 baseline: 1887 kept listings, 15 registered sources,
  encuentra24 coverage 1% of discovered (2947 PRD target) — the single
  biggest coverage lever is `per_source_limit` against encuentra24.
