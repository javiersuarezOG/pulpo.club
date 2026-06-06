# Nightly Resilience PRD

## Working Title

Stop stranding valid inventory when one guard fails.

## Priority

P0 incident-response architecture work.

## Context

The nightly pipeline can generate a valid catalogue and still lose it because a downstream guard exits non-zero before the candidate data is written or promoted.

Recent evidence:

- GitHub Actions run `27050642483`, started `2026-06-06 02:55 UTC`, failed after roughly 2h52m inside the `Run pipeline` step.
- Before failing, the pipeline had produced `2107` ranked listings pre-purge, `1913` post agricultural-land purge, `1678` visible listings, `17/19` active sources, and `5/6` shelves rendering.
- The run failed on the population regression guard because `is_motivated` dropped from `15.3%` to `8.1%`. That was a population-mix shift caused by Phase C's land-dominant sources, not evidence that the catalogue was unusable.
- The guard ran before `phase_write_outputs` in `automation/run.py`, so the fresh candidate never reached `web/data`.
- `.github/workflows/pulpo-nightly.yml` then skipped snapshot, commit, and deploy.
- Run `27054371155` was cancelled mid-pipeline. Again, no durable candidate artifact survived.

Current failure boundary:

```text
scrape -> validate -> rank -> enrich -> photo phase -> guards -> write outputs -> commit -> deploy
```

Target failure boundary:

```text
scrape -> validate -> rank -> write candidate artifact -> guards -> promote or quarantine -> commit/deploy
```

A guard may block promotion. It must never erase the candidate, hide diagnostics, or make the system look like nothing happened.

## Phase 0 Emergency Bedding-In

Phase 0 is not the architecture fix. It temporarily allows the expanded Phase C catalogue to ship while R1-R9 are implemented.

Workflow changes:

- `LISTING_COUNT_FLOOR` becomes `1000`.
- `LISTING_COUNT_CEILING` becomes `3500`.
- Per-type canary `LOG_ONLY` becomes `true`.
- Hero variant canary receives `continue-on-error: true`.
- Repo variable `DATA_QUALITY_LOG_ONLY=true` should be set during the bedding-in window.

Every override must carry a removal comment:

```text
REMOVE 2026-06-13 after 7 green post-Phase-C nightlies, or sooner once the corresponding R-series fix lands.
```

## R1 - Durable Candidate Bundle Before Guards

Move candidate writing before regression, photo, shelf, and population guards.

New file:

- `automation/candidate_bundle.py`

Candidate bundle path:

```text
web/data/.staging/<run_id>/
```

Bundle contents:

- `ranked.json`
- `ranked.list.json`
- `featured.json`
- `last_updated.candidate.json`
- `shelf_audit.json`
- `source_health_history.jsonl`
- `run_history.json`
- `photo_contract.json`
- `kpi_dashboard.json`
- `dedup_audit.json`
- `guard_report.json`
- `bundle_manifest.json`

`bundle_manifest.json` must be schema-versioned and include SHA256 hashes for every file.

Acceptance:

- A guard-failed run still uploads `candidate_bundle_<run_id>`.
- The artifact contains the fresh `ranked.json`.
- Slack says candidate generated and promotion blocked.
- Recovery command is available: `python scripts/promote_candidate.py --run-id <id>`.

## R2 - Guard Policy Matrix

Create `automation/guard_policy.py` and move guard logic into `automation/guards/`.

Guard return shape:

```json
{
  "name": "population_regression",
  "severity": "warn",
  "decision": "warn",
  "recoverable": true,
  "message": "Population-rate shift in is_motivated: 15.3% -> 8.1%",
  "metrics": {
    "field": "is_motivated",
    "before": 0.153,
    "after": 0.081,
    "delta_rel": 0.475
  },
  "evidence_uri": "artifacts/<run_id>/regression_evidence.json"
}
```

Severity policy:

- `block`: catastrophic corruption. Invalid JSON, zero inventory, broken required fields, country contamination, route cannot render, catastrophic dedup collapse, or no candidate artifact.
- `warn`: shippable degradation. Optional source red, population mix shift, photo coverage below ideal while fallback exists, shelf missing due to source brownout, incomplete LLM enrichment.
- `quarantine`: unknown state requiring a human.

Acceptance:

- Population percentage shifts no longer hard-fail if total visible inventory is above floor.
- True catastrophic count collapse still blocks.
- `guard_report.json` is written into the candidate bundle.

## R3 - Nightly Workflow Phase Split

Refactor `.github/workflows/pulpo-nightly.yml` into phase jobs:

```text
scrape-sv
scrape-pa
merge-rank
write-candidate
run-guards
promote
commit-deploy
```

Only `commit-deploy` should be single-flight, using a `nightly-commit` concurrency group with `cancel-in-progress: false`.

Acceptance:

- If guards fail, the candidate artifact still exists.
- If promote fails, the candidate artifact still exists.
- If commit/deploy fails, main remains at the previous known-good state.
- PA failure cannot block SV promotion unless country contamination is detected.

## R4 - Promotion / Quarantine Model

Add `automation/promotion.py`.

Promotion statuses:

- `promoted`
- `degraded_promoted`
- `quarantined`

`last_updated.json` gains:

- `candidate_generated_at`
- `promoted_at`
- `promotion_status`
- `degraded_reasons`
- `previous_promotion_id`

Acceptance:

- Degraded but valid catalogues can deploy.
- Failed candidates are preserved and linked.
- The lineage of degraded promotions is visible.

## R5 - Truthful Nightly Summary

Rewrite `scripts/nightly_summary.py` so it reads candidate metadata and promotion decisions instead of stale committed files.

Required fields:

- candidate generated timestamp
- candidate visible count
- candidate artifact URL
- guard decisions
- promotion decision
- commit status
- deploy status
- previous live data age

Acceptance:

- A guard-failed run says candidate generated but not promoted.
- A cancelled run says where it was cancelled.
- Commit skipped is distinct from commit ran with no changes.

## R6 - Stranded Inventory Alerts

Alert when:

```text
candidate_visible_count > 0 && promoted == false
```

Slack message must include:

- run id
- visible count
- guard reasons
- artifact URL
- recovery command

Also open a persistent GitHub Issue deduped by run id.

Acceptance:

- Slack and GitHub Issue both fire for stranded inventory.
- If Slack fails, the issue still exists.
- The issue auto-closes on the next successful promotion or manual promote.

## R7 - Decouple Photo/LLM From Critical Path

Photo download and LLM enrichment should not prevent catalogue freshness.

Requirements:

- Ranking can complete without fresh photo downloads.
- Cached photos satisfy the hero canary.
- Photo backfill runs separately.
- Top photo coverage remains visible in telemetry.

Hero canary policy:

- `PASS`: top 10 have cached or fresh `.hero.jpg`.
- `WARN`: at least 7 of top 10 covered.
- `FAIL`: fewer than 7 of top 10 covered.

## R8 - Per-Source Matrix + Partial Success

Move toward per-source scrape artifacts:

- `<source>_raw.jsonl`
- `<source>_normalized.jsonl`
- `<source>_status.json`
- `<source>_failure_snapshot.json`

Sources red for more than 7 days continue scraping but are excluded from promotion until recovered.

Acceptance:

- One red source cannot poison the whole run.
- Every source has raw count, kept count, failure id, duration, last green timestamp, and freshness SLA.

## R9 - Recovery CLI

Add:

- `scripts/list_candidates.py`
- `scripts/promote_candidate.py`
- `scripts/explain_run.py`

Requirements:

- `promote_candidate.py --dry-run` shows the exact diff.
- `--apply --allow-degraded` is required for degraded promotion.
- Block-severity guards cannot be bypassed.
- Promotion is idempotent.
- `explain_run.py` is read-only.

## Telemetry Events

Add:

- `nightly.candidate_written`
- `nightly.guard_evaluated`
- `nightly.promotion_decision`
- `nightly.stranded_inventory`
- `nightly.phase_duration`
- `nightly.cancellation_after_candidate`
- `nightly.degraded_promoted`

## Success Criteria

This incident class is solved when:

1. A failed guard never destroys fresh inventory.
2. Every run has a candidate artifact or an explicit reason why no candidate exists.
3. Slack and GitHub Issues alert on stranded inventory.
4. Operators can promote a valid degraded candidate manually in under 5 minutes.
5. The live site never stays stale for days while CI silently produces data.
6. Guard policy distinguishes corruption from quality warnings.
7. Cancellation cannot silently erase a near-complete run.
8. Per-source freshness is visible and independent.

## Execution Order

```text
Phase 0 -> R1 -> R5 -> R6 -> R2 -> R3 -> R4 -> R7 -> R8 -> R9
```

Phase 0 stops the active stale-data bleeding. R1 makes failures recoverable. R5 and R6 make stranded inventory visible. R2-R4 make promotion decisions explicit. R7-R9 harden the long-term operating model.
