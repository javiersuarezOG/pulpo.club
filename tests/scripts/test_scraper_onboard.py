"""Tests for scripts/scraper_onboard.py — the Train B onboarding CLI.

Offline and keyless: the Anthropic call is stubbed, and the end-to-end
integration test drives the *real* harness (sandbox + evaluate + loop) against
an existing source's committed offline fixtures, so it exercises the whole
pipeline deterministically with zero network and zero spend.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import scraper_onboard as onboard  # noqa: E402
from automation.scraper_agent.eval import EvalReport  # noqa: E402
from automation.scraper_agent.loop import LoopContext  # noqa: E402


def _report(slug="acme", *, ok=True, fitness=0.0, passed=False, ranked=0):
    return EvalReport(
        slug=slug, ok=ok, passed=passed, fitness=fitness,
        hard_gate_pct={"property_type": fitness, "location": fitness, "price_usd": fitness},
        ranked_count=ranked, raw_count=ranked, normalized_count=ranked,
        validation={"pass": ranked, "flag": 0, "drop": 0}, failures={}, duration_s=0.0,
        live=False, error=None if ok else "boom",
    )


def _ctx(slug="acme", iteration=1, current=None, last=None):
    rep = last or _report(slug)
    return LoopContext(slug=slug, kind="onboard", iteration=iteration,
                       current_source=current, best=rep, last=rep, history=[])


# ── parsing ──────────────────────────────────────────────────────────

def test_parse_proposal_extracts_module_and_rationale():
    text = (
        "## Rationale\nChose detail_jsonld; fixed the price regex.\n\n"
        "## Module\n```python\nclass X: pass\n```\n"
    )
    module, rationale = onboard.parse_proposal(text)
    assert module == "class X: pass\n"
    assert rationale == "Chose detail_jsonld; fixed the price regex."


def test_parse_proposal_picks_largest_block():
    text = "```python\nsmall\n```\nand\n```python\nthe much longer winning module\n```"
    module, _ = onboard.parse_proposal(text)
    assert "winning module" in module


def test_parse_proposal_none_when_no_code_block():
    assert onboard.parse_proposal("I cannot do this. ## Recommendation needs human") is None


# ── prompt ───────────────────────────────────────────────────────────

def test_build_prompt_includes_contract_and_feedback():
    last = _report("acme", ok=False)  # fetch failed
    prompt = onboard.build_onboard_prompt(_ctx("acme", last=last), source_url="https://acme.sv/ventas")
    assert "acme" in prompt
    assert "https://acme.sv/ventas" in prompt
    assert "## Module" in prompt
    assert "SkeletonConfig" in prompt
    assert 'register(SOURCES, "acme"' in prompt
    assert "funnel FAILED" in prompt  # the ok=False feedback branch


def test_build_prompt_reports_gate_coverage_when_funnel_ran():
    last = _report("acme", ok=True, fitness=0.6, ranked=12)
    prompt = onboard.build_onboard_prompt(_ctx("acme", last=last), source_url="https://acme.sv")
    assert "ranked=12" in prompt
    assert "60%" in prompt


# ── propose (stubbed model call) ─────────────────────────────────────

def test_make_propose_returns_edit_with_usage(monkeypatch):
    canned = "## Rationale\nuse og meta.\n## Module\n```python\n# acme scraper\n```"
    monkeypatch.setattr(
        onboard, "_call_model",
        lambda prompt, *, provider, model: (canned, {"input_tokens": 2000, "output_tokens": 800}),
    )
    propose = onboard.make_propose("https://acme.sv", provider="deepseek")
    edit = propose(_ctx("acme"))
    assert edit is not None
    assert edit.content == "# acme scraper\n"
    assert edit.rationale == "use og meta."
    assert edit.model == "deepseek-chat"  # provider default
    assert edit.usage == {"input_tokens": 2000, "output_tokens": 800}


def test_make_propose_defaults_model_per_provider(monkeypatch):
    captured = {}

    def fake(prompt, *, provider, model):
        captured.update(provider=provider, model=model)
        return "## Module\n```python\n# x\n```", {}

    monkeypatch.setattr(onboard, "_call_model", fake)
    onboard.make_propose("https://acme.sv", provider="anthropic")(_ctx("acme"))
    assert captured == {"provider": "anthropic", "model": "claude-opus-4-8"}


def test_make_propose_returns_none_when_model_gives_no_code(monkeypatch):
    monkeypatch.setattr(onboard, "_call_model", lambda prompt, *, provider, model: ("needs human", {}))
    assert onboard.make_propose("https://acme.sv")(_ctx("acme")) is None


# ── pr body ──────────────────────────────────────────────────────────

def test_render_pr_body_has_gate_percentages():
    class R:
        best = _report("acme", ok=True, fitness=0.9, passed=True, ranked=40)
        iterations = 3
        stop_reason = "passed"
        budget_summary = "spent $0.40 / $2.00"
    body = onboard.render_pr_body("acme", "https://acme.sv", R())
    assert "acme" in body and "90%" in body and "passed" in body


# ── end-to-end against a real source (offline, keyless) ──────────────

def test_run_onboarding_end_to_end_offline_real_source():
    """Stub propose returns goodlife's actual current source; evaluate runs
    offline against goodlife's committed fixtures. Exercises the full
    sandbox -> apply -> reload -> evaluate -> keep -> commit path."""
    slug = "goodlife"
    real_source = (REPO / "pulpo" / "scrapers" / f"{slug}.py").read_text(encoding="utf-8")
    pr_body_file = REPO / f"PR_BODY_{slug}.md"

    def stub_propose(ctx):
        from automation.scraper_agent import ProposedEdit
        return ProposedEdit(content=real_source, rationale="port the known-good source",
                            model="claude-opus-4-8", usage={"input_tokens": 100, "output_tokens": 50})

    try:
        result, pr_body = onboard.run_onboarding(
            slug, "https://goodlifeelsalvador.com", propose=stub_propose,
            live=False, max_iters=2, budget_usd=5.0, limit=50, min_ranked=1, log=lambda m: None,
        )
        assert result.passed, result.summary()
        # goodlife's committed fixtures already clear the gate, so the loop
        # early-exits at baseline (iterations=0) — exercising the real
        # evaluate -> commit -> PR-body path end to end.
        assert result.stop_reason == "passed"
        assert result.iterations == 0
        assert pr_body is not None and "goodlife" in pr_body
        assert pr_body_file.exists()
        # committed best == original source (stub returned it verbatim) -> no diff
        assert (REPO / "pulpo" / "scrapers" / f"{slug}.py").read_text(encoding="utf-8") == real_source
    finally:
        if pr_body_file.exists():
            pr_body_file.unlink()


# ── CLI ──────────────────────────────────────────────────────────────

def test_cli_dry_run_prints_prompt(capsys):
    rc = onboard.main(["--slug", "acme", "--url", "https://acme.sv/ventas", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "## Module" in out and "acme" in out


def test_cli_rejects_bad_slug():
    assert onboard.main(["--slug", "Bad-Slug", "--url", "https://x.sv"]) == 2


def test_cli_requires_provider_key_when_not_dry_run(monkeypatch):
    # default provider is deepseek -> checks DEEPSEEK_API_TOKEN
    monkeypatch.delenv("DEEPSEEK_API_TOKEN", raising=False)
    assert onboard.main(["--slug", "acme", "--url", "https://acme.sv", "--live"]) == 2
    # --provider anthropic -> checks ANTHROPIC_API_KEY
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert onboard.main(
        ["--slug", "acme", "--url", "https://acme.sv", "--live", "--provider", "anthropic"]
    ) == 2
