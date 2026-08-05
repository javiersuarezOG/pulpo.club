# enrichment-copy — does the listing copy make people act?

Deliberately slow loop over the DeepSeek enrichment prompt
(`automation/llm_enrichment_prompts.py`). Objective: detail views that
convert to a save (proxy for "the copy earned belief"). Biweekly at
most, because a `PROMPT_VERSION` bump invalidates the enrichment sidecar
cache and re-pays the DeepSeek bill for the whole catalog — the
projected cost is part of every change entry.

**Paused** until Phase-2 activation. Prompt-content changes (word caps,
USP style) live inside the prompt strings and always ride a
`PROMPT_VERSION` bump — the version is the only greppable tunable, which
is why it is the single registered variable.

```json goal-spec
{
  "name": "enrichment-copy",
  "status": "paused",
  "owner_goal": 3,
  "surface": "enrichment-prompts",
  "cadence": "biweekly",
  "human_ack_required": false,
  "metric": {
    "source": "posthog",
    "direction": "maximize",
    "unit": "ratio",
    "hogql": "SELECT countIf(event = 'save.toggled' AND properties.action = 'add') / nullif(countIf(event = 'detail.opened'), 0) AS value, countIf(event = 'detail.opened') AS sample_n FROM events WHERE timestamp > now() - INTERVAL 14 DAY"
  },
  "guardrails": [
    {"name": "catalog_floor", "source": "supply", "series": "listing_total", "op": ">=", "threshold": 1000}
  ],
  "variables": [
    {"id": "prompt_version", "file": "automation/llm_enrichment_prompts.py", "symbol": "PROMPT_VERSION", "kind": "code", "current": 4, "range": [4, 20], "step": 1, "notes": "monotonic; each bump = prompt-content change + full catalog re-enrichment bill (~$2 order of magnitude, record projection in journal)"}
  ],
  "decision": {"method": "one-at-a-time", "min_sample": 300, "window_days": 14},
  "verification": [
    "PULPO_OFFLINE=1 pytest -q tests/test_canary_validation_alignment.py tests/test_bilingual_coverage.py",
    "ruff check automation scripts"
  ]
}
```

## /goal condition (paste to run one iteration)

```
/goal one iteration of goals/enrichment-copy is complete per goals/README.md: PostHog metric
JSON printed (scripts/goal_metrics.py --goal enrichment-copy), last change evaluated with a
keep/revert/hold decision printed with justification including projected re-enrichment cost,
journal.jsonl appended (entry shown), and either a PR URL printed or a hold recorded — or
stop after 15 turns
```

## Notes

- Bilingual EN+ES invariant applies to every prompt change (CLAUDE.md
  "NEVER ship a listing that isn't bilingual") — the deterministic
  fallback + `ensure_bilingual.py` safety net must stay intact.
- The description hype-lint (`automation/description_lint.py` blocklist)
  is the static floor; this loop optimizes above it, never around it.
- Segmenting the metric by prompt-version cohort requires stamping the
  version into a client-visible property — a small follow-up when this
  goal activates.
