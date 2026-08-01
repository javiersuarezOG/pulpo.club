"""The Copywriter produces a complete, in-voice, lint-clean, fact-grounded
post for every lever, and its LLM path soft-fails to the deterministic draft
on every failure mode. Fully offline (no model call)."""
from __future__ import annotations

import pytest

from automation import ig_copywriter as cw
from automation import ig_caption_lint
from automation import ig_content_categories as cats
from automation import ig_facts

LISTING = {
    "zone": "el-tunco", "department": "La Libertad",
    "price_usd": 145000.0, "area_m2": 1036.0, "bedrooms": 0,
    "dist_beach_km": 0.2, "property_type": "land",
}


# ── every lever: complete, clean, in-voice ─────────────────────────────

@pytest.mark.parametrize("lever", cats.SLUGS)
def test_every_lever_generates_a_complete_clean_post(lever):
    p = cw.generate_post(LISTING, lever)
    # both languages, both surfaces present + non-trivial
    for k in ("caption_es", "caption_en", "comment_es", "comment_en"):
        assert len(p[k]) > 40
    # a hook (bold) and the favor-CTA
    assert p["caption_es"].startswith("**")
    assert "link en bio" in p["caption_es"] and "link in bio" in p["caption_en"]
    # lint-clean in BOTH languages (no banned words, no shouting, no exclamation)
    for k in ("caption_es", "caption_en", "comment_es", "comment_en"):
        assert ig_caption_lint.check(p[k]) == [], f"{lever}/{k} not lint-clean"
        assert ig_facts.stat_violations(p[k]) == [], f"{lever}/{k} has an un-sourced stat"
    assert p["lint_ok"] is True and p["model"] == "deterministic"
    assert p["tier"] in ("free", "pro")


def test_es_caption_uses_voseo_somewhere_in_the_feed():
    # Voseo is the strongest local signal; at least the education/scarcity
    # levers carry an explicit vos-form.
    edu = cw.generate_post(LISTING, "education")["caption_es"].lower()
    assert "vos " in edu or "veás" in edu or "dejá" in edu or "abrís" in edu


def test_stat_levers_cite_a_ledger_fact_verbatim():
    for lever in ("authority", "investment", "social_proof", "transformation"):
        p = cw.generate_post(LISTING, lever)
        assert p["facts_cited"], f"{lever} cites no fact"
        fact = ig_facts.get(p["facts_cited"][0])
        assert fact["statement_es"] in p["caption_es"]  # verbatim, never paraphrased-away


def test_wire_format_joins_es_then_en():
    p = cw.generate_post(LISTING, "aspiration")
    wire = cw.wire_caption(p)
    assert wire.index(p["caption_es"]) < wire.index(p["caption_en"])
    assert cw.DIV in wire


def test_no_lever_ever_mentions_a_banned_topic():
    # HARD RULE: crime / homicide / "safest country" framing is banned on every
    # lever, both languages, caption + comment. This is a brand line we never cross.
    for lever in cats.SLUGS:
        p = cw.generate_post(LISTING, lever)
        for key in ("caption_es", "caption_en", "comment_es", "comment_en"):
            assert ig_facts.mentions_banned_topic(p[key]) == [], f"{lever}/{key} named a banned topic"


def test_unknown_lever_raises():
    with pytest.raises(ValueError):
        cw.generate_post(LISTING, "clickbait")


# ── LLM polish soft-fail paths (the robustness core) ───────────────────

def test_llm_valid_output_is_used():
    def polish(det, listing, lever_def):
        return {**det, "caption_es": "**Un buen gancho.**\n\nCuerpo honesto.\n\npulpo.club · link en bio",
                "model": "claude"}
    p = cw.generate_post(LISTING, "aspiration", llm_polish=polish)
    assert p["model"] == "claude" and "buen gancho" in p["caption_es"]
    assert p["fallback_reason"] is None


def test_llm_lint_rejected_output_falls_back_to_deterministic():
    def polish(det, listing, lever_def):
        return {**det, "caption_es": "**Oportunidad premium única.**\n\nx\n\npulpo.club · link en bio"}
    p = cw.generate_post(LISTING, "scarcity", llm_polish=polish)
    assert p["model"] == "deterministic"        # banned words → rejected
    assert p["fallback_reason"] == "lint_reject"
    assert "premium" not in p["caption_es"]


def test_llm_invented_stat_is_rejected_by_the_fact_guard():
    def polish(det, listing, lever_def):
        return {**det, "caption_es": "**Dato.**\n\nEl 73% ya compró aquí.\n\npulpo.club · link en bio"}
    p = cw.generate_post(LISTING, "authority", llm_polish=polish)
    assert p["model"] == "deterministic" and p["fallback_reason"] == "lint_reject"


def test_llm_exception_soft_fails():
    def polish(det, listing, lever_def):
        raise RuntimeError("api down")
    p = cw.generate_post(LISTING, "investment", llm_polish=polish)
    assert p["model"] == "deterministic"
    assert p["fallback_reason"].startswith("llm_error")


def test_llm_none_falls_back():
    p = cw.generate_post(LISTING, "education", llm_polish=lambda *a: None)
    assert p["model"] == "deterministic" and p["fallback_reason"] == "llm_empty"


# ── observability: events fire, never raise ────────────────────────────

def test_generate_emits_events(monkeypatch):
    events = []
    class _Fake:
        @staticmethod
        def capture(event, props): events.append((event, props))
    monkeypatch.setattr(cw, "_ph", _Fake)
    cw.generate_post(LISTING, "scarcity")
    assert any(e == "ig.caption.generated" for e, _ in events)


def test_telemetry_failure_never_breaks_generation(monkeypatch):
    class _Boom:
        @staticmethod
        def capture(event, props): raise RuntimeError("posthog down")
    monkeypatch.setattr(cw, "_ph", _Boom)
    p = cw.generate_post(LISTING, "scarcity")   # must not raise
    assert p["lint_ok"] is True
