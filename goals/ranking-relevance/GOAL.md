# ranking-relevance — do users click what we rank on top?

Hybrid loop over the ranker's leg weights (`pulpo/ranker.py`, env
`PULPO_W_*` consumed there, set in `.github/workflows/pulpo-nightly.yml`).
Objective: CTR@20 — detail opens per card impression in the top-20
positions. The ranker is currently supply-side only; this loop is the
first demand signal feeding back into ranking.

**Paused — blocked on `browse.card_impression` instrumentation**
(Phase 0 #3). The hogql below is provisional: if impressions ship
batched (listing_ids array), rewrite the query against the final event
shape before activating. Needs 2+ weeks of impression data first.

```json goal-spec
{
  "name": "ranking-relevance",
  "status": "paused",
  "owner_goal": 3,
  "surface": "ranker-weights",
  "cadence": "weekly",
  "human_ack_required": false,
  "metric": {
    "source": "posthog",
    "direction": "maximize",
    "unit": "ratio",
    "hogql": "SELECT countIf(event = 'detail.opened') / nullif(countIf(event = 'browse.card_impression' AND toInt(properties.position) < 20), 0) AS value, countIf(event = 'browse.card_impression' AND toInt(properties.position) < 20) AS sample_n FROM events WHERE timestamp > now() - INTERVAL 7 DAY"
  },
  "guardrails": [
    {"name": "catalog_floor", "source": "supply", "series": "listing_total", "op": ">=", "threshold": 1000},
    {"name": "canary_ceiling", "source": "supply", "series": "listing_total", "op": "<=", "threshold": 3500}
  ],
  "variables": [
    {"id": "w_value", "file": "pulpo/ranker.py", "symbol": "PULPO_W_VALUE", "kind": "env", "current": 0.40, "range": [0.25, 0.55], "step": 0.05, "notes": "value-leg weight (weights renormalize to 1)"},
    {"id": "w_location", "file": "pulpo/ranker.py", "symbol": "PULPO_W_LOCATION", "kind": "env", "current": 0.35, "range": [0.20, 0.50], "step": 0.05, "notes": "location-leg weight"},
    {"id": "w_momentum", "file": "pulpo/ranker.py", "symbol": "PULPO_W_MOMENTUM", "kind": "env", "current": 0.25, "range": [0.10, 0.40], "step": 0.05, "notes": "momentum-leg weight"},
    {"id": "w_quality", "file": "pulpo/ranker_legs/quality_score.py", "symbol": "PULPO_W_QUALITY", "kind": "env", "current": 0.05, "range": [0.0, 0.15], "step": 0.05, "notes": "quality-nudge weight (leg self-registers; env read in the leg file)"}
  ],
  "decision": {"method": "one-at-a-time", "min_sample": 400, "window_days": 7},
  "verification": [
    "PULPO_OFFLINE=1 pytest -q tests/test_canary_validation_alignment.py",
    "ruff check pulpo automation scripts"
  ]
}
```

## /goal condition (paste to run one iteration)

```
/goal one iteration of goals/ranking-relevance is complete per goals/README.md: PostHog
metric JSON printed (scripts/goal_metrics.py --goal ranking-relevance), last change
evaluated with a keep/revert/hold decision printed with justification, journal.jsonl
appended (entry shown), and either a PR URL printed or a hold recorded — or stop after 15 turns
```

## Notes

- Whiplash guardrail (manual until scripted): top-50 turnover between
  consecutive nightlies should stay ≤ 40% after a weight change — users
  notice reshuffles. Compare `git show <sha>:web/data/ranked.json` head
  slices when in doubt.
- Weight changes take effect on the next nightly; the 7-day window
  starts from the first nightly that ran with the new weights, not from
  the merge.
- Secondary metrics worth printing each iteration: saves-per-impression,
  `detail.source_outbound_clicked` per session (once instrumented).
