from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def _help(script: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, script, "--help"],
        cwd=REPO,
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_monitoring_scripts_import_without_pythonpath():
    for script in [
        "scripts/run_row_count_sentinel.py",
        "scripts/check_source_urls.py",
    ]:
        proc = _help(script)
        assert proc.returncode == 0, proc.stderr
        assert "usage:" in proc.stdout.lower()
