"""Wiring test for scripts/run_delta_decision.py — the consumer that
turns automation/delta_decision into a live nightly Slack step.

Covers: (1) the script self-bootstraps sys.path (runs without
PYTHONPATH), (2) it classifies a zero-yield source as source_failed and
exits 0 in --dry-run without posting.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "run_delta_decision.py"


def test_script_runs_without_pythonpath():
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    res = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr


def test_dry_run_classifies_zero_yield_and_does_not_post(tmp_path: Path):
    data_dir = tmp_path / "web" / "data"
    data_dir.mkdir(parents=True)

    # Candidate fresh snapshot: citymax_sc zero-yielded; remax grew so the
    # platform total stays flat (masks the total canary).
    fresh = data_dir / "ranked.fresh.json"
    fresh.write_text(json.dumps([{"source": "remax", "source_id": str(n)} for n in range(444)]))

    # 7-tick history where citymax_sc was healthy at 162.
    hist = data_dir / "row_count_history.jsonl"
    with hist.open("w") as f:
        for i in range(7):
            for src, c in [("citymax_sc", 162), ("remax", 282), ("__total__", 444)]:
                f.write(json.dumps({
                    "tick_at": f"2026-06-0{i+1}T00:00:00+00:00",
                    "country": "sv", "source": src, "count": c,
                }) + "\n")

    # Health says citymax_sc is red (failed scrape) → source_failed bucket.
    health = data_dir / "source_health_history.jsonl"
    health.write_text(
        json.dumps({"ts": "2026-06-08T06:00:00+00:00", "source": "citymax_sc",
                    "status": "red", "scraped": 0, "kept": 0}) + "\n"
        + json.dumps({"ts": "2026-06-08T06:00:00+00:00", "source": "remax",
                      "status": "green", "scraped": 444, "kept": 444}) + "\n"
    )

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["SLACK_WEBHOOK_URL"] = "https://example.invalid/hook"  # must NOT be hit in dry-run
    res = subprocess.run(
        [sys.executable, str(SCRIPT),
         "--fresh-ranked", str(fresh),
         "--sv-ranked", str(fresh),
         "--history-path", str(hist),
         "--data-dir", str(data_dir),
         "--dry-run"],
        cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    assert "citymax_sc" in res.stdout
    assert "source_failed" in res.stdout
    assert "--dry-run: not posting" in res.stdout
