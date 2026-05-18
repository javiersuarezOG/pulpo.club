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
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "QWEN_BASE_URL",
        "QWEN_VISION_MODEL",
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

    assert score == 7.5
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
