"""Smoke tests for the Xitios scraper (Phase C1 skeleton).

This is the minimum contract every Phase C scraper needs per
``tests/test_source_integration.py``: import-clean, offline returns
>=1 record, fields present.

The skeleton uses a synthesized offline fixture so the offline-mode
contract test passes. Replace the fixture with real HTML captures
during the C1 calibration pass (see ``pulpo/scrapers/xitios.py``
module docstring).
"""
from __future__ import annotations

from pulpo.scrapers.xitios import XitiosScraper


def test_offline_returns_at_least_one_record():
    scraper = XitiosScraper(offline=True)
    records = scraper.crawl(limit=10, offline=True)
    assert len(records) >= 1, "Offline fixture must contain at least one record"


def test_offline_records_carry_required_fields():
    scraper = XitiosScraper(offline=True)
    records = scraper.crawl(limit=10, offline=True)
    for r in records:
        assert r.get("source") == "xitios"
        assert r.get("source_id"), "source_id required"
        assert r.get("url"), "url required"
        assert r.get("price_usd") is not None, "price_usd required"


def test_offline_limit_respected():
    scraper = XitiosScraper(offline=True)
    records = scraper.crawl(limit=2, offline=True)
    assert len(records) <= 2
