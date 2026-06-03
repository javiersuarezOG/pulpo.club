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


@pytest.fixture(autouse=True)
def _isolate_picker_excluded_store(tmp_path_factory):
    """Redirect web/data/picker_excluded.json into a per-test tmp file so
    any test that exercises automation/run.py's _score_candidates_cheap
    can't pollute the real on-disk store. Test-only file separation, no
    behavioral change for production code paths."""
    try:
        from automation import picker_excluded as pe
    except Exception:
        yield
        return
    original = pe._STORE_PATH
    tmp_dir = tmp_path_factory.mktemp("picker_excluded")
    pe._set_store_path_for_testing(tmp_dir / "picker_excluded.json")
    try:
        yield
    finally:
        pe._set_store_path_for_testing(original)
