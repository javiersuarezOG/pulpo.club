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

Original fix (PR a527237): `int(os.environ.get(name) or "5")`.
PR-2 of the reliability plan: routed through `automation._config.env_int`,
which centralizes the empty-string and whitespace-tolerance contract
across every parser in the pipeline. See `tests/test_config_env.py`
for the helper's behavior; this file remains as a callsite anchor so
the run.py path doesn't silently regress to the legacy crash-prone
pattern.
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation._config import env_int   # noqa: E402


def test_unset_env_var_defaults_to_5(monkeypatch):
    monkeypatch.delenv("LLM_VISION_TOP_PCT", raising=False)
    assert env_int("LLM_VISION_TOP_PCT", 5) == 5


def test_empty_env_var_defaults_to_5(monkeypatch):
    """The bug case — GH Actions passes an empty string when the secret is unset."""
    monkeypatch.setenv("LLM_VISION_TOP_PCT", "")
    assert env_int("LLM_VISION_TOP_PCT", 5) == 5


def test_whitespace_env_var_defaults_to_5(monkeypatch):
    """The PR-2 helper deliberately tolerates whitespace too — same-shape bug
    as the empty-string case (operator typo, GH templating glitch, etc.).
    The original test asserted ValueError here as a deliberate boundary;
    the helper now treats whitespace as 'unset' for symmetry. Documented
    in automation/_config.py."""
    monkeypatch.setenv("LLM_VISION_TOP_PCT", "   ")
    assert env_int("LLM_VISION_TOP_PCT", 5) == 5


def test_explicit_value_is_honored(monkeypatch):
    monkeypatch.setenv("LLM_VISION_TOP_PCT", "12")
    assert env_int("LLM_VISION_TOP_PCT", 5) == 12


def test_callsite_matches_helper():
    """Read run.py and assert the LLM_VISION_TOP_PCT callsite is wired
    through the helper. Guards against an accidental revert to
    `int(os.environ.get(...))`."""
    src = (REPO / "automation" / "run.py").read_text()
    assert '_env_int("LLM_VISION_TOP_PCT", 5)' in src, (
        "run.py must use `_env_int(\"LLM_VISION_TOP_PCT\", 5)` (or equivalent) "
        "so empty / whitespace / unparseable values fall through to the default "
        "instead of crashing the nightly. See automation/_config.py."
    )
