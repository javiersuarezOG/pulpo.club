# conversion-popup — USP popup → checkout conversion

Traffic-gated funnel loop over the USP popup's trigger tunables
(`web/app/lib/usp-popup-trigger.ts`). Objective: maximize
`usp_popup.cta_clicked / usp_popup.shown` without turning the popup into
an annoyance (dismiss-rate guardrail). All events already exist.

**Paused** until Phase-1 activation (plan: weeks 3–5) — flip `status` to
`active` and let the min-sample discipline gate the first decision.

```json goal-spec
{
  "name": "conversion-popup",
  "status": "paused",
  "owner_goal": 1,
  "surface": "paywall-popup",
  "cadence": "weekly",
  "human_ack_required": false,
  "metric": {
    "source": "posthog",
    "direction": "maximize",
    "unit": "ratio",
    "hogql": "SELECT countIf(event = 'usp_popup.cta_clicked') / nullif(countIf(event = 'usp_popup.shown'), 0) AS value, countIf(event = 'usp_popup.shown') AS sample_n FROM events WHERE timestamp > now() - INTERVAL 7 DAY"
  },
  "guardrails": [
    {"name": "dismiss_rate", "source": "posthog", "op": "<=", "threshold": 0.85,
     "hogql": "SELECT countIf(event = 'usp_popup.dismissed') / nullif(countIf(event = 'usp_popup.shown'), 0) AS value, countIf(event = 'usp_popup.shown') AS sample_n FROM events WHERE timestamp > now() - INTERVAL 7 DAY"}
  ],
  "variables": [
    {"id": "suppression_days", "file": "web/app/lib/usp-popup-trigger.ts", "symbol": "SUPPRESSION_DAYS", "kind": "code", "current": 7, "range": [3, 14], "step": 2, "notes": "days the popup stays suppressed after a dismissal"},
    {"id": "scroll_threshold", "file": "web/app/lib/usp-popup-trigger.ts", "symbol": "SCROLL_THRESHOLD", "kind": "code", "current": 0.5, "range": [0.3, 0.7], "step": 0.1, "notes": "scroll fraction that fires the scroll trigger"},
    {"id": "timer_ms", "file": "web/app/lib/usp-popup-trigger.ts", "symbol": "TIMER_MS", "kind": "code", "current": 30000, "range": [15000, 60000], "step": 5000, "notes": "time-on-page before the timer trigger fires"}
  ],
  "decision": {"method": "one-at-a-time", "min_sample": 300, "window_days": 7},
  "verification": [
    "npm run typecheck",
    "npm run build",
    "npm run e2e:smoke"
  ]
}
```

## /goal condition (paste to run one iteration)

```
/goal one iteration of goals/conversion-popup is complete per goals/README.md: PostHog
metric JSON printed (scripts/goal_metrics.py --goal conversion-popup), last change evaluated
with a keep/revert/hold decision printed with justification, journal.jsonl appended (entry
shown), and either a PR URL printed or a hold recorded — or stop after 15 turns
```

## Notes

- `min_sample: 300` shows — at current traffic a 7-day window may hold
  several weeks in a row. That is the loop working, not failing.
- Once the PostHog multivariate-flag infra lands (Track 1 #2), switch
  `decision.method` to `ab-flag` and run trigger variants concurrently
  instead of sequentially.
- Downstream confirmation metric (not the objective): `paywall.shown` →
  `upgrade.checkout_started` funnel in the umbrella dashboard.
