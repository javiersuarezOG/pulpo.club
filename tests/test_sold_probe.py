"""Tests for automation/sold_probe.py (plan 012).

Pure tests with injected fetch / llm_classify fakes — zero network.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.listing_ledger import LedgerEntry  # noqa: E402
from automation.sold_probe import (  # noqa: E402
    classify_page,
    probe_missing_listings,
)

_T0 = "2026-06-01T00:00:00+00:00"
_T_MISS = "2026-06-10T00:00:00+00:00"
_NOW = "2026-06-12T00:00:00+00:00"

_URL = "https://example.com/propiedad/lote-123"


def _entry(status: str = "missing_recently", reason: str | None = None) -> LedgerEntry:
    return LedgerEntry(
        first_seen_at=_T0,
        last_seen_at=_T0,
        consecutive_seen_count=0,
        missing_since=_T_MISS,
        existence_status=status,
        removal_reason=reason,
        removal_detected_at=_NOW if reason else None,
    )


# ── classify_page (pure ladder) ───────────────────────────────────────

def test_classify_404_is_delisted():
    assert classify_page(404, _URL, _URL, None) == "delisted"
    assert classify_page(410, _URL, _URL, "") == "delisted"


def test_classify_200_with_vendido_is_sold():
    html = "<html><body><h1>Lote en El Tunco</h1><p>VENDIDO</p></body></html>"
    assert classify_page(200, _URL, _URL, html) == "sold"


def test_classify_sold_marker_inside_tag_soup_is_sold():
    # marker glued to markup — tag stripping must expose it
    html = "<div class='ribbon'>Under contract</div><p>Great lot</p>"
    assert classify_page(200, _URL, _URL, html) == "sold"


def test_classify_200_clean_is_active():
    html = "<html><body><h1>Lote en El Tunco</h1><p>US$100,000 — 500 m2</p></body></html>"
    assert classify_page(200, _URL, _URL, html) == "active"


def test_classify_redirect_to_root_is_delisted():
    assert classify_page(200, "https://example.com/", _URL, "<html>search</html>") == "delisted"


def test_classify_redirect_to_deep_page_is_not_delisted():
    # listing slug changed but still deep — fall through the ladder
    final = "https://example.com/propiedad/lote-123-renamed"
    assert classify_page(200, final, _URL, "<p>still here</p>") == "active"


def test_classify_403_is_unknown():
    assert classify_page(403, _URL, _URL, "<html>denied</html>") == "unknown"


def test_classify_200_empty_body_is_unknown():
    assert classify_page(200, _URL, _URL, None) == "unknown"


# ── probe_missing_listings ────────────────────────────────────────────

def test_probe_classifies_and_stamps_ledger():
    ledger = {
        "src|sold-1": _entry(),
        "src|gone-1": _entry("stale"),
        "src|live-1": _entry(),
    }
    urls = {
        "src|sold-1": "https://example.com/propiedad/sold-1",
        "src|gone-1": "https://example.com/propiedad/gone-1",
        "src|live-1": "https://example.com/propiedad/live-1",
    }

    def fake_fetch(url: str, source: str):
        if "sold-1" in url:
            return 200, url, "<p>vendido</p>"
        if "gone-1" in url:
            return 404, url, ""
        return 200, url, "<p>lote disponible US$50,000</p>"

    m = probe_missing_listings(
        ledger, urls_by_key=urls, max_probes=10, llm_budget=0,
        now_iso=_NOW, fetch=fake_fetch, llm_classify=None,
    )
    assert m["probed"] == 3
    assert m["sold"] == 1 and m["delisted"] == 1 and m["active"] == 1
    assert m["unknown"] == 0 and m["fetch_errors"] == 0
    assert ledger["src|sold-1"].removal_reason == "sold"
    assert ledger["src|sold-1"].removal_detected_at == _NOW
    assert ledger["src|gone-1"].removal_reason == "delisted"
    # active → left un-classified so a later nightly re-checks
    assert ledger["src|live-1"].removal_reason is None


def test_probe_skips_confirmed_current_and_already_classified():
    ledger = {
        "src|present": LedgerEntry(
            first_seen_at=_T0, last_seen_at=_NOW, consecutive_seen_count=5,
            missing_since=None, existence_status="confirmed_current",
        ),
        "src|done": _entry(reason="delisted"),
    }
    calls: list[str] = []

    def fake_fetch(url: str, source: str):
        calls.append(url)
        return 200, url, ""

    m = probe_missing_listings(
        ledger, urls_by_key={"src|present": _URL, "src|done": _URL},
        max_probes=10, llm_budget=0, now_iso=_NOW,
        fetch=fake_fetch, llm_classify=None,
    )
    assert calls == []
    assert m["probed"] == 0


def test_probe_max_probes_cap_counts_attempts():
    ledger = {f"src|{i}": _entry() for i in range(10)}
    urls = {k: f"https://example.com/propiedad/{k.split('|')[1]}" for k in ledger}
    calls: list[str] = []

    def fake_fetch(url: str, source: str):
        calls.append(url)
        return 200, url, "<p>ok listing</p>"

    m = probe_missing_listings(
        ledger, urls_by_key=urls, max_probes=4, llm_budget=0,
        now_iso=_NOW, fetch=fake_fetch, llm_classify=None,
    )
    assert len(calls) == 4
    assert m["probed"] == 4


def test_probe_fetch_error_leaves_entry_unprobed():
    ledger = {"src|err": _entry()}

    def fake_fetch(url: str, source: str):
        raise TimeoutError("boom")

    m = probe_missing_listings(
        ledger, urls_by_key={"src|err": _URL}, max_probes=10, llm_budget=0,
        now_iso=_NOW, fetch=fake_fetch, llm_classify=None,
    )
    assert m["fetch_errors"] == 1
    assert m["probed"] == 0
    assert ledger["src|err"].removal_reason is None  # retried next nightly


def test_probe_missing_url_is_skipped_not_attempted():
    ledger = {"src|nourl": _entry()}
    m = probe_missing_listings(
        ledger, urls_by_key={}, max_probes=10, llm_budget=0,
        now_iso=_NOW, fetch=lambda u, s: (_ for _ in ()).throw(AssertionError),
        llm_classify=None,
    )
    assert m["skipped_no_url"] == 1
    assert m["probed"] == 0


def test_llm_consulted_only_on_unknown_and_within_budget():
    # 3 unknown-classifying pages, budget of 2 → 2 LLM calls; the third
    # stays "unknown" without a call. A sold page never hits the LLM.
    ledger = {
        "src|u1": _entry(), "src|u2": _entry(), "src|u3": _entry(),
        "src|s1": _entry(),
    }
    urls = {k: f"https://example.com/propiedad/{k.split('|')[1]}" for k in ledger}

    def fake_fetch(url: str, source: str):
        if "s1" in url:
            return 200, url, "<p>VENDIDO</p>"
        return 403, url, "<html>captcha wall</html>"

    llm_inputs: list[str] = []

    def fake_llm(text: str):
        llm_inputs.append(text)
        return "delisted", 0.0002

    m = probe_missing_listings(
        ledger, urls_by_key=urls, max_probes=10, llm_budget=2,
        now_iso=_NOW, fetch=fake_fetch, llm_classify=fake_llm,
    )
    assert m["llm_calls"] == 2
    assert m["cost_usd"] == 0.0004
    assert m["sold"] == 1
    assert m["delisted"] == 2          # both LLM verdicts
    assert m["unknown"] == 1           # budget-exhausted third page
    # metrics add up: every probed page got exactly one terminal state
    assert m["probed"] == m["sold"] + m["delisted"] + m["unknown"] + m["active"]


def test_llm_nonconforming_response_is_unknown():
    ledger = {"src|u1": _entry()}

    def fake_llm(text: str):
        return "expired-nonsense", 0.0001

    m = probe_missing_listings(
        ledger, urls_by_key={"src|u1": _URL}, max_probes=10, llm_budget=5,
        now_iso=_NOW, fetch=lambda u, s: (500, u, ""), llm_classify=fake_llm,
    )
    assert m["unknown"] == 1
    assert ledger["src|u1"].removal_reason == "unknown"


def test_terminal_unknown_is_written_to_ledger():
    """A successfully-fetched-but-unclassifiable page records 'unknown'
    so it can't consume a probe slot every night."""
    ledger = {"src|u1": _entry()}
    m = probe_missing_listings(
        ledger, urls_by_key={"src|u1": _URL}, max_probes=10, llm_budget=0,
        now_iso=_NOW, fetch=lambda u, s: (403, u, "x"), llm_classify=None,
    )
    assert m["unknown"] == 1
    assert ledger["src|u1"].removal_reason == "unknown"
    assert ledger["src|u1"].removal_detected_at == _NOW
