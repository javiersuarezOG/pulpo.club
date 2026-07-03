"""Contract test: backend KPI dashboard MIN_REAL_LISTINGS == frontend HomeShelf.jsx MIN_REAL_LISTINGS.

The KPI dashboard reports ``renders_on_homepage = (visible_count >= MIN_REAL_LISTINGS)``.
The FE hides shelves with fewer than ``MIN_REAL_LISTINGS`` qualifying listings.
When the two drift, the dashboard reports green for a shelf the user can never see —
the exact failure that landed on main pre-#724 and that this test now prevents.

The check is a grep, not a JSX parser, on purpose: it is cheaper, faster, and the
constant declaration in HomeShelf.jsx is stable. If the FE refactor moves the
constant elsewhere, update the regex below.
"""
from __future__ import annotations

import re
from pathlib import Path

from automation.kpi_dashboard import MIN_REAL_LISTINGS as BACKEND_MIN


REPO_ROOT = Path(__file__).resolve().parents[1]
HOMESHELF = REPO_ROOT / "web" / "app" / "home" / "HomeShelf.jsx"

# Matches: `const MIN_REAL_LISTINGS = 10;` (allow whitespace and trailing comment).
_FE_RE = re.compile(r"const\s+MIN_REAL_LISTINGS\s*=\s*(\d+)\s*;")


def _frontend_value() -> int:
    text = HOMESHELF.read_text(encoding="utf-8")
    matches = _FE_RE.findall(text)
    assert matches, (
        f"Could not find `const MIN_REAL_LISTINGS = N;` in {HOMESHELF.relative_to(REPO_ROOT)}. "
        "If the constant was renamed or moved, update _FE_RE in this test."
    )
    assert len(matches) == 1, (
        f"Multiple MIN_REAL_LISTINGS declarations in {HOMESHELF.relative_to(REPO_ROOT)}: {matches}"
    )
    return int(matches[0])


def test_backend_kpi_min_matches_frontend_homeshelf():
    fe = _frontend_value()
    assert BACKEND_MIN == fe, (
        f"automation/kpi_dashboard.py::MIN_REAL_LISTINGS={BACKEND_MIN} but "
        f"web/app/home/HomeShelf.jsx::MIN_REAL_LISTINGS={fe}. "
        "Update both sides together — the dashboard reports a shelf as rendering "
        "whenever count >= backend value; the UI hides it when count < frontend value."
    )
