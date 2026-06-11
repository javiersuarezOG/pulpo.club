"""The keep/discard iteration — Pulpo's port of the autoresearch loop.

``agent_loop`` is the pure orchestrator: *propose an edit → apply it in the
sandbox → evaluate → keep it if fitness improved, else roll back → repeat*
until the candidate passes the acceptance gate, the iteration cap is hit, the
budget is exhausted, or the agent gives up. It is deliberately decoupled from
*how* edits are proposed and *how* they are evaluated:

- ``propose`` is a caller-supplied callable. Train B (onboarding) and Train A
  (repair) each supply their own — the real ones call Claude via the Anthropic
  SDK; tests supply a deterministic stub. This is what makes the loop testable
  with zero network and zero spend.
- ``evaluate`` is also caller-supplied. It closes over the live-vs-cached
  decision the plan calls the "prepare once, iterate fast" split: onboarding
  fetches live once then evaluates parsing changes against cached raw HTML;
  repair must evaluate ``live=True`` every time (a stale fixture would let a
  broken scraper pass). The loop doesn't care — it just compares the
  ``EvalReport.fitness`` each call returns.

The loop never commits. On return, the sandbox's best-known-good content is on
disk; the caller inspects ``LoopResult.passed`` and decides whether to
``sandbox.commit()`` (persist for a PR) or let the context manager restore the
original.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from automation.scraper_agent.budget import Budget, BudgetExceeded
from automation.scraper_agent.eval import EvalReport
from automation.scraper_agent.sandbox import Sandbox


@dataclass
class ProposedEdit:
    """One candidate edit from the agent. ``content`` is the full new scraper
    source; ``usage`` (an SDK usage block or dict) is billed to the budget."""

    content: str
    rationale: str = ""
    test_content: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[object] = None


@dataclass
class IterationRecord:
    iteration: int
    report: EvalReport
    kept: bool
    cost_usd: float
    rationale: str = ""


@dataclass
class LoopContext:
    """Everything ``propose`` needs to build the next prompt."""

    slug: str
    kind: str                     # "onboard" | "repair"
    iteration: int
    current_source: Optional[str]
    best: EvalReport
    last: EvalReport
    history: list[IterationRecord]


@dataclass
class LoopResult:
    slug: str
    kind: str
    passed: bool
    best: EvalReport
    best_iteration: int
    iterations: int               # number of propose/evaluate rounds run
    stop_reason: str              # passed | max_iters | budget | agent_gave_up | propose_error
    history: list[IterationRecord] = field(default_factory=list)
    budget_summary: str = ""

    def summary(self) -> str:
        return (
            f"{self.slug} [{self.kind}] {self.stop_reason} — "
            f"passed={self.passed} best_fitness={self.best.fitness:.3f} "
            f"@iter {self.best_iteration} over {self.iterations} round(s); "
            f"{self.budget_summary}"
        )


ProposeFn = Callable[[LoopContext], Optional[ProposedEdit]]
EvaluateFn = Callable[[], EvalReport]
LogFn = Callable[[str], None]


def _keep(candidate: EvalReport, best: EvalReport) -> bool:
    """Keep the candidate when it improves fitness, or when it newly passes the
    acceptance gate (a passing candidate is always worth keeping, even on the
    rare fitness tie)."""
    if candidate.passed and not best.passed:
        return True
    return candidate.fitness > best.fitness


def agent_loop(
    slug: str,
    *,
    propose: ProposeFn,
    evaluate: EvaluateFn,
    sandbox: Sandbox,
    budget: Budget,
    kind: str = "onboard",
    max_iters: int = 6,
    baseline: Optional[EvalReport] = None,
    iteration_headroom_usd: float = 0.0,
    log: Optional[LogFn] = None,
) -> LoopResult:
    """Run the keep/discard loop. See module docstring for the contract."""

    def _log(msg: str) -> None:
        if log is not None:
            log(msg)

    # Baseline: score the starting state so the first proposal has something to
    # beat. For onboarding the scraper may not exist yet (fitness 0); for repair
    # it's the broken scraper (also low). Either way, not passed → we iterate.
    best = baseline if baseline is not None else evaluate()
    best_iteration = 0
    history: list[IterationRecord] = [
        IterationRecord(iteration=0, report=best, kept=True, cost_usd=0.0,
                        rationale="baseline")
    ]
    _log(f"[{slug}] baseline: {best.summary()}")

    stop_reason = "max_iters"
    last = best

    for i in range(1, max_iters + 1):
        try:
            budget.check(headroom_usd=iteration_headroom_usd)
        except BudgetExceeded as e:
            stop_reason = "budget"
            _log(f"[{slug}] stopping: {e}")
            break

        ctx = LoopContext(
            slug=slug,
            kind=kind,
            iteration=i,
            current_source=sandbox.read(sandbox.scraper_path),
            best=best,
            last=last,
            history=history,
        )

        try:
            proposed = propose(ctx)
        except Exception as e:  # noqa: BLE001 — a broken propose ends the loop, not the process
            stop_reason = "propose_error"
            _log(f"[{slug}] propose() raised on iter {i}: {e!r}")
            break

        if proposed is None:
            stop_reason = "agent_gave_up"
            _log(f"[{slug}] agent declined to propose on iter {i}")
            break

        cost = 0.0
        if proposed.usage is not None:
            cost = budget.charge_usage(proposed.model or "claude-opus-4-8", proposed.usage)

        sandbox.apply(sandbox.scraper_path, proposed.content)
        if proposed.test_content is not None:
            sandbox.apply(sandbox.test_path, proposed.test_content)

        report = evaluate()
        last = report
        kept = _keep(report, best)
        if kept:
            best = report
            best_iteration = i
            sandbox.checkpoint()
        else:
            sandbox.rollback()

        history.append(
            IterationRecord(iteration=i, report=report, kept=kept, cost_usd=cost,
                            rationale=proposed.rationale)
        )
        _log(
            f"[{slug}] iter {i}: {report.summary()} "
            f"[{'kept' if kept else 'discarded'}] (${cost:.3f}; {budget.summary()})"
        )

        if report.passed and kept:
            stop_reason = "passed"
            break

    return LoopResult(
        slug=slug,
        kind=kind,
        passed=best.passed,
        best=best,
        best_iteration=best_iteration,
        iterations=len(history) - 1,
        stop_reason=stop_reason,
        history=history,
        budget_summary=budget.summary(),
    )
