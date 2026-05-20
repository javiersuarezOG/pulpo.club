"""
Phase 4 U3 — LLM-vision aesthetic booster tests.

The booster must satisfy a hard contract from the plan (§L9):

  1. With LLM_VISION_ENABLED unset / "false", score_aesthetic returns
     None for every call and writes no budget rows.
  2. With LLM_VISION_ENABLED=true but no provider API key, returns None
     and writes no budget rows.
  3. With LLM_VISION_ENABLED=true + a configured provider, returns a
     0-10 float on success and increments the daily budget log.
  4. With cumulative spend ≥ daily cap, returns None and writes a
     `llm_vision_budget_exceeded` row so the operator can see the cap
     hit.
  5. A provider-side failure (parse error, exception) returns None and
     writes a `llm_vision_call_failed` row — never raises.

These are unit tests so the OpenAI/Anthropic clients are mocked. No
network IO. Each test uses tmp_path + monkeypatches the repo root so
the budget log doesn't pollute the real web/data/ tree.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


@pytest.fixture(autouse=True)
def _isolate_budget_log(tmp_path, monkeypatch):
    """Point the booster's budget-log path at a temp directory and clear
    any caller env so the default-off state holds unless the test sets
    its own flags."""
    from automation import aesthetic_vision

    # All env vars relevant to the booster — reset to a known-clean
    # baseline at the start of every test.
    for k in (
        "LLM_VISION_ENABLED",
        "LLM_VISION_PROVIDER",
        "LLM_VISION_DAILY_BUDGET_USD",
        "LLM_VISION_COST_PER_CALL_USD",
        "QWEN_API_KEY",
        "SEGMIND_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "QWEN_BASE_URL",
        "QWEN_VISION_MODEL",
        "SEGMIND_BASE_URL",
        "SEGMIND_VISION_MODEL",
    ):
        monkeypatch.delenv(k, raising=False)

    monkeypatch.setattr(
        aesthetic_vision,
        "_REPO_ROOT",
        tmp_path,
    )
    (tmp_path / "web" / "data").mkdir(parents=True, exist_ok=True)
    yield


def _budget_rows(tmp_path) -> list[dict]:
    path = tmp_path / "web" / "data" / "llm_vision_budget.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


# ── Default OFF behavior ──────────────────────────────────────────────────


def test_returns_none_when_disabled(tmp_path):
    """Hard contract item 1 — no env vars at all means booster is a
    no-op."""
    from automation.aesthetic_vision import score_aesthetic

    assert score_aesthetic(b"fake_jpeg_bytes") is None
    assert _budget_rows(tmp_path) == []


def test_returns_none_when_enabled_but_no_key(tmp_path, monkeypatch):
    """Hard contract item 2 — enabling without keys must NOT throw and
    must NOT call any provider."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    from automation.aesthetic_vision import score_aesthetic

    assert score_aesthetic(b"fake_jpeg_bytes") is None
    assert _budget_rows(tmp_path) == []


# ── Active booster path ───────────────────────────────────────────────────


def test_qwen_call_returns_score_and_records_spend(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-qwen")
    monkeypatch.setenv("LLM_VISION_DAILY_BUDGET_USD", "1.00")

    fake_choice = mock.MagicMock()
    fake_choice.message.content = (
        '{"visual_appeal": 7.5, "issues": [], "rationale": "Bright kitchen"}'
    )
    fake_resp = mock.MagicMock()
    fake_resp.choices = [fake_choice]
    fake_client = mock.MagicMock()
    fake_client.chat.completions.create.return_value = fake_resp
    fake_openai_cls = mock.MagicMock(return_value=fake_client)

    with mock.patch.dict(
        "sys.modules",
        {"openai": mock.MagicMock(OpenAI=fake_openai_cls)},
    ):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(b"fake_jpeg")

    assert score is not None and score["score"] == 7.5
    assert score["has_marketing_overlay"] is None  # legacy fixture omits the field
    # Provider invoked with the DashScope-compat base URL by default.
    fake_openai_cls.assert_called_once()
    call_kwargs = fake_openai_cls.call_args.kwargs
    assert call_kwargs["api_key"] == "sk-test-qwen"
    assert "dashscope" in call_kwargs["base_url"]
    rows = _budget_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["event"] == "llm_vision_call"
    assert rows[0]["provider"] == "qwen"
    assert rows[0]["score"] == 7.5
    assert rows[0]["cost_usd"] > 0


def test_provider_failure_returns_none_and_logs(tmp_path, monkeypatch):
    """Hard contract item 5 — never raise. The picker depends on this."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-qwen")

    fake_client = mock.MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("rate_limited")
    fake_openai_cls = mock.MagicMock(return_value=fake_client)

    with mock.patch.dict(
        "sys.modules",
        {"openai": mock.MagicMock(OpenAI=fake_openai_cls)},
    ):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(b"fake_jpeg")

    assert score is None
    rows = _budget_rows(tmp_path)
    assert any(r["event"] == "llm_vision_call_failed" for r in rows)


def test_unparsable_response_returns_none(tmp_path, monkeypatch):
    """A 200 response that isn't valid JSON shouldn't burn budget."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-qwen")

    fake_choice = mock.MagicMock()
    fake_choice.message.content = "i refuse to comply with json"
    fake_resp = mock.MagicMock()
    fake_resp.choices = [fake_choice]
    fake_client = mock.MagicMock()
    fake_client.chat.completions.create.return_value = fake_resp
    fake_openai_cls = mock.MagicMock(return_value=fake_client)

    with mock.patch.dict(
        "sys.modules",
        {"openai": mock.MagicMock(OpenAI=fake_openai_cls)},
    ):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(b"fake_jpeg")

    assert score is None
    # We don't record spend for a 200 we couldn't parse — the budget
    # log should have zero llm_vision_call rows.
    rows = _budget_rows(tmp_path)
    assert [r for r in rows if r["event"] == "llm_vision_call"] == []


# ── Budget cap enforcement ────────────────────────────────────────────────


def test_budget_exhausted_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-qwen")
    monkeypatch.setenv("LLM_VISION_DAILY_BUDGET_USD", "0.0005")
    monkeypatch.setenv("LLM_VISION_COST_PER_CALL_USD", "0.001")

    # Pre-populate the budget log with a row already over the cap so the
    # very first call sees the budget as exhausted.
    from automation.aesthetic_vision import _budget_log_path, _today_iso

    path = _budget_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(
            json.dumps(
                {
                    "event": "llm_vision_call",
                    "date": _today_iso(),
                    "provider": "qwen",
                    "cost_usd": 0.001,
                }
            )
            + "\n"
        )

    # If the booster honored the cap correctly, OpenAI is never imported.
    with mock.patch.dict("sys.modules", {"openai": mock.MagicMock()}):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(b"fake_jpeg")

    assert score is None
    rows = _budget_rows(tmp_path)
    assert any(r["event"] == "llm_vision_budget_exceeded" for r in rows)


# ── Daily summary ─────────────────────────────────────────────────────────


def test_daily_summary_zero_state(tmp_path):
    from automation.aesthetic_vision import daily_summary
    s = daily_summary()
    assert s["enabled"] is False
    assert s["provider"] is None
    assert s["calls"] == 0
    assert s["spend_usd"] == 0.0


def test_daily_summary_counts_today_only(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-qwen")
    from automation.aesthetic_vision import (
        _budget_log_path,
        _today_iso,
        daily_summary,
    )

    path = _budget_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        # 2 calls today, 1 call yesterday — only today's should appear.
        f.write(json.dumps({
            "event": "llm_vision_call",
            "date": _today_iso(),
            "provider": "qwen",
            "cost_usd": 0.0006,
            "score": 7.0,
        }) + "\n")
        f.write(json.dumps({
            "event": "llm_vision_call",
            "date": _today_iso(),
            "provider": "qwen",
            "cost_usd": 0.0006,
            "score": 5.5,
        }) + "\n")
        f.write(json.dumps({
            "event": "llm_vision_call",
            "date": "2026-01-01",  # not today
            "provider": "qwen",
            "cost_usd": 0.0006,
            "score": 8.0,
        }) + "\n")

    s = daily_summary()
    assert s["calls"] == 2
    assert s["enabled"] is True
    assert s["by_provider"] == {"qwen": 2}
    # Rounded to 4 decimals in the summary.
    assert s["spend_usd"] == pytest.approx(0.0012, abs=1e-6)


# ── Segmind provider ──────────────────────────────────────────────────────


def test_segmind_call_returns_score_and_records_spend(tmp_path, monkeypatch):
    """Segmind's endpoint is custom (URL embeds model, auth via x-api-key
    header). The OpenAI SDK isn't usable here, so the call goes through
    httpx.post directly. Verify: score parsed, budget row written with
    provider=segmind and the Segmind default cost."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("LLM_VISION_PROVIDER", "segmind")
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-test-segmind")
    monkeypatch.setenv("LLM_VISION_DAILY_BUDGET_USD", "1.00")

    fake_response = mock.MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"visual_appeal": 6.0}'}}]
    }
    with mock.patch("httpx.post", return_value=fake_response) as fake_post:
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(b"fake_jpeg_segmind")

    assert score is not None and score["score"] == 6.0
    fake_post.assert_called_once()
    call_kwargs = fake_post.call_args.kwargs
    assert call_kwargs["headers"]["x-api-key"] == "sk-test-segmind"
    # URL must embed the model name per Segmind's API contract.
    assert fake_post.call_args.args[0].endswith("/qwen3-vl-flash")

    rows = _budget_rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["event"] == "llm_vision_call"
    assert rows[0]["provider"] == "segmind"
    assert rows[0]["score"] == 6.0
    # Segmind's per-call default is $0.0008, not the qwen $0.0006.
    assert rows[0]["cost_usd"] == pytest.approx(0.0008, abs=1e-6)


def test_segmind_http_error_returns_none_and_logs(tmp_path, monkeypatch):
    """Fail-soft contract: provider HTTP errors must not raise."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("LLM_VISION_PROVIDER", "segmind")
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-test-segmind")

    with mock.patch("httpx.post", side_effect=RuntimeError("502 bad gateway")):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(b"fake_jpeg_segmind")

    assert score is None
    rows = _budget_rows(tmp_path)
    assert any(r["event"] == "llm_vision_call_failed" and r.get("provider") == "segmind"
               for r in rows)


# ── Provider resolution ───────────────────────────────────────────────────


def test_provider_resolution_segmind_explicit(monkeypatch):
    """LLM_VISION_PROVIDER=segmind resolves to segmind only when the
    Segmind key is set. Without the key, returns None (NOT a silent
    fallback to a different provider) — matches the existing 'surface
    config errors loudly' design for explicit provider picks."""
    monkeypatch.setenv("LLM_VISION_PROVIDER", "segmind")
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-also-set")  # decoy
    from automation.aesthetic_vision import _resolve_provider
    assert _resolve_provider() is None

    monkeypatch.setenv("SEGMIND_API_KEY", "sk-test-segmind")
    assert _resolve_provider() == "segmind"


def test_provider_resolution_auto_detect_prefers_qwen_over_segmind(monkeypatch):
    """Auto-detect order keeps DashScope (qwen) first per the
    .env.example's 'recommended' guidance, then Segmind ahead of
    openai/anthropic."""
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen")
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-segmind")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    from automation.aesthetic_vision import _resolve_provider
    assert _resolve_provider() == "qwen"


def test_provider_resolution_auto_detect_segmind_when_no_qwen(monkeypatch):
    """When QWEN_API_KEY is absent, Segmind wins over openai/anthropic."""
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-segmind")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    from automation.aesthetic_vision import _resolve_provider
    assert _resolve_provider() == "segmind"


# ── Aesthetic-score cache ─────────────────────────────────────────────────


def test_cache_hit_skips_provider_and_spend(tmp_path, monkeypatch):
    """A cache entry for the exact image bytes (sha1 prefix) must
    short-circuit the provider call and NOT record a budget row.

    This is the load-bearing test for the cost-protection design: a
    photo that recurs across runs pays the provider exactly once."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("LLM_VISION_PROVIDER", "segmind")
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-test-segmind")
    from automation.aesthetic_vision import _cache_key, _cache_path

    raw = b"cached_image_bytes"
    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        _cache_key(raw): {
            "score": 8.5,
            "provider": "segmind",
            "model": "qwen3-vl-flash",
            "ts": "2026-05-18T00:00:00+00:00",
        }
    }))

    # If the cache short-circuit fires, httpx is never invoked.
    with mock.patch("httpx.post", side_effect=AssertionError("provider must not be called")):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(raw)

    assert score is not None and score["score"] == 8.5
    assert _budget_rows(tmp_path) == []  # no spend recorded


def test_cache_miss_records_score_and_persists(monkeypatch):
    """Cache miss → provider called → score returned → cache file
    written with the new entry. The autouse fixture handles tmp_path
    via the _REPO_ROOT monkeypatch — no explicit param needed here."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("LLM_VISION_PROVIDER", "segmind")
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-test-segmind")

    fake_response = mock.MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"visual_appeal": 4.5}'}}]
    }
    raw = b"never_before_seen_bytes"
    with mock.patch("httpx.post", return_value=fake_response):
        from automation.aesthetic_vision import score_aesthetic, _cache_key, _cache_path
        score = score_aesthetic(raw)

    assert score is not None and score["score"] == 4.5
    cache = json.loads(_cache_path().read_text(encoding="utf-8"))
    assert _cache_key(raw) in cache
    entry = cache[_cache_key(raw)]
    assert entry["score"] == 4.5
    assert entry["provider"] == "segmind"
    assert entry["model"] == "qwen3-vl-flash"


def test_cache_corruption_falls_through_to_provider(monkeypatch):
    """A corrupt cache file must NOT crash the booster — it just gets
    treated as empty, and the next successful write overwrites the
    corruption. Validates the fail-soft cache contract. The autouse
    fixture handles tmp_path via the _REPO_ROOT monkeypatch."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("LLM_VISION_PROVIDER", "segmind")
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-test-segmind")
    from automation.aesthetic_vision import _cache_path

    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{ this is not valid json at all")

    fake_response = mock.MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "choices": [{"message": {"content": '{"visual_appeal": 3.0}'}}]
    }
    with mock.patch("httpx.post", return_value=fake_response):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(b"fresh_bytes")

    assert score is not None and score["score"] == 3.0
    # The cache file is now valid JSON (overwritten by the successful call).
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert isinstance(cache, dict) and len(cache) == 1


# ── _parse_response tuple coverage ────────────────────────────────────────


def test_parse_response_extracts_score_and_overlay_true():
    from automation.aesthetic_vision import _parse_response
    score, overlay = _parse_response(
        '{"visual_appeal": 6, "has_marketing_overlay": true, "rationale": "banner"}'
    )
    assert score == 6.0
    assert overlay is True


def test_parse_response_extracts_score_and_overlay_false():
    from automation.aesthetic_vision import _parse_response
    score, overlay = _parse_response(
        '{"visual_appeal": 8, "has_marketing_overlay": false, "rationale": "clean"}'
    )
    assert score == 8.0
    assert overlay is False


def test_parse_response_legacy_response_returns_none_overlay():
    """Older cached responses lack the overlay field; parser returns
    None for it so the picker treats it as 'no signal' rather than
    false-rejecting."""
    from automation.aesthetic_vision import _parse_response
    score, overlay = _parse_response(
        '{"visual_appeal": 7.5, "issues": [], "rationale": "ok"}'
    )
    assert score == 7.5
    assert overlay is None


def test_parse_response_malformed_returns_none_pair():
    from automation.aesthetic_vision import _parse_response
    assert _parse_response("not json at all") == (None, None)
    assert _parse_response("{partial json") == (None, None)


# ── score_aesthetic surfaces overlay field end-to-end ─────────────────────


def test_score_aesthetic_returns_overlay_flagged_response(monkeypatch):
    """A live response with has_marketing_overlay=true must propagate to
    the returned dict so the picker can hard-reject the candidate."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("LLM_VISION_PROVIDER", "segmind")
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-test-segmind")

    fake_response = mock.MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "choices": [{"message": {"content":
            '{"visual_appeal": 6.0, "has_marketing_overlay": true, "rationale": "price banner"}'
        }}]
    }
    with mock.patch("httpx.post", return_value=fake_response):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(b"banner_image_bytes")

    assert score is not None
    assert score["score"] == 6.0
    assert score["has_marketing_overlay"] is True


def test_score_aesthetic_cache_row_with_overlay_propagates(monkeypatch):
    """A cache entry written with has_marketing_overlay=true must
    populate the returned dict so a cached banner-stamped photo doesn't
    bypass the picker filter on subsequent runs."""
    monkeypatch.setenv("LLM_VISION_ENABLED", "true")
    monkeypatch.setenv("LLM_VISION_PROVIDER", "segmind")
    monkeypatch.setenv("SEGMIND_API_KEY", "sk-test-segmind")
    from automation.aesthetic_vision import _cache_key, _cache_path

    raw = b"cached_banner_image"
    cache_path = _cache_path()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        _cache_key(raw): {
            "score": 5.0,
            "has_marketing_overlay": True,
            "provider": "segmind",
            "model": "qwen3-vl-flash",
            "ts": "2026-05-20T00:00:00+00:00",
        }
    }))

    with mock.patch("httpx.post", side_effect=AssertionError("must hit cache")):
        from automation.aesthetic_vision import score_aesthetic
        score = score_aesthetic(raw)

    assert score is not None
    assert score["score"] == 5.0
    assert score["has_marketing_overlay"] is True
