"""Tests for scripts/scraper_repair.py — Train A (active-mode repair).

Offline and keyless: the model call + live probe are stubbed, and the
end-to-end test drives the real harness against an existing source's committed
fixtures (live=False) with the borrowed-slug registration restored afterward.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import scraper_repair as repair  # noqa: E402
import scraper_onboard as onboard  # noqa: E402
from automation.scraper_agent.eval import EvalReport  # noqa: E402
from automation.scraper_agent.loop import LoopContext  # noqa: E402


def _report(slug="zz", *, ok=True, fitness=0.0, passed=False, ranked=0):
    return EvalReport(
        slug=slug, ok=ok, passed=passed, fitness=fitness,
        hard_gate_pct={"property_type": fitness, "location": fitness, "price_usd": fitness},
        ranked_count=ranked, raw_count=ranked, normalized_count=ranked,
        validation={"pass": ranked, "flag": 0, "drop": 0}, failures={}, duration_s=0.0,
        live=True, error=None if ok else "boom",
    )


def _ctx(slug="zz", current=None):
    rep = _report(slug)
    return LoopContext(slug=slug, kind="repair", iteration=1, current_source=current,
                       best=rep, last=rep, history=[])


# ── recover-to-median target ─────────────────────────────────────────

def test_recent_kept_median_and_target(tmp_path):
    hist = tmp_path / "health.jsonl"
    rows = [
        '{"source":"acme","kept":100,"status":"green"}',
        '{"source":"acme","kept":120,"status":"green"}',
        '{"source":"acme","kept":110,"status":"green"}',
        '{"source":"other","kept":5,"status":"green"}',
        '{"source":"acme","kept":0,"status":"red"}',   # ignored (kept=0)
    ]
    hist.write_text("\n".join(rows))
    assert repair.recent_kept_median("acme", hist) == 110
    # target = median * recover_frac, never below floor
    assert repair.repair_target_min_ranked("acme", hist, recover_frac=0.8) == 88
    assert repair.repair_target_min_ranked("acme", hist, recover_frac=0.01, floor=10) == 10


def test_target_falls_back_to_floor_without_history(tmp_path):
    assert repair.recent_kept_median("nobody", tmp_path / "missing.jsonl") is None
    assert repair.repair_target_min_ranked("nobody", tmp_path / "missing.jsonl", floor=10) == 10


# ── failure snapshot ─────────────────────────────────────────────────

def test_load_failure_snapshot_picks_newest(tmp_path):
    d = tmp_path / "fails"
    d.mkdir()
    (d / "acme_2026-06-01T00:00:00_a.json").write_text('{"error":"old"}')
    (d / "acme_2026-06-10T00:00:00_b.json").write_text('{"error":"new"}')
    (d / "other_2026-06-11_c.json").write_text('{"error":"nope"}')
    snap = repair.load_failure_snapshot("acme", d)
    assert snap == {"error": "new"}
    assert repair.load_failure_snapshot("acme", tmp_path / "missing") is None


# ── prompt + proposer ────────────────────────────────────────────────

def test_build_repair_prompt_has_break_framing_and_snapshot():
    prompt = repair.build_repair_prompt(
        _ctx("acme", current="class Old: ..."), source_url="https://acme.sv",
        failure_snapshot={"error_class": "HTTPError", "status": 404}, probe=None,
    )
    assert "WAS WORKING and recently broke" in prompt
    assert "HTTPError" in prompt and "404" in prompt   # failure snapshot injected
    assert "class Old:" in prompt                       # current broken code included
    assert 'register(SOURCES, "acme"' in prompt          # reuses the onboard contract


def test_make_repair_propose_probes_and_calls_model(monkeypatch):
    monkeypatch.setattr(onboard, "_probe_site", lambda url: {"catalog_html": "x"})
    monkeypatch.setattr(onboard, "_call_model",
                        lambda prompt, *, provider, model: ("## Module\n```python\n# fixed\n```", {"input_tokens": 5}))
    propose = repair.make_repair_propose("https://acme.sv", provider="deepseek",
                                         failure_snapshot={"error": "x"})
    edit = propose(_ctx("acme"))
    assert edit.content == "# fixed\n"
    assert edit.model == "deepseek-chat"


def test_derive_source_url_from_existing_scraper_config():
    # a real skeleton scraper exposes CONFIG.list_url
    url = repair.derive_source_url("xitios")
    assert url and "xitios" in url


# ── end-to-end against a real source (offline, keyless) ──────────────

def test_run_repair_end_to_end_offline(tmp_path):
    """Stub propose returns goodlife's real source; evaluate offline against
    its fixtures with a low target -> the repair 'passes'. Exercises
    sandbox -> apply -> reload -> evaluate -> keep -> commit + trace."""
    slug = "goodlife"
    real_source = (REPO / "pulpo" / "scrapers" / f"{slug}.py").read_text(encoding="utf-8")
    pr_body_file = REPO / f"PR_BODY_repair_{slug}.md"

    def stub_propose(ctx):
        from automation.scraper_agent import ProposedEdit
        return ProposedEdit(content=real_source, rationale="restore", model="deepseek-chat",
                            usage={"input_tokens": 10, "output_tokens": 5})

    try:
        result, pr_body = repair.run_repair(
            slug, "https://goodlifeelsalvador.com", propose=stub_propose,
            target_min_ranked=1, max_iters=2, budget_usd=5.0, live=False, limit=50,
            trace_dir=tmp_path / "trace", log=lambda m: None,
        )
        assert result.passed and result.kind == "repair"
        assert pr_body is not None and "Repair" in pr_body
        assert pr_body_file.exists()
        assert (tmp_path / "trace" / "summary.json").exists()
    finally:
        if pr_body_file.exists():
            pr_body_file.unlink()
        import importlib

        from automation.scraper_agent.sandbox import reload_scraper
        reload_scraper(slug)
        importlib.import_module(f"pulpo.scrapers.{slug}")


# ── CLI ──────────────────────────────────────────────────────────────

def test_cli_skips_waf_sources(monkeypatch):
    class P:
        auto_repair = False
    monkeypatch.setattr(repair, "get_policy", lambda slug: P())
    assert repair.main(["--slug", "nexo", "--url", "https://x.sv"]) == 0   # skipped, not an error


def test_cli_dry_run_prints_repair_prompt(capsys):
    rc = repair.main(["--slug", "goodlife", "--url", "https://goodlifeelsalvador.com", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "WAS WORKING and recently broke" in out
    assert "repair target" in out


def test_cli_requires_key_when_not_dry_run(monkeypatch):
    class P:
        auto_repair = True
    monkeypatch.setattr(repair, "get_policy", lambda slug: P())
    monkeypatch.delenv("DEEPSEEK_API_TOKEN", raising=False)
    assert repair.main(["--slug", "goodlife", "--url", "https://x.sv"]) == 2


def test_cli_rejects_bad_slug():
    assert repair.main(["--slug", "Bad-Slug", "--url", "https://x.sv"]) == 2
