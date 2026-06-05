"""Tests for the probe loader + domain resolver (PR-S3b)."""
from __future__ import annotations

import json
from pathlib import Path

from automation.probe_audit import Probe
from automation.probe_loader import (
    _extract_host,
    _strip_www,
    build_domain_to_slug,
    build_matcher_inputs,
    configured_source_domains,
    load_probes_from_file,
    stale_keys_from_ledger,
    zero_yield_domains,
)


# ---------- _strip_www / _extract_host ----------

def test_strip_www_lowercases_and_strips():
    assert _strip_www("WWW.Example.COM") == "example.com"


def test_strip_www_no_www():
    assert _strip_www("example.com") == "example.com"


def test_extract_host_basic():
    assert _extract_host("https://www.example.com/path") == "example.com"


def test_extract_host_with_port():
    assert _extract_host("https://example.com:443/path") == "example.com"


def test_extract_host_empty():
    assert _extract_host("") is None
    assert _extract_host("not a url") is None


# ---------- load_probes_from_file ----------

def test_load_probes_returns_empty_for_missing_file(tmp_path: Path):
    assert load_probes_from_file(tmp_path / "absent.json") == []


def test_load_probes_returns_empty_for_non_list(tmp_path: Path):
    p = tmp_path / "probes.json"
    p.write_text('{"not": "a list"}')
    assert load_probes_from_file(p) == []


def test_load_probes_tolerates_malformed_json(tmp_path: Path):
    p = tmp_path / "probes.json"
    p.write_text("not json {")
    assert load_probes_from_file(p) == []


def test_load_probes_skips_non_dict_rows(tmp_path: Path):
    p = tmp_path / "probes.json"
    p.write_text(json.dumps([
        {"title": "A", "source_url": "https://x.com", "probe_kind": "seed_list"},
        "not a dict",
        42,
        {"title": "B", "source_url": "https://y.com", "probe_kind": "seed_list"},
    ]))
    probes = load_probes_from_file(p)
    assert len(probes) == 2
    assert probes[0].title == "A"
    assert probes[1].title == "B"


def test_load_probes_populates_optional_fields(tmp_path: Path):
    p = tmp_path / "probes.json"
    p.write_text(json.dumps([
        {
            "title": "Beachfront lot",
            "price_usd": 240000,
            "location": "El Tunco",
            "source_url": "https://x.com/listing/1",
            "probe_kind": "seed_list",
        },
    ]))
    probes = load_probes_from_file(p)
    assert probes[0].title == "Beachfront lot"
    assert probes[0].price_usd == 240000.0
    assert probes[0].location == "El Tunco"


def test_load_probes_ignores_underscore_comment_fields(tmp_path: Path):
    """The seed JSON allows _comment fields for human notes — these
    end up ignored by Probe.from_dict (it only reads known keys)."""
    p = tmp_path / "probes.json"
    p.write_text(json.dumps([
        {
            "title": "X",
            "source_url": "https://x.com",
            "probe_kind": "seed_list",
            "_comment": "human note",
        },
    ]))
    probes = load_probes_from_file(p)
    assert len(probes) == 1
    # Probe dataclass doesn't carry _comment; just verify no crash.
    assert isinstance(probes[0], Probe)


# ---------- build_domain_to_slug ----------

def test_build_domain_to_slug_indexes_metadata():
    metadata = {
        "nexo": {"health_probe_url": "https://nexo.com.sv"},
        "remax": {"health_probe_url": "https://www.remax-elsalvador.com"},
    }
    index = build_domain_to_slug(metadata)
    assert index == {
        "nexo.com.sv": "nexo",
        "remax-elsalvador.com": "remax",
    }


def test_build_domain_to_slug_skips_missing_url():
    metadata = {
        "alive": {"health_probe_url": "https://a.com"},
        "deadbeef": {"health_probe_url": None},
        "no_field": {},
    }
    index = build_domain_to_slug(metadata)
    assert index == {"a.com": "alive"}


def test_configured_source_domains_returns_set():
    metadata = {
        "a": {"health_probe_url": "https://a.com"},
        "b": {"health_probe_url": "https://b.com"},
    }
    assert configured_source_domains(metadata) == {"a.com", "b.com"}


# ---------- zero_yield_domains ----------

def _seed_health(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_zero_yield_domains_flags_recent_zero(tmp_path: Path):
    metadata = {"nexo": {"health_probe_url": "https://nexo.com.sv"}}
    p = tmp_path / "health.jsonl"
    _seed_health(p, [
        {"ts": "2026-06-04T00:00:00+00:00", "source": "nexo", "count": 5},
        {"ts": "2026-06-05T00:00:00+00:00", "source": "nexo", "count": 0},
    ])
    domains = zero_yield_domains(
        p,
        scraper_metadata=metadata,
        window_runs=1,
    )
    assert domains == {"nexo.com.sv"}


def test_zero_yield_domains_window_2_requires_both_zero(tmp_path: Path):
    metadata = {"x": {"health_probe_url": "https://x.com"}}
    p = tmp_path / "health.jsonl"
    _seed_health(p, [
        {"ts": "2026-06-04T00:00:00+00:00", "source": "x", "count": 0},
        {"ts": "2026-06-05T00:00:00+00:00", "source": "x", "count": 5},
    ])
    # window_runs=2 → both must be zero → not flagged
    assert zero_yield_domains(p, scraper_metadata=metadata, window_runs=2) == set()


def test_zero_yield_domains_uses_only_most_recent_runs(tmp_path: Path):
    """An old zero followed by a recent positive does NOT flag."""
    metadata = {"x": {"health_probe_url": "https://x.com"}}
    p = tmp_path / "health.jsonl"
    _seed_health(p, [
        {"ts": "2026-06-01T00:00:00+00:00", "source": "x", "count": 0},
        {"ts": "2026-06-05T00:00:00+00:00", "source": "x", "count": 10},
    ])
    assert zero_yield_domains(p, scraper_metadata=metadata, window_runs=1) == set()


def test_zero_yield_domains_missing_file_safe(tmp_path: Path):
    assert zero_yield_domains(
        tmp_path / "absent.jsonl",
        scraper_metadata={},
    ) == set()


def test_zero_yield_domains_skips_slugs_without_probe_url(tmp_path: Path):
    """A slug present in health history but with no health_probe_url
    in metadata produces nothing — there's no domain to alert on."""
    metadata = {"unknown": {"health_probe_url": None}}
    p = tmp_path / "health.jsonl"
    _seed_health(p, [
        {"ts": "2026-06-05T00:00:00+00:00", "source": "unknown", "count": 0},
    ])
    assert zero_yield_domains(p, scraper_metadata=metadata) == set()


# ---------- stale_keys_from_ledger ----------

def test_stale_keys_from_ledger_returns_empty_for_missing(tmp_path: Path):
    assert stale_keys_from_ledger(tmp_path / "absent.json") == set()


def test_stale_keys_from_ledger_reads_stale_entries(tmp_path: Path):
    p = tmp_path / "ledger.json"
    p.write_text(json.dumps({
        "remax|R1": {
            "first_seen_at": "2026-06-01T00:00:00+00:00",
            "last_seen_at": "2026-06-02T00:00:00+00:00",
            "consecutive_seen_count": 0,
            "missing_since": "2026-06-03T00:00:00+00:00",
            "existence_status": "stale",
        },
        "nexo|N1": {
            "first_seen_at": "2026-06-01T00:00:00+00:00",
            "last_seen_at": "2026-06-05T00:00:00+00:00",
            "consecutive_seen_count": 5,
            "missing_since": None,
            "existence_status": "confirmed_current",
        },
    }))
    keys = stale_keys_from_ledger(p)
    assert keys == {"remax|R1"}


# ---------- build_matcher_inputs (integration) ----------

def test_build_matcher_inputs_assembles_all_three(tmp_path: Path):
    metadata = {
        "nexo": {"health_probe_url": "https://nexo.com.sv"},
        "remax": {"health_probe_url": "https://www.remax.com"},
    }
    health_path = tmp_path / "health.jsonl"
    _seed_health(health_path, [
        {"ts": "2026-06-05T00:00:00+00:00", "source": "nexo", "count": 0},
    ])
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps({
        "remax|R1": {
            "first_seen_at": "2026-06-01T00:00:00+00:00",
            "last_seen_at": "2026-06-02T00:00:00+00:00",
            "consecutive_seen_count": 0,
            "missing_since": "2026-06-03T00:00:00+00:00",
            "existence_status": "stale",
        },
    }))

    inputs = build_matcher_inputs(
        scraper_metadata=metadata,
        source_health_history_path=health_path,
        ledger_path=ledger_path,
    )
    assert inputs["configured_sources"] == {"nexo.com.sv", "remax.com"}
    assert inputs["sources_with_zero_yield"] == {"nexo.com.sv"}
    assert inputs["stale_keys"] == {"remax|R1"}
