"""
Tests for automation/llm_enrichment.py — pins the single-call DeepSeek
enrichment contract.

Stub `client` class (no openai library mocking) injected via the public
API's `client=` kwarg, mirroring the pattern in tests/test_ai_enrichment.py.
The stub records every call so we can assert "exactly one API call per
eligible listing" — the whole point of the refactor.

Coverage:
- eligibility: skip when any of the 4 target fields is set
- single-call invariant
- the three fail-closed gates: finish_reason=length, json_parse, schema_invalid
- atomic save (no partial application)
- idempotency: sidecar rehydration, second run = zero API calls
- telemetry: per-decision counters and JSONL audit log
- DEEPSEEK_API_TOKEN missing → graceful skip
- global error short-circuits remaining API calls
"""
from __future__ import annotations
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.llm_enrichment import (   # noqa: E402
    enrich_listings,
    _is_global_error,
)
from automation.llm_enrichment_schema import (   # noqa: E402
    DEFAULT_SCHEMA,
)


# ── stub OpenAI-shaped client ──────────────────────────────────────────

@dataclass
class _Usage:
    prompt_tokens:     int = 600
    completion_tokens: int = 200


@dataclass
class _Message:
    content: str = ""


@dataclass
class _Choice:
    message:       _Message = field(default_factory=_Message)
    finish_reason: str      = "stop"


@dataclass
class _Response:
    choices: list = field(default_factory=list)
    usage:   _Usage = field(default_factory=_Usage)


class _StubCompletions:
    """Stand-in for `client.chat.completions`. Programmable per call.

    `responses` is a list — popped left-to-right. Each entry can be:
      - a _Response object (returned verbatim)
      - a dict (auto-built into a _Response)
      - an Exception class or instance (raised)
    """
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            return _build_response(_OK_JSON)
        nxt = self._responses.pop(0)
        if isinstance(nxt, type) and issubclass(nxt, BaseException):
            raise nxt("stub error")
        if isinstance(nxt, BaseException):
            raise nxt
        if isinstance(nxt, _Response):
            return nxt
        if isinstance(nxt, dict):
            return _build_response(nxt)
        raise TypeError(f"unsupported stub response: {nxt!r}")


class _StubClient:
    def __init__(self, responses: list | None = None):
        self.chat = type("_Chat", (), {})()
        self.chat.completions = _StubCompletions(responses or [])


_OK_JSON = {
    # PR-7.5 — bilingual {en, es} shape on title/description/usps + url_language
    "title": {
        "en": "Beachfront 5,000 m² lot in El Tunco",
        "es": "Terreno frente al mar de 5,000 m² en El Tunco",
    },
    "description": {
        "en": ("A flat, well-positioned parcel near the surf break, "
               "with paved access and ocean views — well-suited for "
               "a small boutique build or buy-and-hold."),
        "es": ("Un terreno plano y bien posicionado cerca del rompiente, "
               "con acceso pavimentado y vista al mar — ideal para "
               "construcción boutique o inversión a largo plazo."),
    },
    "usps": [
        {"en": "🏖 Beachfront access", "es": "🏖 Acceso a la playa"},
        {"en": "📐 Flat terrain",      "es": "📐 Terreno plano"},
        {"en": "🛣 Paved road",        "es": "🛣 Camino pavimentado"},
    ],
    "url_language": "en",
    "latlong":     {"lat": 13.4912, "lng": -89.3818,
                    "source": "estimated",
                    "reference": "near El Tunco, La Libertad",
                    "confidence": "medium"},
}


def _build_response(payload: dict | str, finish_reason: str = "stop",
                    tokens_in: int = 600, tokens_out: int = 200) -> _Response:
    """Wrap a JSON dict (or raw string) into a fake API response."""
    content = payload if isinstance(payload, str) else json.dumps(payload)
    return _Response(
        choices=[_Choice(message=_Message(content=content),
                         finish_reason=finish_reason)],
        usage=_Usage(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )


# ── listing factory ────────────────────────────────────────────────────

def _li(**overrides) -> dict:
    base = {
        "source":    "goodlife",
        "source_id": "GL-001",
        "title":     "Raw scraped title",
        "description": "Lote de 5,000 m² frente al mar en El Tunco, "
                       "con acceso pavimentado y vistas al océano.",
        "title_canonical":             None,
        "short_description_canonical": None,
        "reasons_to_buy":              [],
        # PR-7.5 — bilingual schema added url_language as a target field.
        "url_language":                None,
        "lat":                         None,
        "lng":                         None,
        "geocoding_confidence":        None,
        "geocoding_source":            None,
        "geocoding_reference":         None,
        "enriched_at":                 None,
        "enrichment_model":            None,
    }
    base.update(overrides)
    return base


# ── eligibility — proves the hard rule from the spec ──────────────────

def test_eligibility_skips_when_title_canonical_set(tmp_path):
    li = _li(title_canonical="Already enriched")
    client = _StubClient(responses=[_OK_JSON])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["skipped"] == 1
    assert metrics["enriched"] == 0
    assert metrics["skip_reasons"] == {"already_has_title_canonical": 1}
    assert client.chat.completions.calls == []   # ZERO API calls


def test_eligibility_skips_when_lat_set(tmp_path):
    """Mapbox-grandfathered listings (lat already set) skip the LLM."""
    li = _li(lat=13.5)
    client = _StubClient(responses=[_OK_JSON])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["skipped"] == 1
    assert metrics["skip_reasons"] == {"already_has_latlong": 1}
    assert client.chat.completions.calls == []


def test_eligibility_skips_when_reasons_to_buy_nonempty(tmp_path):
    li = _li(reasons_to_buy=["already here"])
    client = _StubClient(responses=[_OK_JSON])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["skipped"] == 1
    assert metrics["skip_reasons"] == {"already_has_reasons_to_buy": 1}


# ── single-call invariant — the WHOLE point of the refactor ───────────

def test_single_call_per_eligible_listing(tmp_path):
    listings = [_li(source_id=f"GL-{i:03d}") for i in range(5)]
    client = _StubClient(responses=[_OK_JSON] * 5)
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["enriched"] == 5
    # FIVE calls, not 15 — proves we don't fan out per-field.
    assert len(client.chat.completions.calls) == 5
    # And every call carries response_format=json_object
    for call in client.chat.completions.calls:
        assert call["response_format"] == {"type": "json_object"}
    # And the description appears in the user message exactly once
    for call in client.chat.completions.calls:
        user_msg = next(m for m in call["messages"] if m["role"] == "user")
        # The Spanish source description should appear verbatim
        assert "5,000 m²" in user_msg["content"]


# ── fail-closed gates ─────────────────────────────────────────────────

def test_finish_reason_length_treated_as_failure_no_partial_save(tmp_path):
    li = _li()
    truncated = _build_response(_OK_JSON, finish_reason="length")
    client = _StubClient(responses=[truncated])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["failed"] == 1
    assert metrics["enriched"] == 0
    assert metrics["failure_reasons"] == {"finish_reason_length": 1}
    # No partial save — listing untouched
    assert li["title_canonical"] is None
    assert li["short_description_canonical"] is None
    assert li["reasons_to_buy"] == []
    assert li["lat"] is None


def test_malformed_json_treated_as_failure(tmp_path):
    li = _li()
    client = _StubClient(responses=[
        _build_response("{broken json, not closed", finish_reason="stop")
    ])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["failed"] == 1
    assert metrics["failure_reasons"] == {"json_parse": 1}
    assert li["title_canonical"] is None


def test_missing_required_key_treated_as_failure(tmp_path):
    li = _li()
    bad = {**_OK_JSON}
    del bad["latlong"]
    client = _StubClient(responses=[bad])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["failed"] == 1
    reason = next(iter(metrics["failure_reasons"]))
    assert reason.startswith("schema_invalid:missing:latlong")
    assert li["title_canonical"] is None


def test_wrong_type_for_usps_treated_as_failure(tmp_path):
    li = _li()
    bad = {**_OK_JSON, "usps": "not a list"}
    client = _StubClient(responses=[bad])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["failed"] == 1
    reason = next(iter(metrics["failure_reasons"]))
    assert reason.startswith("schema_invalid:invalid:usps")
    assert li["reasons_to_buy"] == []


def test_invalid_latlong_outside_sv_bbox_treated_as_failure(tmp_path):
    li = _li()
    bad = {**_OK_JSON, "latlong": {**_OK_JSON["latlong"], "lat": 0.0}}
    client = _StubClient(responses=[bad])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["failed"] == 1
    assert li["lat"] is None


# ── successful enrichment + atomic save ───────────────────────────────

def test_successful_enrichment_writes_all_fields_atomically(tmp_path):
    li = _li()
    client = _StubClient(responses=[_OK_JSON])
    metrics = enrich_listings([li], tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["enriched"] == 1
    # PR-7.5 — bilingual {en, es} dict shape
    assert li["title_canonical"] == _OK_JSON["title"]
    assert li["short_description_canonical"]["en"].startswith("A flat, well-positioned")
    assert li["short_description_canonical"]["es"].startswith("Un terreno plano")
    assert li["reasons_to_buy"] == _OK_JSON["usps"]
    assert li["url_language"] == "en"
    assert li["lat"] == 13.4912
    assert li["lng"] == -89.3818
    assert li["geocoding_confidence"] == "medium"
    assert li["geocoding_source"] == "estimated"
    assert li["geocoding_reference"] == "near El Tunco, La Libertad"


def test_enrichment_stamps_enriched_at_and_enrichment_model(tmp_path):
    li = _li()
    client = _StubClient(responses=[_OK_JSON])
    enrich_listings([li], tmp_path / "side.json",
                    tmp_path / "log.jsonl",
                    client=client)
    assert li["enriched_at"] is not None
    assert "T" in li["enriched_at"]              # ISO8601 looks right
    assert li["enrichment_model"] == "deepseek-chat"


# ── idempotency — sidecar rehydration ─────────────────────────────────

def test_idempotency_second_run_uses_sidecar_no_api_call(tmp_path):
    sidecar = tmp_path / "side.json"
    log = tmp_path / "log.jsonl"

    # First run — actually calls the stub
    li1 = _li()
    client1 = _StubClient(responses=[_OK_JSON])
    m1 = enrich_listings([li1], sidecar, log, client=client1)
    assert m1["enriched"] == 1
    assert sidecar.exists()

    # Second run — same listing, fresh client whose calls would explode
    li2 = _li()
    client2 = _StubClient(responses=[ValueError])  # would raise if called
    m2 = enrich_listings([li2], sidecar, log, client=client2)
    assert m2["cache_hits"] == 1
    assert m2["enriched"] == 0
    assert client2.chat.completions.calls == []
    # And the listing got fully rehydrated from the sidecar
    assert li2["title_canonical"] == _OK_JSON["title"]
    assert li2["lat"] == 13.4912
    assert li2["enrichment_model"] == "deepseek-chat"


def test_sidecar_persists_validated_payload(tmp_path):
    sidecar = tmp_path / "side.json"
    li = _li()
    client = _StubClient(responses=[_OK_JSON])
    enrich_listings([li], sidecar, tmp_path / "log.jsonl", client=client)
    saved = json.loads(sidecar.read_text(encoding="utf-8"))
    entry = saved["goodlife|GL-001"]
    assert entry["title_canonical"] == _OK_JSON["title"]
    assert entry["lat"] == 13.4912
    assert entry["model"] == "deepseek-chat"
    assert entry["finish_reason"] == "stop"
    assert entry["schema_version"] == DEFAULT_SCHEMA.schema_version
    assert "tokens_in" in entry and "tokens_out" in entry and "cost_usd" in entry


# ── telemetry — JSONL audit log ───────────────────────────────────────

def test_audit_log_jsonl_appended_per_decision(tmp_path):
    log = tmp_path / "log.jsonl"
    listings = [
        _li(source_id="GL-OK"),                            # → enriched
        _li(source_id="GL-SKIP", title_canonical="set"),    # → skipped
    ]
    client = _StubClient(responses=[_OK_JSON])
    enrich_listings(listings, tmp_path / "side.json", log, client=client)
    lines = [json.loads(ln) for ln in log.read_text().splitlines() if ln.strip()]
    decisions = sorted(ev["decision"] for ev in lines)
    assert decisions == ["enriched", "skipped"]
    enriched = next(ev for ev in lines if ev["decision"] == "enriched")
    assert enriched["model"] == "deepseek-chat"
    assert enriched["finish_reason"] == "stop"
    assert "tokens_in" in enriched and "latency_ms" in enriched


def test_metrics_track_counters_and_reasons(tmp_path):
    listings = [
        _li(source_id="A"),                                 # enriched
        _li(source_id="B", title_canonical="set"),          # skipped: title
        _li(source_id="C", lat=13.5),                       # skipped: latlong
        _li(source_id="D"),                                 # failed: malformed
    ]
    client = _StubClient(responses=[
        _OK_JSON,
        _build_response("{broken", finish_reason="stop"),   # for D
    ])
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client)
    assert metrics["enriched"] == 1
    assert metrics["skipped"] == 2
    assert metrics["failed"] == 1
    assert metrics["skip_reasons"] == {
        "already_has_title_canonical": 1,
        "already_has_latlong":         1,
    }
    assert metrics["failure_reasons"] == {"json_parse": 1}
    assert metrics["cost_usd"] > 0
    assert len(metrics["latency_ms"]) == 1   # only the one successful call


# ── graceful degradation ──────────────────────────────────────────────

def test_skipped_no_token_when_DEEPSEEK_API_TOKEN_unset(tmp_path):
    li = _li()
    with patch.dict("os.environ", {}, clear=True):
        # No client passed → enrich_listings tries to build one and bails
        metrics = enrich_listings([li], tmp_path / "side.json",
                                  tmp_path / "log.jsonl")
    assert metrics["skipped_no_token"] is True
    assert metrics["enriched"] == 0
    assert li["title_canonical"] is None


def test_global_error_short_circuits_remaining_calls(tmp_path):
    """Auth failure on first call → remaining listings get skipped, not retried.

    Tested with `max_workers=1` because the strict 'no further calls' guarantee
    only holds for the sequential code path. The parallel path makes the
    weaker (still useful) guarantee that no NEW submissions happen after the
    global error is detected, but in-flight ones from the priming batch
    complete — see `test_global_error_in_parallel_stops_new_submissions`.
    """
    listings = [_li(source_id=f"GL-{i}") for i in range(3)]

    class AuthenticationError(Exception):
        pass

    client = _StubClient(responses=[
        AuthenticationError,   # first call: global error
        _OK_JSON,              # would succeed but should never run
        _OK_JSON,              # ditto
    ])
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client, max_workers=1)
    # Only the first listing actually called the API
    assert len(client.chat.completions.calls) == 1
    assert metrics["failed"] == 1
    assert metrics["global_error_seen"] == "AuthenticationError"
    # No partial save on listing 0; listings 1+2 untouched
    for li in listings:
        assert li["title_canonical"] is None


def test_max_listings_caps_api_calls(tmp_path):
    listings = [_li(source_id=f"GL-{i}") for i in range(5)]
    client = _StubClient(responses=[_OK_JSON] * 5)
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client, max_listings=2)
    assert len(client.chat.completions.calls) == 2
    assert metrics["enriched"] == 2


# ── parallelisation + deadline soft-fail (PRD WS2 nightly stability) ──


def test_max_workers_one_preserves_sequential_path(tmp_path):
    """max_workers=1 → strictly sequential; same call ordering as the legacy
    pre-parallel implementation."""
    listings = [_li(source_id=f"GL-{i}") for i in range(4)]
    client = _StubClient(responses=[_OK_JSON] * 4)
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client, max_workers=1)
    assert metrics["enriched"] == 4
    # Sequential ordering: call 0 carries GL-0's prompt, call 3 carries GL-3's
    bodies = [c["messages"][1]["content"] for c in client.chat.completions.calls]
    assert all("Lote de 5,000 m²" in b for b in bodies)


def test_parallel_pool_processes_all_eligible_listings(tmp_path):
    """max_workers=4 → all 8 listings still get enriched, sidecar grows by 8."""
    listings = [_li(source_id=f"GL-{i}") for i in range(8)]
    client = _StubClient(responses=[_OK_JSON] * 8)
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client, max_workers=4)
    assert metrics["enriched"] == 8
    assert len(client.chat.completions.calls) == 8
    sidecar = json.loads((tmp_path / "side.json").read_text())
    assert len(sidecar) == 8
    assert all(li.get("title_canonical") for li in listings)


def test_global_error_in_parallel_stops_new_submissions(tmp_path):
    """Parallel-path semantics: in-flight calls from the priming batch may
    complete after the global error is detected, but NO new ones get
    submitted. With 8 listings and pool=2, exactly 2 land in-flight; the
    remaining 6 are deferred. Counts the legacy strict-ordering test
    (max_workers=1) as the sequential complement."""
    listings = [_li(source_id=f"GL-{i}") for i in range(8)]

    class AuthenticationError(Exception):
        pass

    # First two responses: one auth error, one success. Anything beyond
    # that is the test bug — no further calls should ever happen.
    client = _StubClient(responses=[
        AuthenticationError,
        _OK_JSON,
        # Padding to detect over-submission. If the test ever triggers
        # any of these, the global short-circuit broke.
    ] + [_OK_JSON] * 20)

    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client, max_workers=2)
    # Pool primed with 2 calls → both land. After the auth-error result
    # is processed, no new submissions go out.
    assert len(client.chat.completions.calls) == 2
    assert metrics["global_error_seen"] == "AuthenticationError"


def test_deadline_passed_in_advance_skips_all_eligible(tmp_path):
    """deadline already in the past → the parallel loop submits nothing,
    every eligible listing is counted as deadline_skipped."""
    import time
    listings = [_li(source_id=f"GL-{i}") for i in range(5)]
    client = _StubClient(responses=[_OK_JSON] * 5)
    past = time.monotonic() - 1.0   # already expired
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client, max_workers=4, deadline=past)
    assert len(client.chat.completions.calls) == 0
    assert metrics["enriched"] == 0
    assert metrics["deadline_skipped"] == 5
    assert metrics["eligible"] == 5   # they passed eligibility, just got cut off


def test_deadline_in_sequential_path_skips_remaining(tmp_path):
    """Same deadline contract on the max_workers=1 path."""
    import time
    listings = [_li(source_id=f"GL-{i}") for i in range(3)]
    client = _StubClient(responses=[_OK_JSON] * 3)
    past = time.monotonic() - 1.0
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl",
                              client=client, max_workers=1, deadline=past)
    assert len(client.chat.completions.calls) == 0
    assert metrics["deadline_skipped"] == 3


def test_concurrency_default_from_env_var(tmp_path, monkeypatch):
    """When max_workers is None (caller didn't specify), the env var
    PULPO_LLM_CONCURRENCY drives the default."""
    monkeypatch.setenv("PULPO_LLM_CONCURRENCY", "1")
    listings = [_li(source_id=f"GL-{i}") for i in range(3)]
    client = _StubClient(responses=[_OK_JSON] * 3)
    enrich_listings(listings, tmp_path / "side.json",
                    tmp_path / "log.jsonl", client=client)
    assert len(client.chat.completions.calls) == 3


def test_concurrency_default_when_env_unset(tmp_path, monkeypatch):
    """No env var, no explicit max_workers → default kicks in (8). With
    only 3 listings this still works fine; we just assert it doesn't
    crash and the work completes."""
    monkeypatch.delenv("PULPO_LLM_CONCURRENCY", raising=False)
    listings = [_li(source_id=f"GL-{i}") for i in range(3)]
    client = _StubClient(responses=[_OK_JSON] * 3)
    metrics = enrich_listings(listings, tmp_path / "side.json",
                              tmp_path / "log.jsonl", client=client)
    assert metrics["enriched"] == 3


# ── _is_global_error classifier ────────────────────────────────────────

def test_global_error_catches_authentication():
    class AuthenticationError(Exception):
        pass
    assert _is_global_error(AuthenticationError("bad key"))


def test_global_error_catches_quota_exhausted():
    assert _is_global_error(Exception("insufficient_quota"))


def test_global_error_does_not_catch_transient():
    class TimeoutError_(Exception):
        pass
    assert not _is_global_error(TimeoutError_("read timeout"))
