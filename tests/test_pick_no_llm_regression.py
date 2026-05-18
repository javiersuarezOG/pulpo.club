"""
Hard contract: the LLM is a booster, never compulsory.

With ``LLM_VISION_ENABLED`` unset / false and no provider keys set, the
refactored two-pass picker must produce the SAME winning candidate as
the pre-refactor single-pass picker — proving that hero selection works
end-to-end without any LLM dependency.

The test mocks every cheap-signal function (compute_score,
detect_text_overlay, cheap_quality_score) with deterministic outputs so
we're asserting picker logic, not OpenCV/Tesseract behavior. Image
synthesis uses PNG to avoid the libjpeg-version mismatch on dev
machines (see BACKLOG.md).
"""
from __future__ import annotations
import io
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _make_png(width: int, height: int, *, marker: int = 0) -> bytes:
    """Synthesize a tiny PNG. ``marker`` perturbs pixel data so distinct
    candidates produce distinct byte streams (and therefore distinct
    cache keys)."""
    from PIL import Image
    img = Image.new("RGB", (width, height))
    img.putdata([(marker % 255, 128, 200)] * (width * height))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):  # type: ignore[reportUnusedFunction]
    """Clear every LLM-vision env var so the test's 'no LLM' baseline
    can't leak from a developer's local .env."""
    for k in (
        "LLM_VISION_ENABLED",
        "LLM_VISION_PROVIDER",
        "LLM_VISION_DAILY_BUDGET_USD",
        "LLM_VISION_COST_PER_CALL_USD",
        "LLM_VISION_TOP_PCT",
        "QWEN_API_KEY",
        "SEGMIND_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_pick_best_photo_url_unchanged_when_llm_off():
    """Three candidates: highest cheap score must win when the LLM is
    off. Asserts the refactor preserves the legacy picker contract
    (return tuple shape + selection logic)."""
    pytest.importorskip("PIL")
    from automation.run import _pick_best_photo_url

    big = _make_png(1920, 1080, marker=1)
    mid = _make_png(1280, 720, marker=2)
    small = _make_png(800, 600, marker=3)

    responses = {
        "https://example.com/small.png": small,
        "https://example.com/mid.png": mid,
        "https://example.com/big.png": big,
    }

    def fake_get(url, *_args, **_kwargs):
        r = mock.MagicMock()
        r.content = responses[url]
        r.raise_for_status = mock.MagicMock()
        return r

    # Make each candidate's technical score uniquely identify it so the
    # winner is deterministic and the assert isn't a function of OpenCV
    # presence on the test machine.
    def fake_compute_score(content, byte_size=None):
        if content == big:
            return 90
        if content == mid:
            return 60
        return 30

    with mock.patch("httpx.get", side_effect=fake_get), \
         mock.patch("automation.photo_quality.compute_score",
                    side_effect=fake_compute_score), \
         mock.patch("automation.photo_quality.detect_text_overlay",
                    return_value=False):
        url, content, score, has_text = _pick_best_photo_url(list(responses.keys()))

    assert url == "https://example.com/big.png"
    assert content == big
    assert score == 90
    assert has_text is False


def test_aesthetic_off_means_pure_technical_ranking():
    """A candidate with a 'better aesthetic' value (which the booster
    would have returned if enabled) MUST lose to a candidate with a
    higher technical score when the booster is off. Locks the
    non-influence of disabled-LLM state on hero choice.

    Implementation note: with LLM_VISION_ENABLED unset, score_aesthetic
    returns None for every call before any provider is consulted.
    _apply_aesthetic_to_eligible still invokes it, but the contract
    guarantees None -> no composite blending -> technical-only sort."""
    pytest.importorskip("PIL")
    from automation.run import _pick_best_photo_url

    a = _make_png(1280, 720, marker=10)
    b = _make_png(1280, 720, marker=11)

    responses = {
        "https://example.com/a.png": a,
        "https://example.com/b.png": b,
    }

    def fake_get(url, *_args, **_kwargs):
        r = mock.MagicMock()
        r.content = responses[url]
        r.raise_for_status = mock.MagicMock()
        return r

    # b has the higher technical score; a is otherwise identical.
    def fake_compute_score(content, byte_size=None):
        return 80 if content == b else 60

    with mock.patch("httpx.get", side_effect=fake_get), \
         mock.patch("automation.photo_quality.compute_score",
                    side_effect=fake_compute_score), \
         mock.patch("automation.photo_quality.detect_text_overlay",
                    return_value=False):
        url, _content, score, _has_text = _pick_best_photo_url(list(responses.keys()))

    assert url == "https://example.com/b.png"
    assert score == 80


def test_provider_failure_still_picks_a_hero():
    """LLM_VISION_ENABLED=true + Segmind key + provider raises on every
    call → score_aesthetic returns None → picker falls through to
    technical-only ranking. A hero MUST still be selected.

    This is the most important regression test in this PR: it locks
    the contract that a broken LLM cannot block hero selection."""
    pytest.importorskip("PIL")
    import os
    os.environ["LLM_VISION_ENABLED"] = "true"
    os.environ["LLM_VISION_PROVIDER"] = "segmind"
    os.environ["SEGMIND_API_KEY"] = "sk-broken-key"

    try:
        from automation.run import _pick_best_photo_url

        big = _make_png(1920, 1080, marker=21)
        small = _make_png(800, 600, marker=22)
        responses = {
            "https://example.com/big.png": big,
            "https://example.com/small.png": small,
        }

        def fake_get(url, *_args, **_kwargs):
            r = mock.MagicMock()
            r.content = responses[url]
            r.raise_for_status = mock.MagicMock()
            return r

        def fake_compute_score(content, byte_size=None):
            return 95 if content == big else 40

        # Provider raises on every aesthetic call — booster must absorb
        # and return None per the fail-soft contract.
        with mock.patch("httpx.get", side_effect=fake_get), \
             mock.patch("httpx.post", side_effect=RuntimeError("provider exploded")), \
             mock.patch("automation.photo_quality.compute_score",
                        side_effect=fake_compute_score), \
             mock.patch("automation.photo_quality.detect_text_overlay",
                        return_value=False):
            url, _content, _score, _has_text = _pick_best_photo_url(list(responses.keys()))

        # Despite provider failures, the picker still produces a hero —
        # the one with the higher technical score.
        assert url == "https://example.com/big.png"
    finally:
        for k in ("LLM_VISION_ENABLED", "LLM_VISION_PROVIDER", "SEGMIND_API_KEY"):
            os.environ.pop(k, None)
