"""Contract test: every cross-run state file automation/run.py reads
back must be staged by the nightly's commit step.

Why this exists
---------------
On 2026-08-08 the browse table showed "0d" in the DAYS column for
1533 of 1558 production listings, and the "New" badge fired on all of
them. Root cause was NOT the age logic — ``run.py``'s first-seen block
is idempotent and correct. It was that ``web/data/listings_history.json``
(the ``{"<source>|<source_id>": iso}`` sidecar it writes at the end of a
run and reads back at the start of the next) was never added to the
nightly's ``git add`` list. Every run therefore checked out a fresh repo,
found no file, treated all ~1500 listings as first-seen-today, and
stamped ``first_seen_at = <this run>``. ``days_listed`` derives from that
timestamp, so it collapsed to 0 catalog-wide.

``web/data/listings_ledger.json`` had the same gap with a quieter blast
radius: ``PULPO_RANKER_DROP_STALE=1`` needs >=3 consecutive missing
nightlies of accumulated ledger state before it drops anything, and the
ledger reset every night, so the stale filter was a permanent no-op.

The failure mode is invisible to every other guardrail. The pipeline
exits 0, the canaries pass, the data PR merges, the file is written to
the runner's disk — and then the runner is destroyed. Nothing asserts
that a file written for the *next* run actually survives to it.

Contract
--------
A file is "cross-run state" if run.py both writes it AND reads it back
to seed the next run's behaviour. For each such file, the nightly's
commit step must contain a ``git add`` line naming it.

Adding a new cross-run sidecar means two edits in the same PR: the
read/write in run.py, and the ``git add`` in pulpo-nightly.yml. This
test failing on a run.py-only edit is the guardrail working.
"""
from __future__ import annotations

import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "pulpo-nightly.yml"
RUN_PY = REPO / "automation" / "run.py"

# Files run.py writes at the end of a run and reads back at the start of
# the next. Absence from the commit step means the read is guaranteed to
# miss and the state silently resets every night.
#
# Keep this list in sync when adding a new sidecar. The rule of thumb:
# if run.py does `path.exists()` / `path.read_text()` on it before
# writing it, it belongs here.
CROSS_RUN_STATE = [
    "web/data/listings_history.json",   # first_seen_at -> days_listed
    "web/data/listings_ledger.json",    # existence_status -> stale filter
    "web/data/prices_history.json",     # price history -> is_repriced
]


def _workflow_text() -> str:
    if not WORKFLOW.exists():
        pytest.skip(f"{WORKFLOW} not present")
    return WORKFLOW.read_text(encoding="utf-8")


@pytest.mark.parametrize("rel_path", CROSS_RUN_STATE)
def test_cross_run_state_is_staged(rel_path: str) -> None:
    text = _workflow_text()
    # Match a `git add` naming the file, tolerating the surrounding
    # `2>/dev/null || true` best-effort suffix and multi-path adds.
    pattern = re.compile(
        r"^\s*git add\b[^\n]*(?<![\w/.-])" + re.escape(rel_path) + r"(?![\w/.-])",
        re.MULTILINE,
    )
    assert pattern.search(text), (
        f"{rel_path} is cross-run state that run.py reads back, but no "
        f"`git add` line in pulpo-nightly.yml stages it. Without the add, "
        f"the file is written to the runner's disk and destroyed with the "
        f"runner — the next nightly starts from empty and the state resets. "
        f"This is the 2026-08-08 days_listed=0 bug. Add:\n"
        f"    git add {rel_path} 2>/dev/null || true"
    )


@pytest.mark.parametrize("rel_path", CROSS_RUN_STATE)
def test_cross_run_state_is_actually_read_back(rel_path: str) -> None:
    """Guards the other direction: the list above should not accumulate
    files that stopped being cross-run state. A file staged but never
    read back is dead weight in the data commit, not a persistence bug —
    drop it from CROSS_RUN_STATE rather than leaving a stale entry that
    makes the contract look broader than it is."""
    if not RUN_PY.exists():
        pytest.skip(f"{RUN_PY} not present")
    basename = rel_path.rsplit("/", 1)[-1]
    assert basename in RUN_PY.read_text(encoding="utf-8"), (
        f"{rel_path} is listed as cross-run state but automation/run.py "
        f"never mentions {basename}. Either the read/write moved to "
        f"another module (update this test's RUN_PY target) or the file "
        f"is no longer cross-run state (remove it from CROSS_RUN_STATE)."
    )
