"""Regression pin for the photo-pipeline budget guards.

The original audit flagged "Photo budget guards are advisory, not
blocking — budget_hit=True logs but doesn't stop new jobs." Tracing
the current code, the budget DOES break out of three separate loops:

  - _download_hero_photos Phase A (candidate scoring): line ~511
  - _download_hero_photos Phase C (aesthetic + write):  line ~634
  - _download_hires_photos:                              line ~880

…which means the audit was reading stale line numbers. The real gap
is that nothing pinned the break pattern — a future refactor that
unwraps the loop or moves the budget check could silently regress
the guard and the operator wouldn't know until a real budget
overrun started racking up cloud-photo egress.

This test grep-pins the pattern: every photo-loop in run.py that
references budget_s must also break out of the loop on overrun.
Specifically we anchor on the three known guard sites — if one moves,
the test surfaces the move with a clear message instead of letting
the regression ship.
"""
from __future__ import annotations
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
RUN_PY = REPO / "automation" / "run.py"


def test_photo_budget_guards_break_not_continue():
    """Every line that flips `budget_hit = True` must be followed within
    the same indented block by a `break` (not a `continue` or a log-only
    print). Catches the regression class the audit was worried about."""
    src = RUN_PY.read_text()
    lines = src.split("\n")

    # Find every `budget_hit = True` line and look ahead to verify the
    # next non-comment, non-print line at the SAME or DEEPER indent is
    # a `break`.
    hits: list[int] = []
    for i, ln in enumerate(lines):
        if re.match(r"^\s*budget_hit\s*=\s*True\s*$", ln):
            hits.append(i)

    # The audit baseline expected 3 budget guards across run.py
    # (hero Phase A, hero Phase C, hires). If a future PR adds a fourth
    # guard or removes one, the operator should consciously update the
    # test rather than accidentally regress.
    assert len(hits) == 3, (
        f"Expected 3 `budget_hit = True` sites in run.py "
        f"(hero Phase A + Phase C + hires); found {len(hits)}. "
        "If you intentionally added/removed a guard, update this "
        "assertion in the same PR so a future regression can't "
        "silently slip through."
    )

    for line_no in hits:
        # Look at the next 5 lines for a `break` at the same/deeper indent.
        # `break` MUST appear before we hit a dedented line or another
        # statement at the same indent that isn't `break`.
        guard_indent = len(lines[line_no]) - len(lines[line_no].lstrip())
        found_break = False
        for j in range(line_no + 1, min(line_no + 6, len(lines))):
            stripped = lines[j].strip()
            if not stripped or stripped.startswith("#"):
                continue
            j_indent = len(lines[j]) - len(lines[j].lstrip())
            if j_indent < guard_indent:
                break  # dedented out of the block; no `break` found
            if stripped == "break":
                found_break = True
                break
            # A non-break statement at the same indent that ISN'T
            # `break` means the guard's only effect is logging.
            if j_indent == guard_indent and not stripped.startswith(("print(", '"""')):
                break

        assert found_break, (
            f"automation/run.py line {line_no + 1}: `budget_hit = True` "
            "is not followed by `break` within the same loop. The "
            "budget guard is advisory — remaining iterations keep "
            "running. Fix by adding `break` immediately after the flag "
            "assignment (see hero Phase A at run.py:511 for the canonical "
            "shape)."
        )


def test_budget_env_vars_use_safe_helper():
    """Both photo budgets must read through _env_float (PR-2 of the
    reliability plan), not int()/float() on the raw env. Otherwise an
    empty-string secret from GH Actions crashes the pipeline before
    photos ever get processed — same bug class as #285."""
    src = RUN_PY.read_text()
    assert '_env_float("PULPO_PHOTO_BUDGET_S"' in src, (
        "PULPO_PHOTO_BUDGET_S must be read via _env_float so an empty "
        "secret doesn't crash photo download. See automation/_config.py."
    )
    assert '_env_float("PULPO_HIRES_BUDGET_S"' in src, (
        "PULPO_HIRES_BUDGET_S must be read via _env_float so an empty "
        "secret doesn't crash the hires backfill. See automation/_config.py."
    )
