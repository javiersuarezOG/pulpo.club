"""Agent registries for pulpo.club.

Three registries: SOURCES, ENRICHERS, RANKER_LEGS.
Each is a plain dict keyed by slug. Add new agents with register().
"""
from __future__ import annotations
from typing import Any

SOURCES: dict[str, Any] = {}
ENRICHERS: dict[str, Any] = {}
RANKER_LEGS: dict[str, Any] = {}


def register(registry: dict, slug: str, obj: Any) -> None:
    """Register obj under slug in registry. Raises if slug already taken."""
    if slug in registry:
        raise ValueError(f"Slug '{slug}' already registered in {registry}")
    registry[slug] = obj
