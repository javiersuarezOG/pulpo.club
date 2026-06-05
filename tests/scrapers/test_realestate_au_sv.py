"""Smoke test for Phase C realestate_au_sv scraper."""
from __future__ import annotations

from pulpo.scrapers.realestate_au_sv import RealestateAuSvScraper


def test_offline_returns_at_least_one_record():
    records = RealestateAuSvScraper(offline=True).crawl(limit=10, offline=True)
    assert len(records) >= 1


def test_offline_records_carry_required_fields():
    for r in RealestateAuSvScraper(offline=True).crawl(limit=10, offline=True):
        assert r.get("source") == "realestate_au_sv"
        assert r.get("source_id")
        assert r.get("url")
        assert r.get("price_usd") is not None
