"""Root conftest — makes pulpo and automation importable from anywhere pytest runs."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


# PRD P2-2 — hermetic offline tests. .env values leak into a local
# `PULPO_OFFLINE=1 pytest -q` (DEEPSEEK_API_TOKEN triggers the LLM
# path, PULPO_SOURCES=kazu narrows source set and writes failure
# artifacts). CI installs cleanly and is unaffected. This session-scoped
# autouse fixture purges cost-bearing + source-narrowing env vars under
# `PULPO_OFFLINE=1` so the test run cannot accidentally make a paid API
# call or mutate tracked data.
#
# `PULPO_OFFLINE` itself is implicitly forced to "1" when the env var
# is missing, matching the existing convention (pytest is offline by
# default; live tests must explicitly opt in via `PULPO_OFFLINE=0`).
#
# When a test legitimately needs an LLM client, it should mock it
# explicitly (see tests/test_llm_enrichment.py for the pattern). The
# fixture catches accidental construction by raising a clear error.
_COST_BEARING_ENV = (
    "DEEPSEEK_API_TOKEN",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "RESEND_API_KEY",
    "CLERK_SECRET_KEY",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    # Source-narrowing — when PULPO_SOURCES is set, pulpo.cli reduces
    # the scraper set, which corrupts the rest of the test suite when
    # devs source `.env` for the dev pipeline and then run pytest.
    "PULPO_SOURCES",
)


@pytest.fixture(autouse=True, scope="session")
def _hermetic_offline_env():
    """Strip cost-bearing + source-narrowing env vars before any test
    runs. Restore them in teardown so an in-shell `set PULPO_OFFLINE=0`
    after pytest still sees the original values.
    """
    if os.environ.get("PULPO_OFFLINE", "1") != "1":
        # Live mode — caller explicitly opted in; don't strip anything.
        yield
        return
    # Ensure PULPO_OFFLINE itself is asserted as "1" for any code that
    # reads it before the fixture runs (some module imports do).
    os.environ.setdefault("PULPO_OFFLINE", "1")
    saved = {}
    for key in _COST_BEARING_ENV:
        if key in os.environ:
            saved[key] = os.environ.pop(key)
    try:
        yield
    finally:
        for key, value in saved.items():
            os.environ[key] = value


# ---------------------------------------------------------------------
# Guardrail: a test run must not mutate committed data files.
#
# Found 2026-08-09: `PULPO_OFFLINE=1 pytest -q` left three tracked files
# dirty — picker_excluded.json, scraper_coverage_history.jsonl,
# unmapped_beaches_history.jsonl. tests/test_first_seen.py drives the
# real pipeline, and while it patches `run.REPO` to a tmp dir, those
# writers re-derived their own paths from `__file__` and escaped the
# redirect. picker_excluded additionally had its isolation fixture
# below thrown away by that test's `sys.modules` purge.
#
# Nothing failed — the files just showed up modified afterwards, one
# careless `git add -A` away from a bogus data commit.
#
# This compares tracked files under web/data/ before and after the
# session and fails the run if any NEWLY changed. Pre-existing local
# dirt is ignored, so a dev mid-edit isn't punished.
# ---------------------------------------------------------------------
_WATCHED_DATA_DIR = "web/data"


def _dirty_data_files() -> set[str]:
    """Tracked-but-modified paths under web/data. Returns empty when git
    is unavailable so the guard degrades to a no-op in a non-git
    checkout rather than breaking the suite."""
    import subprocess
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--", _WATCHED_DATA_DIR],
            cwd=Path(__file__).resolve().parent,
            capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if out.returncode != 0:
        return set()
    dirty = set()
    for line in out.stdout.splitlines():
        # '??' is untracked — pipeline byproducts we deliberately don't
        # track are not the failure mode this guards against.
        if line and not line.startswith("??"):
            path = line[3:].strip()
            if path:
                dirty.add(path)
    return dirty


@pytest.fixture(autouse=True, scope="session")
def _no_committed_data_mutation():
    before = _dirty_data_files()
    yield
    newly = sorted(_dirty_data_files() - before)
    if newly:
        raise AssertionError(
            "Test run modified committed data files under "
            f"{_WATCHED_DATA_DIR}/:\n  " + "\n  ".join(newly)
            + "\n\nA test drove production code that wrote to the real repo "
              "instead of tmp_path. Give the writer a path derived from the "
              "caller's REPO (see the coverage_logger / unmapped_beach_detector "
              "calls in automation/run.py), or add an isolation fixture next "
              "to _isolate_picker_excluded_store below.\n"
              f"Restore with: git checkout -- {_WATCHED_DATA_DIR}"
        )


@pytest.fixture(autouse=True)
def _isolate_self_resolving_data_writers(tmp_path_factory):
    """Redirect the modules that build a `web/data` path from their own
    `__file__` (picker_excluded, aesthetic_vision) into a per-test tmp
    dir, so any test exercising the pipeline can't pollute the committed
    stores. Test-only file separation, no behavioral change for
    production code paths.

    Tests that purge `automation.*` from `sys.modules` defeat this — the
    re-imported module is a different object. Those call
    `tests._isolation.isolate_data_writers` again after their import;
    see that module for the list.
    """
    from tests._isolation import isolate_data_writers

    originals = {}
    try:
        from automation import picker_excluded as pe
        originals["pe"] = (pe, pe._STORE_PATH)
    except Exception:  # noqa: BLE001
        pass
    try:
        from automation import aesthetic_vision as av
        originals["av"] = (av, av._REPO_ROOT)
    except Exception:  # noqa: BLE001
        pass

    isolate_data_writers(tmp_path_factory.mktemp("data_writers"))
    try:
        yield
    finally:
        if "pe" in originals:
            mod, val = originals["pe"]
            mod._set_store_path_for_testing(val)
        if "av" in originals:
            mod, val = originals["av"]
            mod._REPO_ROOT = val
