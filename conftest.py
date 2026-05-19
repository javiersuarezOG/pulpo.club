"""Root conftest — makes pulpo and automation importable from anywhere pytest runs."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))


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
