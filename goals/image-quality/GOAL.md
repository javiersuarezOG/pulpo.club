# image-quality — best possible hero images

Supply-side loop over the two-phase photo pipeline (cheap technical
scoring in `automation/photo_quality.py` + LLM aesthetic booster in
`automation/aesthetic_vision.py`). Objective: maximize the share of
listings that ship a locally-served hero derivative, without letting the
missing-hero tail grow. Reads nightly-committed `web/data` — no user
traffic needed, so this loop iterates every 2–3 nights (one nightly to
apply, one-plus to confirm).

Winning threshold changes can be retro-applied to the existing catalog
with `python3 automation/repick_heroes.py` (dry-run first).

Related one-time item (Track 1 #4): flipping `LLM_VISION_ENABLED` on is
its own PR, not a loop variable — the loop then tunes TOP_PCT/budget.

```json goal-spec
{
  "name": "image-quality",
  "status": "active",
  "owner_goal": 4,
  "surface": "image-pipeline",
  "cadence": "nightly",
  "human_ack_required": false,
  "metric": {
    "source": "supply",
    "direction": "maximize",
    "unit": "pct",
    "series": ["hero_with_local_pct", "hero_local_missing_rate"]
  },
  "guardrails": [
    {"name": "broken_local_path_rate", "source": "supply", "series": "hero_local_missing_rate", "op": "<=", "threshold": 0.05},
    {"name": "catalog_floor", "source": "supply", "series": "listing_total", "op": ">=", "threshold": 1000},
    {"name": "nightly_runtime", "source": "supply", "series": "nightly_duration_s", "op": "<=", "threshold": 14400}
  ],
  "variables": [
    {"id": "text_min_conf", "file": "automation/photo_quality.py", "symbol": "TEXT_MIN_CONF", "kind": "code", "current": 60, "range": [40, 80], "step": 5, "notes": "Tesseract per-word confidence floor for text-overlay flagging"},
    {"id": "text_min_words", "file": "automation/photo_quality.py", "symbol": "TEXT_MIN_WORDS", "kind": "code", "current": 8, "range": [5, 12], "step": 1, "notes": "qualifying-word count that flags a marketing overlay"},
    {"id": "text_overlay_penalty", "file": "automation/photo_quality.py", "symbol": "_TEXT_OVERLAY_PENALTY", "kind": "code", "current": 50, "range": [30, 70], "step": 10, "notes": "subtracted from cheap score when overlay flagged"},
    {"id": "picker_floor", "file": "automation/photo_quality.py", "symbol": "_DEFAULT_PICKER_MIN_CHEAP_SCORE", "kind": "code", "current": 40, "range": [30, 60], "step": 5, "notes": "below floor = permanently excluded from picker; lower = more LLM spend, fewer misses"},
    {"id": "vision_top_pct", "file": "automation/run.py", "symbol": "LLM_VISION_TOP_PCT", "kind": "env", "current": 5, "range": [5, 25], "step": 5, "notes": "% of uncached candidates eligible for aesthetic LLM per nightly"},
    {"id": "vision_daily_budget", "file": "automation/aesthetic_vision.py", "symbol": "LLM_VISION_DAILY_BUDGET_USD", "kind": "env", "current": 1.0, "range": [0.5, 2.0], "step": 0.5, "notes": "daily spend cap for the aesthetic booster"}
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
/goal one iteration of goals/image-quality is complete per goals/README.md: supply metric
JSON printed (scripts/goal_supply_metrics.py --goal image-quality), last change evaluated
with a keep/revert/hold decision printed with justification, journal.jsonl appended (entry
shown), and either a PR URL printed or a hold recorded — or stop after 15 turns
```

## Notes

- `min_sample: 1` — supply metrics are census, not samples; the
  `window_days: 3` decision window (2–3 nightlies) is the real gate.
- Series semantics: `hero_with_local_pct` = share of ranked listings
  with a local hero derivative (objective, 68.4% at registration);
  `hero_local_missing_rate` = share of local paths whose FILE is
  missing (photo_contract.json `missing_rate`, 0.0 healthy — a rise
  is the PR-#781 archived-heroes-404 regression class, hence the
  tight 0.05 guardrail).
- Photo-phase wall clock (`PULPO_PHOTO_BUDGET_S=600`) and the $/day
  vision budget are the cost guardrails; the nightly_runtime guardrail
  catches indirect blowups.
- Local pytest on `tests/test_photos.py` may fail with the libjpeg ABI
  mismatch documented in CLAUDE.md — that failure is env-only, not a
  loop signal.
