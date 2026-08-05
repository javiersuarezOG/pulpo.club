# gating-depth — how much to show before the paywall

Traffic-gated funnel loop over the free/anon content gates
(`web/app/lib/gating.ts`). Objective: maximize checkout sessions per
anonymous detail view. Gating trades curiosity against frustration in
both directions, so the engagement guardrail matters as much as the
objective.

**Paused** until Phase-1 activation AND the multivariate-flag infra
(Track 1 #2) — this surface should run as an A/B (`ab-flag`), not
sequential edits: both arms accumulate samples concurrently, which
matters at low traffic. Guardrail thresholds below are provisional;
recalibrate from the measured baseline in iteration 1 before any
variable change.

```json goal-spec
{
  "name": "gating-depth",
  "status": "paused",
  "owner_goal": 1,
  "surface": "paywall-gating",
  "cadence": "biweekly",
  "human_ack_required": false,
  "metric": {
    "source": "posthog",
    "direction": "maximize",
    "unit": "ratio",
    "hogql": "SELECT countIf(event = 'stripe.checkout_session_created') / nullif(countIf(event = 'detail.opened' AND properties.auth_state = 'anonymous'), 0) AS value, countIf(event = 'detail.opened' AND properties.auth_state = 'anonymous') AS sample_n FROM events WHERE timestamp > now() - INTERVAL 14 DAY"
  },
  "guardrails": [
    {"name": "detail_opens_per_landing", "source": "posthog", "op": ">=", "threshold": 0.2,
     "hogql": "SELECT countIf(event = 'detail.opened') / nullif(countIf(event = 'landing.viewed'), 0) AS value, countIf(event = 'landing.viewed') AS sample_n FROM events WHERE timestamp > now() - INTERVAL 14 DAY"}
  ],
  "variables": [
    {"id": "usps_visible_anon", "file": "web/app/lib/gating.ts", "symbol": "USPS_VISIBLE_BY_TIER", "kind": "code", "current": 1, "range": [0, 3], "step": 1, "notes": "anon entry of the per-tier USP visibility record"},
    {"id": "usps_visible_free", "file": "web/app/lib/gating.ts", "symbol": "USPS_VISIBLE_BY_TIER", "kind": "code", "current": 2, "range": [1, 4], "step": 1, "notes": "free-tier entry of the same record"},
    {"id": "gallery_thumbs_anon", "file": "web/app/lib/gating.ts", "symbol": "GALLERY_THUMBS_UNLOCKED_BY_TIER", "kind": "code", "current": 2, "range": [1, 4], "step": 1, "notes": "anon entry of the per-tier gallery unlock record"},
    {"id": "gallery_thumbs_free", "file": "web/app/lib/gating.ts", "symbol": "GALLERY_THUMBS_UNLOCKED_BY_TIER", "kind": "code", "current": 2, "range": [1, 4], "step": 1, "notes": "free-tier entry of the same record"}
  ],
  "decision": {"method": "ab-flag", "min_sample": 500, "window_days": 14},
  "verification": [
    "npm run typecheck",
    "npm run build",
    "npm run e2e:smoke"
  ]
}
```

## /goal condition (paste to run one iteration)

```
/goal one iteration of goals/gating-depth is complete per goals/README.md: PostHog metric
JSON printed (scripts/goal_metrics.py --goal gating-depth), last change evaluated with a
keep/revert/hold decision printed with justification, journal.jsonl appended (entry shown),
and either a PR URL printed or a hold recorded — or stop after 15 turns
```

## Notes

- Vanity-shift protection: a change that raises signups while total
  `stripe.checkout_session_created` falls is a `revert`, not a `keep` —
  check the absolute count alongside the ratio.
- Watch `paywall.shown` volume as context; this loop shares a funnel
  with conversion-popup but locks a different surface, so both may hold
  in-flight changes only if their windows don't overlap on the same PR.
