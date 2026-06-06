"""news_store — the persisted Weekly News Spotlight artifact.

Covers load/save round-trip, multi-locale preservation, and the
"incomplete entry → None" contract that keeps every shipped spotlight
citing a real outlet.

All tests pass an explicit ``path=`` so they never touch the real
web/data/news_spotlight.json (and so they ignore the conftest's autouse
PULPO_NEWS_SPOTLIGHT_PATH env override).
"""

from __future__ import annotations

import json

from automation.newsletter import news_store
from automation.newsletter.types import NewsSpotlight


def _spot(**overrides) -> NewsSpotlight:
    base = dict(
        title="New coastal road reaches El Zonte",
        paragraph="The widened stretch trims the airport drive.",
        source_name="La Prensa Gráfica",
        source_url="https://www.laprensagrafica.com/elsalvador/road",
        source_date="1 Jun 2026",
        candidates_seen=9,
        llm_cost_usd=0.0031,
    )
    base.update(overrides)
    return NewsSpotlight(**base)


def test_save_then_load_round_trip(tmp_path):
    p = tmp_path / "news_spotlight.json"
    news_store.save_spotlight("en", _spot(), path=p, picked_at="2026-06-01", issue_number=42)

    loaded = news_store.load_spotlight("en", path=p)
    assert loaded is not None
    assert loaded.title == "New coastal road reaches El Zonte"
    assert loaded.source_name == "La Prensa Gráfica"
    assert loaded.source_url.startswith("https://")
    assert loaded.candidates_seen == 9
    assert loaded.llm_cost_usd == 0.0031


def test_save_preserves_other_locales(tmp_path):
    p = tmp_path / "news_spotlight.json"
    news_store.save_spotlight("en", _spot(title="EN story"), path=p)
    news_store.save_spotlight("es", _spot(title="ES historia"), path=p)

    assert news_store.load_spotlight("en", path=p).title == "EN story"
    assert news_store.load_spotlight("es", path=p).title == "ES historia"


def test_save_overwrites_same_locale(tmp_path):
    p = tmp_path / "news_spotlight.json"
    news_store.save_spotlight("en", _spot(title="Old"), path=p)
    news_store.save_spotlight("en", _spot(title="New"), path=p)
    assert news_store.load_spotlight("en", path=p).title == "New"


def test_load_missing_file_returns_none(tmp_path):
    assert news_store.load_spotlight("en", path=tmp_path / "does-not-exist.json") is None


def test_load_missing_locale_returns_none(tmp_path):
    p = tmp_path / "news_spotlight.json"
    news_store.save_spotlight("en", _spot(), path=p)
    assert news_store.load_spotlight("es", path=p) is None


def test_load_malformed_json_returns_none(tmp_path):
    p = tmp_path / "news_spotlight.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert news_store.load_spotlight("en", path=p) is None


def test_load_entry_without_source_url_returns_none(tmp_path):
    """The real-outlet contract: an entry missing source_url is not a
    citable spotlight, so it renders nothing rather than half a story."""
    p = tmp_path / "news_spotlight.json"
    p.write_text(json.dumps({"en": {"title": "t", "paragraph": "p"}}), encoding="utf-8")
    assert news_store.load_spotlight("en", path=p) is None


def test_load_entry_without_title_returns_none(tmp_path):
    p = tmp_path / "news_spotlight.json"
    p.write_text(
        json.dumps({"en": {"paragraph": "p", "source_url": "https://x.com/a"}}),
        encoding="utf-8",
    )
    assert news_store.load_spotlight("en", path=p) is None


def test_save_is_atomic_and_valid_json(tmp_path):
    p = tmp_path / "news_spotlight.json"
    news_store.save_spotlight("en", _spot(), path=p)
    # File parses cleanly and has no leftover temp files in the dir.
    json.loads(p.read_text(encoding="utf-8"))
    assert [f.name for f in tmp_path.iterdir() if f.suffix == ".tmp"] == []


def test_env_path_override(tmp_path, monkeypatch):
    p = tmp_path / "via_env.json"
    news_store.save_spotlight("en", _spot(title="env"), path=p)
    monkeypatch.setenv("PULPO_NEWS_SPOTLIGHT_PATH", str(p))
    # No explicit path → resolves via env.
    assert news_store.load_spotlight("en").title == "env"
