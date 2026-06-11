"""Scraper-agent harness — the autoresearch loop applied to Pulpo scrapers.

The lesson from karpathy/autoresearch is that a *cheap, deterministic eval*
is what makes autonomous agent iteration possible (its ``val_bpb`` metric is
the whole trick). Pulpo already built that eval surface for human dev velocity
under the SCRAPER-FEEDBACK-CYCLE PRD — ``automation.scraper_lab.lab_run`` +
``automation.field_audit.acceptance_check`` — and never pointed an agent at it.

This package wraps that surface as an agent stopping condition:

  - :mod:`automation.scraper_agent.eval` — the fitness function
    (``evaluate_scraper`` -> :class:`EvalReport`). The ``val_bpb`` analogue.
  - :mod:`automation.scraper_agent.budget` — a hard Anthropic spend cap so a
    runaway loop can't burn credit.
  - :mod:`automation.scraper_agent.sandbox` — scope-limited, reversible edits
    so a loop never mutates anything outside ``pulpo/scrapers/<slug>.py`` (+
    its test) and can roll back a regression (keep/discard).
  - :mod:`automation.scraper_agent.loop` — the keep/discard iteration:
    propose edit -> apply in sandbox -> evaluate -> keep best, discard
    regressions -> stop on pass / max_iters / budget.

Train B (onboarding) builds on this first; Train A (repair active mode)
reuses it. See ``~/.claude/plans/can-this-improving-the-humble-shamir.md``.
"""
from __future__ import annotations

from automation.scraper_agent.budget import Budget, BudgetExceeded
from automation.scraper_agent.eval import EvalReport, evaluate_scraper
from automation.scraper_agent.loop import LoopResult, ProposedEdit, agent_loop
from automation.scraper_agent.sandbox import Sandbox, ScopeViolation

__all__ = [
    "Budget",
    "BudgetExceeded",
    "EvalReport",
    "evaluate_scraper",
    "LoopResult",
    "ProposedEdit",
    "agent_loop",
    "Sandbox",
    "ScopeViolation",
]
