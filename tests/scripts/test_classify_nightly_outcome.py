"""Unit tests for scripts/classify_nightly_outcome.py::classify.

Pure-function coverage of every outcome bucket. The gh-API refinement
(``_earliest_failed_step``) is best-effort glue and intentionally not unit
tested here — ``classify`` is exercised with the ``failed_step`` it would
return.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from classify_nightly_outcome import classify  # noqa: E402


@pytest.mark.parametrize(
    "job,committed,deploy,failed,expected",
    [
        # Happy paths
        ("success", "true", "success", None, "committed"),
        ("success", "false", "skipped", None, "no_data_change"),
        # Cancellation (timeout) wins over everything
        ("cancelled", "", "skipped", None, "pipeline_timeout"),
        ("cancelled", "true", "success", None, "pipeline_timeout"),
        # Committed-but-deploy-died is its own bucket, not a data problem
        ("failure", "true", "failure", None, "deploy_failed"),
        # Gate blocks — production protected, refined by failed_step
        ("failure", "", "skipped", "Per-source row-count delta gate", "blocked_by_data_quality"),
        ("failure", "", "skipped", "Data-quality canaries (floor + classification confidence)", "blocked_by_data_quality"),
        ("failure", "", "skipped", "Count canary (floor + ceiling)", "blocked_by_data_quality"),
        ("failure", "", "skipped", "Photo-contract truth canary (committed SV state)", "blocked_by_data_quality"),
        # Plumbing failures
        ("failure", "", "skipped", "Run pipeline", "pipeline_error"),
        ("failure", "", "skipped", "Install dependencies", "pipeline_error"),
        ("failure", "", "skipped", "Run PA pipeline (multi-country scaffolding)", "pa_failed"),
        ("failure", "", "skipped", "Slack on failure or cancellation", "notification_failed"),
        ("failure", "", "skipped", "Source-health Slack alert (pre-canary)", "notification_failed"),
        # Job failed but no per-step detail → safe default (a gate is the
        # dominant pre-commit hard-fail)
        ("failure", "", "skipped", None, "blocked_by_data_quality"),
        # Unclassifiable
        ("", "", "", None, "unknown"),
        (None, None, None, None, "unknown"),
    ],
)
def test_classify(job, committed, deploy, failed, expected):
    assert classify(job, committed, deploy, failed) == expected


def test_buckets_are_stable_strings():
    # Lock the bucket vocabulary — dashboards/alerts query these literals.
    seen = {
        classify("success", "true", "success", None),
        classify("success", "false", "skipped", None),
        classify("cancelled", "", "", None),
        classify("failure", "true", "failure", None),
        classify("failure", "", "skipped", "Data-quality canaries"),
        classify("failure", "", "skipped", "Run pipeline"),
        classify("failure", "", "skipped", "Run PA pipeline"),
        classify("failure", "", "skipped", "Slack alert"),
        classify("", "", "", None),
    }
    assert seen == {
        "committed", "no_data_change", "pipeline_timeout", "deploy_failed",
        "blocked_by_data_quality", "pipeline_error", "pa_failed",
        "notification_failed", "unknown",
    }
