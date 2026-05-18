"""
Regression test for run 26060732778 (2026-05-18) failure:

    File "automation/run.py", line 507, in _download_hero_photos
        top_pct = int(os.environ.get("LLM_VISION_TOP_PCT", "5"))
    ValueError: invalid literal for int() with base 10: ''

GH Actions resolves `${{ secrets.LLM_VISION_TOP_PCT }}` to the empty
string when the secret is unset. `os.environ.get(..., "5")` returns ""
(not the default) because the variable IS set, just to "". int("")
raises ValueError → pipeline aborts after the LLM enrichment step,
right before photo download, blocking the data-PR commit.

Fix: use `os.environ.get(name) or "5"` so both unset AND empty-string
fall through to the default.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _resolve_top_pct() -> int:
    """Mirrors the run.py snippet under test verbatim."""
    return int(os.environ.get("LLM_VISION_TOP_PCT") or "5")


def test_unset_env_var_defaults_to_5(monkeypatch):
    monkeypatch.delenv("LLM_VISION_TOP_PCT", raising=False)
    assert _resolve_top_pct() == 5


def test_empty_env_var_defaults_to_5(monkeypatch):
    """The bug case — GH Actions passes an empty string when the secret is unset."""
    monkeypatch.setenv("LLM_VISION_TOP_PCT", "")
    assert _resolve_top_pct() == 5


def test_whitespace_env_var_still_raises():
    """Whitespace-only env is operator error — should NOT silently default.
    Documents intent; if you want to also tolerate whitespace, change
    the fix to `(os.environ.get(...) or "").strip() or "5"`."""
    # We do NOT add strip() in the fix. Keep this test red-on-change
    # so a future contributor is forced to make a deliberate call.
    os.environ["LLM_VISION_TOP_PCT"] = "   "
    try:
        with pytest.raises(ValueError):
            _resolve_top_pct()
    finally:
        del os.environ["LLM_VISION_TOP_PCT"]


def test_explicit_value_is_honored(monkeypatch):
    monkeypatch.setenv("LLM_VISION_TOP_PCT", "12")
    assert _resolve_top_pct() == 12


def test_callsite_matches_fix():
    """Read the actual source of run.py and assert the fixed pattern is in place.
    Guards against accidental revert."""
    src = (REPO / "automation" / "run.py").read_text()
    # The fix uses `or "5"` rather than `, "5"` as the int() default.
    assert 'int(os.environ.get("LLM_VISION_TOP_PCT") or "5")' in src, (
        "run.py:507 must use `int(os.environ.get(...) or '5')` to tolerate "
        "the empty-string env GH Actions passes when the secret is unset."
    )
