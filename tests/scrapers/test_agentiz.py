"""Smoke test for Phase C2 Agentiz scraper [DRAFT skeleton]."""
from __future__ import annotations

from pulpo.scrapers.agentiz import AgentizScraper


def test_offline_returns_at_least_one_record():
    records = AgentizScraper(offline=True).crawl(limit=10, offline=True)
    assert len(records) >= 1


def test_offline_records_carry_required_fields():
    for r in AgentizScraper(offline=True).crawl(limit=10, offline=True):
        assert r.get("source") == "agentiz"
        assert r.get("source_id")
        assert r.get("url")
        assert r.get("price_usd") is not None
