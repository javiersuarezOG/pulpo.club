"""Tests for automation/ig_caption.py.

Strategy:
  - Test the template-only baseline (client=None) deterministically.
  - Use a stub client that returns canned strings to validate the LLM
    flow without hitting the network or requiring DEEPSEEK_API_TOKEN.
  - Cover the lint-fallback path explicitly — a bad LLM output must
    NOT poison the caption queue.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_caption import (   # noqa: E402
    _fallback_descriptive_line,
    generate_caption,
    generate_descriptive_line,
    main as caption_main,
)
from automation.ig_poster import (   # noqa: E402
    BIG_NUMBER, MAP_MARK, POST_IT, RECEIPT, STICKER, TYPO_MAX,
)


# ── fixtures ───────────────────────────────────────────────────────────

def _candidate(**override) -> dict:
    base = {
        "listing_id":          "bienesraices__test_001",
        "source":              "bienesraices",
        "source_id":           "test_001",
        "rank":                11,
        "rank_score":          81.6,
        "zone":                "el-zonte",
        "department":          "La Libertad",
        "property_type":       "land",
        "subcategory":         "land",
        "price_usd":           667295.0,
        "area_m2":             18917.05,
        "price_per_m2":        35.27,
        "price_vs_zone_pct":   -10.0,
        "dist_beach_km":       1.4,
    }
    base.update(override)
    return base


def _listing(**override) -> dict:
    base = {
        "source":          "bienesraices",
        "source_id":       "test_001",
        "title":           "Raw Land 1.9 ha El Zonte",
        "has_ocean_view":  True,
        "has_water":       True,
        "has_power":       True,
        "has_paved_access": True,
        "zone":            "el-zonte",
        "department":      "La Libertad",
    }
    base.update(override)
    return base


class _StubClient:
    """Mimics the openai.ChatCompletion interface.  `responses` is a
    list; each call() pops the next entry as the message content."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.chat = self          # so `client.chat.completions.create(...)` works
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise RuntimeError("StubClient exhausted")
        content = self._responses.pop(0)

        class _Choice:
            def __init__(s, c):
                s.message = type("M", (), {"content": c})()
        class _Resp:
            def __init__(s, choices): s.choices = choices
        return _Resp([_Choice(content)])


# ── _fallback_descriptive_line ─────────────────────────────────────────

def test_fallback_uses_zone_and_view():
    line = _fallback_descriptive_line(_candidate(), _listing(), TYPO_MAX)
    assert "El Zonte" in line
    assert "vista al océano" in line
    assert "19,000 m²" in line


def test_fallback_handles_missing_ocean_view():
    line = _fallback_descriptive_line(
        _candidate(), _listing(has_ocean_view=False, has_water_body=False), TYPO_MAX,
    )
    assert "sin construir" in line


# ── generate_descriptive_line ─────────────────────────────────────────

def test_descriptive_line_template_only_when_no_client():
    """client=None forces fallback — no LLM, no network."""
    line = generate_descriptive_line(_candidate(), _listing(), client=None)
    assert "El Zonte" in line
    assert "19,000 m²" in line


def test_descriptive_line_uses_clean_llm_output():
    clean_text = (
        "Diecinueve mil metros de tierra cruda con vista al océano, "
        "a diez minutos caminando de Bitcoin Beach."
    )
    client = _StubClient([clean_text])
    line = generate_descriptive_line(_candidate(), _listing(), client=client)
    assert line == clean_text
    assert len(client.calls) == 1


def test_descriptive_line_strips_surrounding_quotes():
    """DeepSeek sometimes wraps its output in quotes — they get stripped."""
    raw = '"Diecinueve mil metros con vista al océano."'
    client = _StubClient([raw])
    line = generate_descriptive_line(_candidate(), _listing(), client=client)
    assert not line.startswith('"')
    assert not line.endswith('"')


def test_descriptive_line_retries_on_lint_fail():
    """First LLM output is dirty (banned word).  Second is clean.  We
    use the second."""
    dirty = "Una premium oportunidad única en El Zonte."
    clean = "Una hectárea de tierra cruda con vista al océano."
    client = _StubClient([dirty, clean])
    line = generate_descriptive_line(_candidate(), _listing(), client=client)
    assert line == clean
    assert len(client.calls) == 2


def test_descriptive_line_falls_back_after_repeated_lint_fail():
    """Both LLM attempts dirty → falls back to safe template."""
    dirty1 = "Premium propiedad exclusiva!!!"
    dirty2 = "Otra oportunidad imperdible para inversionistas."
    client = _StubClient([dirty1, dirty2])
    line = generate_descriptive_line(_candidate(), _listing(), client=client)
    # Fallback for normal (non-bargain) terreno = "{area} en {zone}, vista al océano."
    assert "El Zonte" in line
    assert "19,000 m²" in line
    assert "premium" not in line.lower()
    assert "!" not in line


def test_descriptive_line_falls_back_on_api_error():
    """LLM raises → fall back, no retry on hard error."""
    class _Boom:
        def __init__(s):
            s.chat = s
            s.completions = s
        def create(s, **kw):
            raise RuntimeError("api 500")
    line = generate_descriptive_line(_candidate(), _listing(), client=_Boom())
    assert "El Zonte" in line  # fallback


# ── generate_caption full composition ──────────────────────────────────

def test_caption_template_only_typo_max():
    caption = generate_caption(_candidate(), _listing(), poster_type=TYPO_MAX, client=None)
    # Hook (bold), descriptive, facts (price + distance), CTA
    assert "**" in caption
    assert "El Zonte" in caption
    assert "$667,295" in caption
    assert "1.4 km" in caption
    assert "pulpo.club" in caption
    assert "011" in caption       # listing N°


def test_caption_sticker_uses_sticker_hook():
    caption = generate_caption(_candidate(), _listing(), poster_type=STICKER, client=None)
    # Sticker hook = "**{area} en {zone}.**"
    assert "**19,000 m² en El Zonte.**" in caption


def test_caption_post_it_uses_bargain_hook_when_pct_low():
    bargain = _candidate(price_vs_zone_pct=-93.0)
    caption = generate_caption(bargain, _listing(), poster_type=POST_IT, client=None)
    assert "tentáculo" in caption.lower()
    assert "El Zonte" in caption or "Zonte" in caption


def test_caption_post_it_falls_back_when_pct_missing():
    """If not actually a bargain, post-it hook is generic (no tentáculo phrase)."""
    boring = _candidate(price_vs_zone_pct=0.0)
    caption = generate_caption(boring, _listing(), poster_type=POST_IT, client=None)
    # No tentáculo claim if not a bargain
    assert "tentáculo" not in caption.lower()


def test_caption_big_number_uses_ppm():
    caption = generate_caption(_candidate(), _listing(), poster_type=BIG_NUMBER, client=None)
    assert "$35.27/m²" in caption


def test_caption_receipt_skips_facts_line():
    """Receipt (listicle) caption is cover-only — no per-listing facts."""
    caption = generate_caption(_candidate(), _listing(), poster_type=RECEIPT, client=None)
    assert "Cinco terrenos" in caption
    # Receipt CTA is "link en bio" instead of listing N°
    assert "link en bio" in caption
    # No "$667,295 · a 1.4 km del mar" facts strip
    assert "del mar" not in caption


def test_caption_map_mark_uses_zone_tentaculo():
    caption = generate_caption(_candidate(), _listing(), poster_type=MAP_MARK, client=None)
    assert "tentáculo" in caption.lower()
    assert "link en bio" in caption


def test_caption_respects_hook_override():
    caption = generate_caption(
        _candidate(), _listing(), poster_type=TYPO_MAX, client=None,
        overrides={"hook": "**Custom hook.**"},
    )
    assert caption.startswith("**Custom hook.**")


def test_caption_respects_empty_overrides_skip_section():
    """Empty override removes the section entirely.  Used by queue
    builder when a human wants only a hook + descriptive (no facts)."""
    caption = generate_caption(
        _candidate(), _listing(), poster_type=TYPO_MAX, client=None,
        overrides={"facts": "", "cta": ""},
    )
    assert "pulpo.club" not in caption


def test_caption_invalid_poster_type_raises():
    with pytest.raises(ValueError):
        generate_caption(_candidate(), _listing(), poster_type="bogus", client=None)


def test_caption_works_without_listing_record():
    """The queue builder may call with just the candidate (no listing
    lookup) — should still produce a sensible caption."""
    caption = generate_caption(_candidate(), None, poster_type=TYPO_MAX, client=None)
    assert "El Zonte" in caption
    assert "$667,295" in caption


# ── CLI smoke ──────────────────────────────────────────────────────────

def test_main_template_only(tmp_path, capsys):
    import json
    cand_file = tmp_path / "ig_candidates.json"
    cand_file.write_text(json.dumps({
        "version": 1,
        "candidates": [_candidate(listing_id="src__cli_test", source="src", source_id="cli_test")],
    }))
    ranked = tmp_path / "ranked.json"
    ranked.write_text(json.dumps([
        _listing(source="src", source_id="cli_test"),
    ]))
    rc = caption_main([
        "--candidates", str(cand_file),
        "--ranked",     str(ranked),
        "--candidate-id", "src__cli_test",
        "--no-llm",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "El Zonte" in out
    assert "pulpo.club" in out


def test_main_unknown_candidate_returns_2(tmp_path):
    import json
    cand_file = tmp_path / "c.json"
    cand_file.write_text(json.dumps({"version": 1, "candidates": []}))
    ranked = tmp_path / "r.json"
    ranked.write_text("[]")
    rc = caption_main([
        "--candidates", str(cand_file),
        "--ranked",     str(ranked),
        "--candidate-id", "nobody__here",
    ])
    assert rc == 2
