#!/usr/bin/env python3
"""Classify a nightly run into one queryable outcome bucket.

"Red workflow" conflates two very different things: the data-quality gates
*correctly* refusing to ship bad/stale data (safe — the site keeps serving
last-good from main) versus the plumbing breaking (page someone). This step
writes a single classified verdict to ``web/data/nightly_outcome.json`` and
fires the ``nightly.outcome`` PostHog event so dashboards/alerts can treat the
buckets differently — alert on the plumbing buckets, not on a data-quality hold.

Buckets:
  committed                fresh data committed to main
  no_data_change           pipeline ran; nothing to commit (identical data)
  blocked_by_data_quality  a gate refused to ship — production PROTECTED, not broken
  pipeline_timeout         the job was cancelled (almost always the 240-min timeout)
  deploy_failed            data committed but the Vercel deploy step failed
  pa_failed                the PA (multi-country) step failed
  notification_failed      an alerting step failed
  pipeline_error           the SV pipeline step itself crashed
  unknown                  could not classify (should be rare — investigate)

Best-effort and never raises: telemetry must not fail the nightly. The local
JSON is always written so the verdict survives even if PostHog/Slack are down.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Step-name substrings that identify a *data-quality gate* step (vs. plumbing).
# Used to refine a job-level "failure" into its specific cause via the run's
# per-step conclusions (best-effort gh lookup).
_GATE_STEP_MARKERS = (
    "Count canary",
    "row-count delta gate",
    "Per-type canaries",
    "Data-quality canaries",
    "Photo storage canary",
    "Hires photo storage canary",
    "Hires pipeline health canary",
    "Hero variant canary",
    "Photo-contract truth canary",
)


def classify(
    job_status: str | None,
    committed: str | None,
    deploy_conclusion: str | None,
    failed_step: str | None = None,
) -> str:
    """Map the run signals to one bucket. Pure — unit-tested exhaustively.

    ``failed_step`` is the name of the earliest step that concluded ``failure``
    (best-effort); when absent we fall back to the job-level signal.
    """
    js = (job_status or "").strip().lower()
    committed = (committed or "").strip().lower()
    deploy = (deploy_conclusion or "").strip().lower()

    if js == "cancelled":
        return "pipeline_timeout"
    if deploy == "failure":
        # Data was committed (deploy only runs on committed==true) but the
        # publish step died — distinct from a data problem.
        return "deploy_failed"
    if committed == "true":
        return "committed"
    if js == "failure":
        if failed_step:
            if any(m in failed_step for m in _GATE_STEP_MARKERS):
                return "blocked_by_data_quality"
            if "Deploy to Vercel" in failed_step:
                return "deploy_failed"
            if "Run PA pipeline" in failed_step:
                return "pa_failed"
            if "Slack" in failed_step or "alert" in failed_step.lower():
                return "notification_failed"
            # "Run pipeline" and any install/checkout step → the run itself
            # broke before/at production. (A population-regression SystemExit
            # inside "Run pipeline" lands here too; the R2 guard matrix will
            # reclassify that as a warn — until then, failed_step is recorded
            # so a human can tell which it was.)
            return "pipeline_error"
        # No per-step detail available: the dominant pre-commit hard-fail is a
        # data-quality gate, and a gate block is the SAFE "protected production"
        # case. Default there; failed_step=null in the JSON flags it as unrefined.
        return "blocked_by_data_quality"
    if committed == "false":
        return "no_data_change"
    return "unknown"


def _earliest_failed_step(run_id: str, repo: str) -> str | None:
    """Best-effort name of the earliest step that concluded ``failure`` in this
    run, via the gh CLI. Returns None on any error (gh missing, API hiccup, run
    not found) so ``classify`` falls back to the job-level signal."""
    if not run_id:
        return None
    import subprocess

    try:
        cmd = ["gh", "run", "view", run_id, "--json", "jobs"]
        if repo:
            cmd[3:3] = ["--repo", repo]
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            return None
        failed: list[tuple[int, str]] = []
        for job in json.loads(out.stdout).get("jobs", []):
            for step in job.get("steps", []):
                if (step.get("conclusion") or "").lower() == "failure":
                    failed.append((int(step.get("number", 10**9)), step.get("name", "")))
        if not failed:
            return None
        failed.sort()
        return failed[0][1]
    except Exception:  # noqa: BLE001 — observability must never raise
        return None


def main() -> int:
    job_status = os.environ.get("JOB_STATUS")
    committed = os.environ.get("COMMITTED")
    deploy_conclusion = os.environ.get("DEPLOY_CONCLUSION")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}" if (repo and run_id) else None
    data_dir = Path(os.environ.get("PULPO_DATA_DIR", "web/data"))

    failed_step = None
    if (job_status or "").strip().lower() == "failure":
        failed_step = _earliest_failed_step(run_id, repo)

    outcome = classify(job_status, committed, deploy_conclusion, failed_step)

    record = {
        "outcome": outcome,
        "committed": committed,
        "deploy_conclusion": deploy_conclusion,
        "job_status": job_status,
        "failed_step": failed_step,
        "run_id": run_id or None,
        "run_url": run_url,
    }

    # Always write the local verdict FIRST — it must survive even if telemetry
    # is down (the "write nightly_outcome.json regardless of Slack" rule).
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "nightly_outcome.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8"
        )
    except Exception as e:  # noqa: BLE001
        print(f"[nightly_outcome] local write failed (non-fatal): {e!r}")

    # Best-effort PostHog event (silent no-op without POSTHOG_PROJECT_TOKEN).
    try:
        from automation.posthog_client import capture
        capture("nightly.outcome", record)
    except Exception as e:  # noqa: BLE001
        print(f"[nightly_outcome] posthog capture failed (non-fatal): {e!r}")

    print(
        f"[nightly_outcome] {outcome} (committed={committed} "
        f"deploy={deploy_conclusion} job={job_status} failed_step={failed_step})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
