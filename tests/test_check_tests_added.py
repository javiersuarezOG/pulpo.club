"""Tests for .github/scripts/check_tests_added.py.

The audit flagged the legacy bypass as too quiet: the workflow-level
`if: !contains(labels, 'no-test-required')` skipped the whole job, so
a missing-tests PR with the label gave reviewers zero signal about
what was waved through.

PR-7 of the reliability plan moves the gate into the script. These
tests pin the new contract:

  - PR with missing tests AND no bypass label  → exit 1 (block merge)
  - PR with missing tests AND  bypass label    → exit 0 + ::warning::
    annotation listing every skipped file
  - PR with no missing tests AND no label       → exit 0 (silent)
  - PR with no missing tests AND  label         → exit 0 + ::notice::
    flagging the unused label (clean-up hint)
"""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / ".github" / "scripts" / "check_tests_added.py"


def _run(diff_lines: list[str], *, bypass: bool = False, env_extra: dict | None = None):
    """Run the script in a subprocess so we exercise the real exit code +
    stdout shape (CI sees these literally)."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as tmp:
        tmp.write("\n".join(diff_lines) + "\n")
        diff_path = tmp.name
    env = {"PATH": "/usr/bin:/bin"}
    if bypass:
        env["PULPO_TESTS_BYPASS_ACTIVE"] = "1"
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), diff_path],
        capture_output=True, text=True, env=env,
    )
    return proc


def test_no_added_files_passes_silently():
    """Empty diff (e.g. docs-only PR) — exit 0, no noise."""
    proc = _run([])
    assert proc.returncode == 0
    assert "0 added files" in proc.stdout


def test_added_agent_without_test_fails():
    """The core contract: a new scraper without a paired test fails the
    check. This is the regression-prevention path PR-7 keeps live."""
    proc = _run(["pulpo/scrapers/new_source.py"])
    assert proc.returncode == 1
    assert "Missing test files" in proc.stdout
    assert "new_source.py" in proc.stdout
    assert "tests/scrapers/test_new_source.py" in proc.stdout


def test_added_agent_with_paired_test_passes():
    """When the PR includes BOTH the new agent and its test, the script
    must pass cleanly without flagging the agent as missing."""
    proc = _run([
        "pulpo/scrapers/new_source.py",
        "tests/scrapers/test_new_source.py",
    ])
    assert proc.returncode == 0
    assert "all agents have tests" in proc.stdout


def test_bypass_label_with_missing_test_passes_but_warns():
    """PR-7 audit fix — bypass still works but is LOUD. Old behavior
    silently skipped the whole job; new behavior exits 0 AND emits a
    GitHub Actions ::warning:: annotation so the reviewer sees what
    was waved through."""
    proc = _run(["pulpo/scrapers/new_source.py"], bypass=True)
    assert proc.returncode == 0, "bypass label must still allow merge"
    assert "::warning::TEST COVERAGE BYPASS ACTIVE" in proc.stdout
    assert "new_source.py" in proc.stdout, (
        "warning must list which file was waved through"
    )


def test_bypass_label_with_no_missing_tests_flags_dead_label():
    """If the bypass label is on but the script would have passed on its
    own merit, surface a ::notice:: pointing out the label is unused.
    A stale label on a clean PR is misleading — reviewers might assume
    something was skipped when nothing was."""
    proc = _run(
        [
            "pulpo/scrapers/new_source.py",
            "tests/scrapers/test_new_source.py",
        ],
        bypass=True,
    )
    assert proc.returncode == 0
    assert "::notice::" in proc.stdout
    assert "bypass is unnecessary" in proc.stdout


def test_non_python_added_file_is_ignored():
    """Data + config files don't need test coverage — they're tested
    indirectly by the consumers they configure."""
    proc = _run(["pulpo/scrapers/some_config.json"])
    assert proc.returncode == 0
    assert "Missing test files" not in proc.stdout


def test_init_files_are_skipped():
    """__init__.py is boilerplate — never needs a dedicated test."""
    proc = _run(["pulpo/scrapers/__init__.py"])
    assert proc.returncode == 0
