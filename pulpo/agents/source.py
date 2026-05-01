"""Source Protocol — the contract every data-source agent must satisfy."""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class Source(Protocol):
    slug: str

    def crawl(self, limit: int = 30, offline: bool | None = None) -> list[dict]:
        """Return raw listing dicts. offline=None defers to PULPO_OFFLINE env."""
        ...
