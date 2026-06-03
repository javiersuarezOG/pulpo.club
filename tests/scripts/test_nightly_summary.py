from __future__ import annotations

from scripts import nightly_summary


def test_local_mode_uses_health_endpoint_without_false_no_refresh(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.delenv("NIGHTLY_RUN_URL", raising=False)
    monkeypatch.delenv("NIGHTLY_COMMITTED", raising=False)
    monkeypatch.delenv("NIGHTLY_DEPLOY_OUTCOME", raising=False)
    monkeypatch.setattr(
        nightly_summary,
        "fetch_remote_health",
        lambda: ({"last_updated": "2026-06-03T02:00:00Z", "listing_count": 959}, None),
    )

    assert nightly_summary.main(["--data-dir", str(tmp_path)]) == 0

    out = capsys.readouterr().out
    assert "[mode=local]" in out
    assert "Health endpoint: " in out
    assert "2026-06-03T02:00:00Z" in out
    assert "will NOT refresh" not in out


def test_workflow_mode_keeps_env_driven_commit_story(tmp_path):
    summary = nightly_summary.format_summary(
        listing_count=959,
        pipeline_ts="2026-06-03T02:00:00Z",
        rows_by_src={},
        committed="true",
        deploy_outcome="success",
        run_url="https://github.com/example/runs/1",
        today_iso="2026-06-03",
        mode="workflow",
    )

    assert "[mode=local]" not in summary
    assert "Commit:  ✓ COMMITTED" in summary
    assert "pulpo.club will show: 2026-06-03T02:00:00Z" in summary
