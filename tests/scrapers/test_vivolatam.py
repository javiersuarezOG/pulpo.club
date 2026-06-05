"""Smoke test for Phase C vivolatam scraper [DRAFT skeleton]."""
from __future__ import annotations

from pulpo.scrapers.vivolatam import VivolatamScraper


def test_offline_returns_at_least_one_record():
    records = VivolatamScraper(offline=True).crawl(limit=10, offline=True)
    assert len(records) >= 1


def test_offline_records_carry_required_fields():
    for r in VivolatamScraper(offline=True).crawl(limit=10, offline=True):
        assert r.get("source") == "vivolatam"
        assert r.get("source_id")
        assert r.get("url")
        assert r.get("price_usd") is not None
