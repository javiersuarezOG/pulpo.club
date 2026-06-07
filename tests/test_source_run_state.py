"""Tests for source attempt/success helpers."""
from __future__ import annotations

from automation.source_run_state import succeeded_sources_for_ledger


def test_succeeded_sources_only_include_attempted_sources():
    succeeded = succeeded_sources_for_ledger(
        attempted_sources=["nexo"],
        source_errors={},
    )
    assert succeeded == {"nexo"}


def test_succeeded_sources_exclude_failed_attempts():
    succeeded = succeeded_sources_for_ledger(
        attempted_sources=["nexo", "remax"],
        source_errors={"nexo": "HTTP 403"},
    )
    assert succeeded == {"remax"}


def test_succeeded_sources_strip_empty_values():
    succeeded = succeeded_sources_for_ledger(
        attempted_sources=[" nexo ", "", "  "],
        source_errors={},
    )
    assert succeeded == {"nexo"}
