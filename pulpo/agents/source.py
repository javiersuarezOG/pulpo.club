"""Source Protocol — the contract every data-source agent must satisfy."""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class Source(Protocol):
    slug: str
    # ISO-3166-1 alpha-2 country code (uppercase). Every scraper MUST
    # declare which country its listings belong to. The nightly
    # orchestrator scopes runs by country via this attribute; the
    # multi-country test guard (tests/test_country_manifest.py) refuses
    # to start if a registered Source omits it.
    country: str

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        """Return raw listing dicts. offline=None defers to PULPO_OFFLINE env."""
        ...
