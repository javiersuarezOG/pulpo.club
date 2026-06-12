from __future__ import annotations

import json
import re
from pathlib import Path

from automation.run import _write_fresh_ranked_snapshot
from pulpo.countries import data_filename


WORKFLOW = Path(".github/workflows/pulpo-nightly.yml")

# Unscoped legacy files the SV pipeline writes that the PA run dual-writes and
# therefore MUST snapshot+restore, or PA clobbers SV's served/gated data.
_REQUIRED_LEGACY_RESTORE = {
    "ranked.json",
    "ranked.list.json",
    "ranked.fresh.json",
    "last_updated.json",
    "featured.json",
    "photo_contract.json",
}


def _step_text(workflow: str, name: str) -> str:
    """The YAML body of a single named step (up to the next step header)."""
    after = workflow.split(f"- name: {name}", 1)[1]
    return after.split("\n      - name:", 1)[0]


def _pa_for_lists(pa_step: str) -> list[list[str]]:
    """Every `for f in <files>; do` file list inside the PA step (snapshot +
    restore), each as a token list."""
    lists: list[list[str]] = []
    for m in re.finditer(r"for f in (.+?);\s*do", pa_step, re.DOTALL):
        toks = m.group(1).replace("\\", " ").split()
        lists.append([t for t in toks if t and not t.startswith("#")])
    return lists


class _Listing:
    def __init__(self, payload: dict):
        self.payload = payload

    def to_dict(self) -> dict:
        return dict(self.payload)


def test_pa_legacy_restore_manifest_covers_fresh_snapshot():
    workflow = WORKFLOW.read_text()
    pa_step = workflow.split("- name: Run PA pipeline (multi-country scaffolding)", 1)[1].split(
        "- name: Refresh Weekly News Spotlight artifact", 1
    )[0]

    # The PA run dual-writes legacy filenames. If this file is omitted
    # from either loop, PA can overwrite SV's fresh-only candidate and
    # cause the pre-commit row-count gate to false-fail.
    assert pa_step.count("ranked.fresh.json") >= 2


def test_pipeline_writes_country_scoped_fresh_snapshot(tmp_path: Path):
    listings = [_Listing({"source": "remax", "source_id": "1"})]

    _write_fresh_ranked_snapshot(tmp_path, listings, active_cc="SV")

    legacy = json.loads((tmp_path / "ranked.fresh.json").read_text())
    scoped = json.loads((tmp_path / "ranked.fresh.SV.json").read_text())
    assert legacy == scoped == [{"source": "remax", "source_id": "1"}]


def test_nightly_queues_instead_of_cancelling_running_candidate():
    workflow = WORKFLOW.read_text()

    assert "cancel-in-progress: false" in workflow


def test_vercel_deploy_uses_archive_retry_and_pinned_cli():
    workflow = WORKFLOW.read_text()
    deploy_step = workflow.split("- name: Deploy to Vercel", 1)[1].split(
        "- name: Nightly summary", 1
    )[0]

    assert "npm install -g vercel@44.7.3" in deploy_step
    assert "vercel deploy --prod --yes --archive=tgz" in deploy_step
    assert "for attempt in 1 2" in deploy_step


# ── #2 producer/consumer contract for the fresh-candidate file ──────────────
# #830 made the row-count gate HARD-REQUIRE web/data/ranked.fresh.SV.json
# (fail-loud if missing). So if run.py stops writing it, or the gate /
# delta-decision drift to a different name, EVERY nightly fails at the gate.
# This ties the producer name (run.py via data_filename) to both consumers.

def test_producer_and_consumer_agree_on_fresh_sv_filename():
    fresh_sv = data_filename("ranked.fresh.json", "SV")
    assert fresh_sv == "ranked.fresh.SV.json"  # the name _write_fresh_ranked_snapshot emits

    wf = WORKFLOW.read_text()
    gate = _step_text(wf, "Per-source row-count delta gate")
    delta = _step_text(wf, "Delta decision (Slack runbook record)")

    # Both consumers must read the SAME file the producer writes.
    assert f"web/data/{fresh_sv}" in gate
    assert f"web/data/{fresh_sv}" in delta
    # The gate must NOT silently fall back to the legacy unscoped file that PA
    # or carry-forward can contaminate — #830 replaced that fallback with a
    # hard error. (Substring is safe: "ranked.fresh.SV.json" does not contain
    # "ranked.fresh.json".)
    assert "web/data/ranked.fresh.json" not in gate


# ── #3 generalized PA snapshot/restore drift guard ──────────────────────────

def test_pa_snapshot_and_restore_lists_are_identical():
    pa_step = _step_text(WORKFLOW.read_text(), "Run PA pipeline (multi-country scaffolding)")
    lists = _pa_for_lists(pa_step)
    assert len(lists) == 2, f"expected snapshot + restore loops, found {len(lists)}"
    snapshot, restore = lists
    # A file snapshotted but not restored (or vice-versa) is the exact drift
    # class that let PA clobber SV's fresh candidate. The two lists must match.
    assert set(snapshot) == set(restore), (
        f"PA snapshot/restore drift: "
        f"only-snapshot={set(snapshot) - set(restore)} "
        f"only-restore={set(restore) - set(snapshot)}"
    )


def test_pa_restore_covers_required_legacy_files():
    pa_step = _step_text(WORKFLOW.read_text(), "Run PA pipeline (multi-country scaffolding)")
    restore = set(_pa_for_lists(pa_step)[-1])
    missing = _REQUIRED_LEGACY_RESTORE - restore
    assert not missing, f"PA restore manifest missing required legacy files: {missing}"
