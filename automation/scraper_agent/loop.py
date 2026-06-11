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

import json
from dataclasses import dataclass, field
from pathlib import Path
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


def _write_trace(trace_dir: Optional[Path], filename: str, payload: dict) -> None:
    """Persist one diagnostic artifact. Tracing must NEVER break the loop, so
    every failure here is swallowed."""
    if trace_dir is None:
        return
    try:
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / filename).write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001 — observability is best-effort
        pass


def _iter_payload(slug, kind, iteration, report, *, kept, cost, module_source, rationale):
    """The self-diagnosing record for one iteration: the module the agent
    wrote + exactly where the funnel dropped it (failures / error / a sample
    of the raw records). This is what made hand-written diagnostics
    unnecessary."""
    return {
        "slug": slug, "kind": kind, "iteration": iteration,
        "kept": kept, "cost_usd": round(cost, 6), "rationale": rationale,
        "fitness": report.fitness, "passed": report.passed, "ok": report.ok,
        "report": report.to_json(),       # counts, validation, failures, error, raw_sample
        "module_source": module_source,    # the exact scraper the agent produced
    }


def _finalize_trace(trace_dir, result, best_source) -> None:
    """At loop end, drop the best attempt's source + a run summary so the
    closest-to-passing scraper is one file away."""
    if trace_dir is None:
        return
    if best_source:
        _write_trace_text(trace_dir, "best-scraper.py", best_source)
    _write_trace(trace_dir, "summary.json", {
        "slug": result.slug, "kind": result.kind, "passed": result.passed,
        "stop_reason": result.stop_reason, "best_iteration": result.best_iteration,
        "iterations": result.iterations, "best_fitness": result.best.fitness,
        "best_report": result.best.to_json(), "budget": result.budget_summary,
    })


def _write_trace_text(trace_dir: Optional[Path], filename: str, text: str) -> None:
    if trace_dir is None:
        return
    try:
        trace_dir.mkdir(parents=True, exist_ok=True)
        (trace_dir / filename).write_text(text, encoding="utf-8")
    except Exception:  # noqa: BLE001 — observability is best-effort
        pass


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
    trace_dir: Optional[Path] = None,
) -> LoopResult:
    """Run the keep/discard loop. See module docstring for the contract.

    When ``trace_dir`` is given, every iteration's module source + funnel
    breakdown is persisted there (``iter-NN.json``), plus the best attempt
    (``best-scraper.py`` + ``summary.json``) — so a failed run is diagnosable
    by opening one directory instead of re-deriving the failure by hand."""

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
    baseline_source = sandbox.read(sandbox.scraper_path)
    _write_trace(trace_dir, "iter-00.json", _iter_payload(
        slug, kind, 0, best, kept=True, cost=0.0,
        module_source=baseline_source, rationale="baseline"))

    # If the starting state already clears the gate, there's nothing to do —
    # don't burn an iteration (or budget). Happens when a "repair" fires on a
    # source that self-healed, or onboarding re-runs on an already-good scraper.
    if best.passed:
        _log(f"[{slug}] baseline already passes — nothing to do")
        result = LoopResult(
            slug=slug, kind=kind, passed=True, best=best, best_iteration=0,
            iterations=0, stop_reason="passed", history=history,
            budget_summary=budget.summary(),
        )
        _finalize_trace(trace_dir, result, sandbox.read(sandbox.scraper_path))
        return result

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
        _write_trace(trace_dir, f"iter-{i:02d}.json", _iter_payload(
            slug, kind, i, report, kept=kept, cost=cost,
            module_source=proposed.content, rationale=proposed.rationale))
        _log(
            f"[{slug}] iter {i}: {report.summary()} "
            f"[{'kept' if kept else 'discarded'}] (${cost:.3f}; {budget.summary()})"
        )

        if report.passed and kept:
            stop_reason = "passed"
            break

    result = LoopResult(
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
    _finalize_trace(trace_dir, result, sandbox.read(sandbox.scraper_path))
    return result
