"""Tests for the scraper-agent harness (automation/scraper_agent/*).

Deterministic and offline: the fitness function runs against a scraper's
committed offline fixtures (no network), and the loop is driven by a stubbed
``propose`` + scripted ``evaluate`` so it exercises the keep/discard
orchestration with zero spend.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from automation.scraper_agent import (
    Budget,
    BudgetExceeded,
    EvalReport,
    ProposedEdit,
    Sandbox,
    ScopeViolation,
    agent_loop,
    evaluate_scraper,
)
from automation.scraper_agent.eval import _fitness
from automation.scraper_agent.sandbox import reload_scraper

REPO = Path(__file__).resolve().parents[1]


# ── eval / fitness ───────────────────────────────────────────────────

def test_evaluate_scraper_offline_real_source():
    r = evaluate_scraper("goodlife", live=False)
    assert r.ok
    assert r.passed
    assert r.ranked_count > 0
    # gate fully met (1.0) + a bounded coverage bonus < 0.1
    assert 1.0 < r.fitness < 1.1
    assert set(r.hard_gate_pct) == {"property_type", "location", "price_usd"}


def test_evaluate_scraper_missing_module_is_zero_not_crash():
    r = evaluate_scraper("does_not_exist_zzz", live=False)
    assert r.ok is False
    assert r.passed is False
    assert r.fitness == 0.0
    assert r.error is not None


def test_fitness_is_monotonic_in_gate_and_coverage():
    g = {"property_type": 0.6, "location": 0.6, "price_usd": 0.6}
    better_gate = {"property_type": 0.9, "location": 0.9, "price_usd": 0.9}
    assert _fitness(better_gate, 10, True) > _fitness(g, 10, True)
    # coverage breaks ties but never outweighs the gate
    assert _fitness(g, 100, True) > _fitness(g, 5, True)
    assert _fitness(better_gate, 1, True) > _fitness(g, 10_000, True)
    # the binding (minimum) gate dominates
    skewed = {"property_type": 1.0, "location": 0.2, "price_usd": 1.0}
    # _fitness rounds to 4 decimals, so allow a rounding-width tolerance
    assert _fitness(skewed, 10, True) == pytest.approx(0.2 + 0.1 * (1 - 1 / 11), abs=1e-4)
    assert _fitness({}, 10, True) == 0.0
    assert _fitness(g, 10, False) == 0.0


# ── budget ───────────────────────────────────────────────────────────

def test_budget_cost_math_with_cache_tiers():
    b = Budget(limit_usd=10.0)
    cost = b.cost_of(
        "claude-opus-4-8",
        input_tokens=100_000,            # 0.1M * $5  = $0.50
        output_tokens=4_000,             # 0.004M * $25 = $0.10
        cache_read_input_tokens=50_000,  # 0.05M * $5 * 0.10 = $0.025
        cache_creation_input_tokens=20_000,  # 0.02M * $5 * 1.25 = $0.125
    )
    assert cost == pytest.approx(0.75, abs=1e-6)


def test_budget_charge_usage_accepts_dict_and_object():
    b = Budget(limit_usd=10.0)
    from_dict = b.charge_usage("claude-sonnet-4-6", {"input_tokens": 1_000_000})
    assert from_dict == pytest.approx(3.0)  # sonnet input $3/M

    class U:  # mimic the SDK usage object (attributes, cache fields may be None)
        input_tokens = 1_000_000
        output_tokens = 0
        cache_read_input_tokens = None
        cache_creation_input_tokens = None

    from_obj = b.charge_usage("claude-sonnet-4-6", U())
    assert from_obj == pytest.approx(3.0)
    assert b.calls == 2


def test_budget_unknown_model_defaults_to_opus_tier():
    b = Budget(limit_usd=10.0)
    assert b.price_for("some-future-model") == (5.00, 25.00)


def test_budget_check_trips_with_and_without_headroom():
    b = Budget(limit_usd=1.0)
    b.charge("claude-opus-4-8", input_tokens=100_000)  # $0.50
    b.check()  # under ceiling, no raise
    # headroom that would cross the ceiling trips early
    with pytest.raises(BudgetExceeded):
        b.check(headroom_usd=0.6)
    b.charge("claude-opus-4-8", input_tokens=120_000)  # +$0.60 -> $1.10
    assert b.exhausted()
    with pytest.raises(BudgetExceeded):
        b.check()


# ── sandbox ──────────────────────────────────────────────────────────

SLUG = "scraper_agent_test_tmp_zzz"


def test_sandbox_scope_violation():
    with Sandbox(REPO, SLUG) as sb:
        with pytest.raises(ScopeViolation):
            sb.apply(REPO / "pulpo" / "normalize.py", "nope")


def test_sandbox_new_file_lifecycle_and_rollback():
    target = REPO / "pulpo" / "scrapers" / f"{SLUG}.py"
    assert not target.exists()
    with Sandbox(REPO, SLUG) as sb:
        sb.apply(sb.scraper_path, "VERSION_A\n")
        sb.checkpoint()
        sb.apply(sb.scraper_path, "VERSION_B\n")
        assert sb.read(sb.scraper_path) == "VERSION_B\n"
        sb.rollback()
        assert sb.read(sb.scraper_path) == "VERSION_A\n"
    # not committed -> the new file is removed, no leak into the worktree
    assert not target.exists()


def test_sandbox_commit_persists_best():
    target = REPO / "pulpo" / "scrapers" / f"{SLUG}.py"
    try:
        with Sandbox(REPO, SLUG) as sb:
            sb.apply(sb.scraper_path, "WINNER\n")
            sb.checkpoint()
            sb.commit()
        assert target.exists()
        assert target.read_text() == "WINNER\n"
    finally:
        if target.exists():
            target.unlink()


def test_reload_scraper_evicts_module_cache():
    import importlib

    mod_name = "pulpo.scrapers.goodlife"
    importlib.import_module(mod_name)
    assert mod_name in sys.modules
    reload_scraper("goodlife")
    assert mod_name not in sys.modules


# ── loop ─────────────────────────────────────────────────────────────

def _report(slug, fitness, passed, ranked):
    return EvalReport(
        slug=slug, ok=True, passed=passed, fitness=fitness,
        hard_gate_pct={"property_type": fitness, "location": fitness, "price_usd": fitness},
        ranked_count=ranked, raw_count=ranked, normalized_count=ranked,
        validation={"pass": ranked, "flag": 0, "drop": 0}, failures={}, duration_s=0.0, live=False,
    )


def _stub_propose(usage=None):
    def propose(ctx):
        return ProposedEdit(
            content=f"# candidate {ctx.iteration}\n",
            usage=usage if usage is not None else {"input_tokens": 1000, "output_tokens": 500},
            model="claude-opus-4-8",
            rationale=f"try {ctx.iteration}",
        )
    return propose


def test_loop_keeps_best_discards_regression_and_stops_on_pass():
    scripted = iter([
        _report(SLUG, 0.40, False, 5),   # iter 1: kept
        _report(SLUG, 0.30, False, 4),   # iter 2: regression -> discarded
        _report(SLUG, 0.92, True, 30),   # iter 3: passes -> kept, stop
    ])
    with Sandbox(REPO, SLUG) as sb:
        res = agent_loop(
            SLUG, propose=_stub_propose(), evaluate=lambda: next(scripted),
            sandbox=sb, budget=Budget(limit_usd=5.0), kind="onboard", max_iters=6,
            baseline=_report(SLUG, 0.0, False, 0),
        )
        assert res.passed
        assert res.stop_reason == "passed"
        assert res.best_iteration == 3
        assert res.iterations == 3
        # disk reflects the best candidate, not the discarded iter-2 regression
        assert sb.read(sb.scraper_path) == "# candidate 3\n"
    # iter-2 was discarded
    assert [r.kept for r in res.history] == [True, True, False, True]


def test_loop_stops_on_budget():
    # each call bills $0.50; a $0.6 ceiling allows exactly one round
    usage = {"input_tokens": 100_000, "output_tokens": 0}
    scripted = iter([_report(SLUG, 0.4, False, 5)] * 6)
    with Sandbox(REPO, SLUG) as sb:
        res = agent_loop(
            SLUG, propose=_stub_propose(usage=usage), evaluate=lambda: next(scripted),
            sandbox=sb, budget=Budget(limit_usd=0.6), kind="onboard", max_iters=6,
            baseline=_report(SLUG, 0.0, False, 0),
        )
    assert res.stop_reason == "budget"
    assert not res.passed


def test_loop_stops_when_agent_gives_up():
    with Sandbox(REPO, SLUG) as sb:
        res = agent_loop(
            SLUG, propose=lambda ctx: None, evaluate=lambda: _report(SLUG, 0.0, False, 0),
            sandbox=sb, budget=Budget(limit_usd=5.0), kind="repair", max_iters=4,
            baseline=_report(SLUG, 0.1, False, 1),
        )
    assert res.stop_reason == "agent_gave_up"
    assert res.iterations == 0


def test_loop_propose_error_ends_loop_not_process():
    def boom(ctx):
        raise ValueError("model blew up")
    with Sandbox(REPO, SLUG) as sb:
        res = agent_loop(
            SLUG, propose=boom, evaluate=lambda: _report(SLUG, 0.0, False, 0),
            sandbox=sb, budget=Budget(limit_usd=5.0), max_iters=4,
            baseline=_report(SLUG, 0.0, False, 0),
        )
    assert res.stop_reason == "propose_error"


def test_loop_hits_max_iters_without_pass():
    scripted = iter([_report(SLUG, 0.5 + i * 0.01, False, 5) for i in range(10)])
    with Sandbox(REPO, SLUG) as sb:
        res = agent_loop(
            SLUG, propose=_stub_propose(), evaluate=lambda: next(scripted),
            sandbox=sb, budget=Budget(limit_usd=50.0), max_iters=3,
            baseline=_report(SLUG, 0.0, False, 0),
        )
    assert res.stop_reason == "max_iters"
    assert res.iterations == 3
    assert not res.passed
