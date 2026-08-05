# goals/ — the optimization-loop registry

Each subdirectory is one **optimization goal**: a measurable objective,
the tunable variables that move it, guardrails, and an append-only
experiment journal. Iterations are driven by Claude Code's **native
`/goal` command** — each GOAL.md carries a ready-to-paste condition
block. One `/goal` run completes exactly **one iteration** (measure →
evaluate → change-or-hold → PR). Cadence across sessions comes from
`/schedule` routines or manual re-invocation; see "Cadence" below.

Registry overview: run `python3 scripts/goal_status.py`.

## Layout

```
goals/
  README.md              ← this protocol (referenced by every /goal condition)
  <name>/
    GOAL.md              ← prose + ```json goal-spec fenced block + /goal condition
    journal.jsonl        ← append-only iteration log (one JSON object per line)
```

The machine-readable spec is a fenced block marked ` ```json goal-spec `
inside GOAL.md (JSON, not YAML — the pytest suite is hermetic and has no
YAML dependency). `scripts/goal_registry.py` is the single parser;
`tests/test_goal_registry.py` validates every spec in CI, including that
each variable's `file` exists and its `symbol` still greps — renaming a
tunable without updating the registry fails CI on purpose.

## Spec schema (the `json goal-spec` block)

| Key | Meaning |
|-----|---------|
| `name` | must equal the directory name |
| `status` | `active` \| `paused` \| `done` — paused goals refuse iterations |
| `owner_goal` | 1-6, Sebastian's goal list (conversion, referrals, listings, images, perf, engagement) |
| `surface` | lock key — **one in-flight `change` per surface** across all goals |
| `cadence` | `nightly` \| `weekly` \| `biweekly` \| `per-deploy` |
| `human_ack_required` | `true` = stop and ask Sebastian before opening any PR (price/billing) |
| `metric` | `{source: posthog\|supply, direction, unit, hogql\|series}` — the objective |
| `guardrails[]` | `{name, source, hogql\|series, op: <=\|>=, threshold}` — hard constraints |
| `variables[]` | `{id, file, symbol, kind: code\|env, current, range: [min,max], step, notes}` |
| `decision` | `{method: one-at-a-time\|ab-flag, min_sample, window_days}` |
| `verification[]` | shell commands the iteration PR must pass locally before opening |

Metric/guardrail contracts:
- `source: posthog` — `hogql` must `SELECT` columns aliased `value` and
  `sample_n` (single row). Executed via `scripts/goal_metrics.py`.
- `source: supply` — `series` names come from the extractor set in
  `scripts/goal_supply_metrics.py` (git history of nightly-committed
  `web/data/*.json` is the time-series DB). First series is the primary
  metric.

## Journal entry schema (journal.jsonl)

```json
{"ts": "2026-08-12T09:00Z", "iter": 3, "action": "change",
 "variable": "TIMER_MS", "from": 30000, "to": 25000,
 "hypothesis": "earlier timer catches short sessions",
 "baseline": {"metric": 0.021, "n": 412},
 "decision_due": "2026-08-19", "pr": "https://github.com/.../pull/1234"}
```

`action` is one of:
- `init` — goal registered, no change yet
- `change` — a variable edit shipped (PR opened); starts a decision window
- `hold` — measured, but sample too small or window not elapsed; no edit
- `keep` — last change confirmed better; becomes the new baseline
- `revert` — last change worsened the metric or tripped a guardrail; revert PR opened
- `ack_required` — iteration stopped awaiting Sebastian (human_ack_required goals)

Append-only. Never rewrite or delete lines; never edit another goal's
journal. The `change` entry ships **in the same commit** as the variable
edit so the journal and the code never drift.

## The iteration algorithm (what one `/goal` run executes)

1. **Load** `goals/<name>/GOAL.md` + `journal.jsonl`. Verify
   `status: active`. Check surface locks
   (`scripts/goal_registry.py:active_surface_locks`) — if another goal
   holds an in-flight `change` on the same surface, stop with `hold`.
2. **Measure** — run the matching reader and **print the JSON output**:
   - posthog: `python3 scripts/goal_metrics.py --goal <name>`
   - supply:  `python3 scripts/goal_supply_metrics.py --goal <name>`
   If `sample_n < decision.min_sample` OR `now < decision_due` of the
   last `change` → append `hold` (print the entry), done. Doing nothing
   is a valid, common outcome at low traffic.
3. **Evaluate the last `change`** against its recorded `baseline` and
   **print the decision + justification**:
   - improved beyond the noise floor, guardrails pass → `keep`
   - worsened, or any guardrail fails → `revert` (open the revert PR FIRST)
   - inconclusive → extend the window once; on the second inconclusive,
     `revert` by default (bias to known-good).
   Noise floor: for ratio metrics run a crude two-proportion z-check at
   the recorded `n`s; refuse to declare a winner below ~95% confidence.
4. **Propose the next change** — hill-climb: continue the direction of
   the last `keep`, else round-robin to the next variable; move by
   `step`, clamped to `range`. **Refuse** any edit outside the declared
   `variables` list or outside `range`.
5. **Ship** — feature branch off origin/main (worktree convention),
   single-variable diff + journal `change` entry in the same commit, run
   every `verification` command, open a PR titled
   `goal(<name>) iter N: SYMBOL from→to` whose body carries hypothesis,
   baseline, decision date, and revert plan. **Print the PR URL.**
   **Never self-merge** — Sebastian merges (CLAUDE.md).
6. Done. One iteration per `/goal` run.

## Hard safety rails

- `human_ack_required: true` goals (anything touching price, billing
  copy, or removal of paid features) stop at step 4 with `ack_required`
  and wait for Sebastian. Price additionally requires
  `node scripts/check_price_sync.mjs` to pass.
- **Never touch `web/data/`** — pipeline-owned.
- Pipeline tunables always include
  `PULPO_OFFLINE=1 pytest -q tests/test_canary_validation_alignment.py`
  in `verification`; respect `LISTING_COUNT_FLOOR/CEILING` in
  `.github/workflows/pulpo-nightly.yml`.
- `method: one-at-a-time` until the PostHog multivariate flag infra
  lands; then funnel goals may switch to `ab-flag` (both arms run
  concurrently — preferred at low traffic).
- Auth/billing surfaces: the PR body must say "requires Vercel preview
  walk" and the iteration is not `keep`-able until merged + a full
  decision window elapsed post-merge.
- All CLAUDE.md gates apply unchanged (screenshots for visual diffs,
  i18n `t()`, e2e smoke, etc. — listed per-goal in `verification`).

## Cadence

- Interactive: paste the goal's stored `/goal` condition (see each
  GOAL.md); pair with auto mode for unattended turns. The `/goal`
  evaluator cannot call tools — it judges only what is printed, which is
  why steps 2/3/5 above **print** their evidence.
- Unattended: `/schedule` routines whose prompt embeds the same
  iteration contract (weekly funnel goals Monday 09:00; nightly supply
  goals 09:00 UTC, after the 02:00 UTC nightly lands).
- Review: `python3 scripts/goal_status.py` — one-glance table; every
  goal's first two iterations get human review before its schedule goes
  unattended.
