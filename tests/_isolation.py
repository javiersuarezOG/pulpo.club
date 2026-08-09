"""Redirect modules that resolve their own `web/data` path.

Most of the pipeline writes through paths derived from `automation.run.REPO`,
so a test that does `mock.patch.object(run_mod, "REPO", tmp_path)` is
hermetic. A few modules instead compute a repo root from their own
`__file__` at import time and never consult the caller:

    automation/picker_excluded.py   _REPO_ROOT -> picker_excluded.json
    automation/aesthetic_vision.py  _REPO_ROOT -> llm_vision_budget.jsonl

Patching `run.REPO` does not reach those, so any test that drives the
real pipeline appends to the **committed** copies in `web/data/`.

Worse, the three tests that drive the pipeline all purge
`automation.*` from `sys.modules` first (to make `PULPO_OFFLINE` take
effect on a fresh import):

    tests/test_first_seen.py
    tests/test_pipeline_smoke.py
    tests/test_scrape_concurrency.py

That purge throws away the module objects conftest's autouse fixture
had already patched, so the re-import silently restores the real paths.
Hence this helper: call it *after* the purge, from inside the same
`REPO`-patched block.

The `_no_committed_data_mutation` session guard in conftest.py is the
backstop — if a new writer or a new purging test escapes, the run fails
and names the file rather than leaving a dirty tree for `git add -A` to
sweep up.
"""
from __future__ import annotations

from pathlib import Path


def isolate_data_writers(tmp_root: Path) -> None:
    """Point the self-resolving writers at ``tmp_root`` instead of the repo.

    Idempotent and safe to call repeatedly (each purge/re-import cycle
    needs its own call). Import failures are swallowed: a test that
    doesn't pull in these modules shouldn't break on their absence, and
    the session guard catches anything this misses.
    """
    data_dir = tmp_root / "web" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        from automation import picker_excluded as _pe
        _pe._set_store_path_for_testing(data_dir / "picker_excluded.json")
    except Exception:  # noqa: BLE001 - best-effort isolation
        pass

    try:
        from automation import aesthetic_vision as _av
        # _budget_log_path() builds <_REPO_ROOT>/web/data/llm_vision_budget.jsonl
        _av._REPO_ROOT = tmp_root
    except Exception:  # noqa: BLE001 - best-effort isolation
        pass
