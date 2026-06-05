"""Smoke tests for the Xitios scraper (Phase C1 — calibrated)."""
from __future__ import annotations

from pulpo.scrapers.xitios import XitiosScraper


def test_offline_returns_at_least_one_record():
    records = XitiosScraper(offline=True).crawl(limit=10, offline=True)
    assert len(records) >= 1


def test_offline_records_carry_required_fields():
    for r in XitiosScraper(offline=True).crawl(limit=10, offline=True):
        assert r.get("source") == "xitios"
        assert r.get("source_id")
        assert r.get("url")
        assert r.get("price_usd") is not None


def test_offline_limit_respected():
    records = XitiosScraper(offline=True).crawl(limit=2, offline=True)
    assert len(records) <= 2
