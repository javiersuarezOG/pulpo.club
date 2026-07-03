"""scripts/refresh_news_spotlight.refresh — the nightly artifact writer.

Covers the three per-locale outcomes that guarantee every Pro email keeps
a real, cited article:

  • fresh LLM pick            → refreshed (artifact overwritten)
  • no fresh pick + prior seed → carried_forward (prior article kept)
  • no fresh pick + no seed    → no_seed (cold start; canary's job)
  • fetch raises               → carried_forward / no_seed, never crashes
"""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from automation.newsletter import news_store
from automation.newsletter.types import NewsSpotlight

# Load the script module by path (scripts/ isn't a package).
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "refresh_news_spotlight.py"
_spec = importlib.util.spec_from_file_location("refresh_news_spotlight", _SCRIPT)
refresh_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(refresh_mod)

NOW = datetime(2026, 6, 6, 12, 0, tzinfo=timezone.utc)


def _spot(**overrides) -> NewsSpotlight:
    base = dict(
        title="Fresh pick",
        paragraph="Body.",
        source_name="El Diario de Hoy",
        source_url="https://www.elsalvador.com/fresh",
        source_date="6 Jun 2026",
        candidates_seen=11,
        llm_cost_usd=0.004,
    )
    base.update(overrides)
    return NewsSpotlight(**base)


def test_fresh_pick_is_written(tmp_path):
    p = tmp_path / "news_spotlight.json"
    results = refresh_mod.refresh(
        locales=("en",),
        fetch_fn=lambda *, locale: _spot(title=f"pick-{locale}"),
        now=NOW,
        path=p,
        log=lambda *_: None,
    )
    assert results == {"en": refresh_mod.REFRESHED}
    loaded = news_store.load_spotlight("en", path=p)
    assert loaded.title == "pick-en"


def test_no_pick_carries_forward_prior(tmp_path):
    p = tmp_path / "news_spotlight.json"
    # Seed a prior real article.
    news_store.save_spotlight("en", _spot(title="last week's real article"), path=p)

    results = refresh_mod.refresh(
        locales=("en",),
        fetch_fn=lambda *, locale: None,  # slow news week
        now=NOW,
        path=p,
        log=lambda *_: None,
    )
    assert results == {"en": refresh_mod.CARRIED_FORWARD}
    # The prior article survives untouched.
    assert news_store.load_spotlight("en", path=p).title == "last week's real article"


def test_no_pick_no_seed_reports_no_seed(tmp_path):
    p = tmp_path / "news_spotlight.json"
    results = refresh_mod.refresh(
        locales=("en",),
        fetch_fn=lambda *, locale: None,
        now=NOW,
        path=p,
        log=lambda *_: None,
    )
    assert results == {"en": refresh_mod.NO_SEED}
    assert news_store.load_spotlight("en", path=p) is None


def test_fetch_exception_carries_forward(tmp_path):
    p = tmp_path / "news_spotlight.json"
    news_store.save_spotlight("en", _spot(title="survivor"), path=p)

    def _boom(*, locale):
        raise RuntimeError("deepseek down")

    results = refresh_mod.refresh(
        locales=("en",),
        fetch_fn=_boom,
        now=NOW,
        path=p,
        log=lambda *_: None,
    )
    assert results == {"en": refresh_mod.CARRIED_FORWARD}
    assert news_store.load_spotlight("en", path=p).title == "survivor"


def test_per_locale_independent(tmp_path):
    """EN refreshes, ES carries forward — independently, in one run."""
    p = tmp_path / "news_spotlight.json"
    news_store.save_spotlight("es", _spot(title="es prior"), path=p)

    def _fetch(*, locale):
        return _spot(title="en fresh") if locale == "en" else None

    results = refresh_mod.refresh(
        locales=("en", "es"),
        fetch_fn=_fetch,
        now=NOW,
        path=p,
        log=lambda *_: None,
    )
    assert results == {"en": refresh_mod.REFRESHED, "es": refresh_mod.CARRIED_FORWARD}
    assert news_store.load_spotlight("en", path=p).title == "en fresh"
    assert news_store.load_spotlight("es", path=p).title == "es prior"


def test_picked_at_stamped(tmp_path):
    p = tmp_path / "news_spotlight.json"
    refresh_mod.refresh(
        locales=("en",),
        fetch_fn=lambda *, locale: _spot(),
        now=NOW,
        path=p,
        log=lambda *_: None,
    )
    import json
    entry = json.loads(p.read_text(encoding="utf-8"))["en"]
    assert entry["picked_at"] == "2026-06-06"
