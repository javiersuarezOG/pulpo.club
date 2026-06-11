from __future__ import annotations

import json
from pathlib import Path

from automation.run import _write_fresh_ranked_snapshot


WORKFLOW = Path(".github/workflows/pulpo-nightly.yml")


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
