"""Tests for `pulpo scrape-external` CLI subcommand.

The CLI is the writer side of the cache-fallback pair (the read side
is tested in tests/scrapers/test__scrape_cache.py). It runs daily on
the GCP self-hosted runner and writes web/data/scrape_cache/<slug>.json
files that the main Azure nightly's scrapers consume. These tests
verify the writer's envelope contract and its three failure exits.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.cli import _run_scrape_external  # noqa: E402


class _FakeScraper:
    """Mimics the .crawl(limit, offline) contract every Pulpo scraper
    in pulpo.agents.SOURCES exposes. Tests inject one of these via
    monkeypatching SOURCES so the CLI runs offline without needing
    the real httpx / curl_cffi paths."""

    def __init__(self, slug: str, records: list[dict] | Exception):
        self.slug = slug
        self._behaviour = records
        self.crawl_calls: list[tuple] = []

    def crawl(self, limit: int = 200, offline: bool = False) -> list[dict]:
        self.crawl_calls.append((limit, offline))
        if isinstance(self._behaviour, Exception):
            raise self._behaviour
        return self._behaviour


@pytest.fixture
def fake_sources(monkeypatch):
    """Replace pulpo.agents.SOURCES with a controllable test fleet."""
    from pulpo import agents
    test_sources: dict = {}
    monkeypatch.setattr(agents, "SOURCES", test_sources)
    return test_sources


# ── happy path ────────────────────────────────────────────────────────


def test_writes_cache_file_with_correct_envelope(tmp_path, fake_sources):
    fake_sources["realtyelsalvador"] = _FakeScraper(
        "realtyelsalvador",
        records=[
            {"source_id": "1", "title": "lot 1", "url": "https://example.com/1"},
            {"source_id": "2", "title": "lot 2", "url": "https://example.com/2"},
        ],
    )
    rc = _run_scrape_external([
        "--sources", "realtyelsalvador",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    out_path = tmp_path / "realtyelsalvador.json"
    assert out_path.exists()

    envelope = json.loads(out_path.read_text())
    assert envelope["source"] == "realtyelsalvador"
    assert envelope["count"] == 2
    assert len(envelope["records"]) == 2
    assert envelope["records"][0]["source_id"] == "1"
    # ts must be ISO with Z suffix — the reader (_scrape_cache.py)
    # accepts both Z and offset forms but the writer's canonical
    # output is Z to match the rest of Pulpo's telemetry files.
    assert envelope["ts"].endswith("Z")
    # Format check: YYYY-MM-DDTHH:MM:SSZ
    assert len(envelope["ts"]) == 20
    assert envelope["ts"][10] == "T"


def test_writes_multiple_sources_independently(tmp_path, fake_sources):
    fake_sources["realtyelsalvador"] = _FakeScraper(
        "realtyelsalvador", records=[{"source_id": "r1"}])
    fake_sources["elagente"] = _FakeScraper(
        "elagente", records=[{"source_id": "e1"}, {"source_id": "e2"}])

    rc = _run_scrape_external([
        "--sources", "realtyelsalvador,elagente",
        "--out", str(tmp_path),
    ])
    assert rc == 0

    rty = json.loads((tmp_path / "realtyelsalvador.json").read_text())
    eag = json.loads((tmp_path / "elagente.json").read_text())
    assert rty["count"] == 1 and eag["count"] == 2
    assert rty["source"] == "realtyelsalvador"
    assert eag["source"] == "elagente"


def test_out_dir_is_created_if_missing(tmp_path, fake_sources):
    fake_sources["realtyelsalvador"] = _FakeScraper(
        "realtyelsalvador", records=[{"source_id": "1"}])
    missing = tmp_path / "nested" / "scrape_cache"
    assert not missing.exists()
    rc = _run_scrape_external([
        "--sources", "realtyelsalvador",
        "--out", str(missing),
    ])
    assert rc == 0
    assert (missing / "realtyelsalvador.json").exists()


def test_limit_is_passed_to_crawler(tmp_path, fake_sources):
    fake = _FakeScraper("realtyelsalvador", records=[{"source_id": "1"}])
    fake_sources["realtyelsalvador"] = fake
    _run_scrape_external([
        "--sources", "realtyelsalvador",
        "--out", str(tmp_path),
        "--limit", "42",
    ])
    assert fake.crawl_calls == [(42, False)]


# ── exit-code contract ────────────────────────────────────────────────


def test_exits_1_when_a_source_returns_zero_records(tmp_path, fake_sources):
    """An empty crawl is a regression signal, NOT a success. Exit 1
    so the shim workflow skips the commit step — an empty cache file
    would mask the failure when the main nightly loads it next."""
    fake_sources["realtyelsalvador"] = _FakeScraper(
        "realtyelsalvador", records=[])
    rc = _run_scrape_external([
        "--sources", "realtyelsalvador",
        "--out", str(tmp_path),
    ])
    assert rc == 1
    # And no cache file is written.
    assert not (tmp_path / "realtyelsalvador.json").exists()


def test_exits_1_when_scraper_raises(tmp_path, fake_sources, capsys):
    fake_sources["realtyelsalvador"] = _FakeScraper(
        "realtyelsalvador", records=RuntimeError("connection reset"))
    rc = _run_scrape_external([
        "--sources", "realtyelsalvador",
        "--out", str(tmp_path),
    ])
    assert rc == 1
    # Exception message surfaces so the shim's log includes a
    # debuggable signal.
    assert "connection reset" in capsys.readouterr().err
    assert not (tmp_path / "realtyelsalvador.json").exists()


def test_unknown_source_does_not_block_other_sources(tmp_path, fake_sources):
    """A typo in --sources shouldn't kill the whole run; the other
    sources should still produce their cache files. Overall exit
    is 1 (unknown source is a real config error and must surface)."""
    fake_sources["elagente"] = _FakeScraper(
        "elagente", records=[{"source_id": "e1"}])
    rc = _run_scrape_external([
        "--sources", "elagente,does-not-exist",
        "--out", str(tmp_path),
    ])
    assert rc == 1
    # elagente's cache still landed
    assert (tmp_path / "elagente.json").exists()
    # but the typo's didn't
    assert not (tmp_path / "does-not-exist.json").exists()


def test_exit_2_when_sources_empty():
    """An empty --sources is an argparse-level usage error → exit 2,
    not 1. Distinguishes 'config bug' from 'scrape failure'."""
    rc = _run_scrape_external([
        "--sources", "",
        "--out", "/tmp/whatever",
    ])
    assert rc == 2
