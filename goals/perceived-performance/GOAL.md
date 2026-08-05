# perceived-performance — p75 LCP/INP on real traffic

Loop over the browse-render tunables. Objective: minimize p75 LCP from
the already-instrumented `web_vitals.*` PostHog events (see
`web/app/telemetry/web-vitals.ts`). Measurement is per-deploy, decisions
weekly (p75 needs page-load volume).

**Paused** until Phase-1 activation. The single largest one-time perf
lever is Track 1 #3 (list-payload slim/shard) — land that first; this
loop tunes the residual.

```json goal-spec
{
  "name": "perceived-performance",
  "status": "paused",
  "owner_goal": 5,
  "surface": "browse-render",
  "cadence": "weekly",
  "human_ack_required": false,
  "metric": {
    "source": "posthog",
    "direction": "minimize",
    "unit": "ms",
    "hogql": "SELECT quantile(0.75)(toFloat(properties.value)) AS value, count() AS sample_n FROM events WHERE event = 'web_vitals.lcp' AND timestamp > now() - INTERVAL 7 DAY"
  },
  "guardrails": [
    {"name": "cls_p75", "source": "posthog", "op": "<=", "threshold": 0.1,
     "hogql": "SELECT quantile(0.75)(toFloat(properties.value)) AS value, count() AS sample_n FROM events WHERE event = 'web_vitals.cls' AND timestamp > now() - INTERVAL 7 DAY"},
    {"name": "inp_p75", "source": "posthog", "op": "<=", "threshold": 500,
     "hogql": "SELECT quantile(0.75)(toFloat(properties.value)) AS value, count() AS sample_n FROM events WHERE event = 'web_vitals.inp' AND timestamp > now() - INTERVAL 7 DAY"}
  ],
  "variables": [
    {"id": "page_size", "file": "web/app/pages.jsx", "symbol": "PAGE_SIZE", "kind": "code", "current": 60, "range": [24, 96], "step": 12, "notes": "cards per Load-more page on /browse"},
    {"id": "photo_preload_max", "file": "web/app/components.jsx", "symbol": "PHOTO_PRELOAD_MAX", "kind": "code", "current": 5, "range": [2, 8], "step": 1, "notes": "secondary card photos prefetched on hover"},
    {"id": "max_markers", "file": "web/app/components/MapView.jsx", "symbol": "MAX_MARKERS", "kind": "code", "current": 5000, "range": [1000, 5000], "step": 1000, "notes": "map marker cap before truncation"}
  ],
  "decision": {"method": "one-at-a-time", "min_sample": 200, "window_days": 7},
  "verification": [
    "npm run typecheck",
    "npm run build",
    "npm run e2e:smoke"
  ]
}
```

## /goal condition (paste to run one iteration)

```
/goal one iteration of goals/perceived-performance is complete per goals/README.md: PostHog
metric JSON printed (scripts/goal_metrics.py --goal perceived-performance), last change
evaluated with a keep/revert/hold decision printed with justification, journal.jsonl
appended (entry shown), and either a PR URL printed or a hold recorded — or stop after 15 turns
```

## Notes

- Segment by route via `properties.route` when diagnosing (LCP
  attribution props identify hero vs card vs text) — the objective
  stays global p75 to avoid metric shopping.
- Engagement guardrail to watch manually while PAGE_SIZE shrinks:
  `browse.load_more_clicked` shouldn't crater.
