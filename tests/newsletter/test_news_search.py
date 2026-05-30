"""Tests for the Weekly News Spotlight RSS fetcher.

Covers:
  • Happy-path RSS parse + keyword filter
  • Date-window cutoff (older articles dropped)
  • Per-outlet failure isolation (one bad feed doesn't break the run)
  • Malformed XML is swallowed
  • Keyword-filter off returns everything in the window
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from automation.newsletter import news_search


def _make_feed_xml(items: list[dict]) -> bytes:
    """Build a minimal RSS 2.0 feed from a list of {title, link, pub_date, description}."""
    item_xml = ""
    for it in items:
        item_xml += f"""
        <item>
          <title>{it.get('title', '')}</title>
          <link>{it.get('link', '')}</link>
          <pubDate>{it.get('pub_date', '')}</pubDate>
          <description>{it.get('description', '')}</description>
        </item>"""
    return (
        f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0"><channel>
          <title>Test Feed</title>{item_xml}
        </channel></rss>"""
    ).encode("utf-8")


def _rfc2822(dt: datetime) -> str:
    """Format datetime per RFC 2822, the RSS pubDate convention."""
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def test_fetch_candidates_happy_path():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(days=1)
    fresh_irrelevant = now - timedelta(days=2)

    feed = _make_feed_xml([
        {
            "title": "Nuevo puente sobre el río Lempa",
            "link": "https://www.elsalvador.com/noticias/nacional/puente-lempa/",
            "pub_date": _rfc2822(fresh),
            "description": "El gobierno anunció hoy la construcción del puente sobre el río Lempa.",
        },
        {
            "title": "Resultados deportivos",
            "link": "https://www.elsalvador.com/deportes/futbol/",
            "pub_date": _rfc2822(fresh_irrelevant),
            "description": "Resumen de la jornada deportiva.",
        },
    ])

    fake_fetch = lambda url, timeout: feed  # noqa: E731

    candidates = news_search.fetch_candidates(
        whitelist={"El Diario de Hoy": "https://example.com/feed"},
        fetcher=fake_fetch,
        now=now,
    )

    # The Lempa article matches (keyword: "lempa" + "puente"). The
    # sports article doesn't match any keyword and is dropped.
    assert len(candidates) == 1
    assert candidates[0].source_name == "El Diario de Hoy"
    assert candidates[0].source_url == "https://www.elsalvador.com/noticias/nacional/puente-lempa/"
    assert "Lempa" in candidates[0].title


def test_fetch_candidates_drops_articles_outside_window():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    too_old = now - timedelta(days=14)  # outside default 7-day window
    fresh = now - timedelta(days=3)

    feed = _make_feed_xml([
        {
            "title": "Vieja noticia de Surf City",
            "link": "https://www.elsalvador.com/old/",
            "pub_date": _rfc2822(too_old),
            "description": "Old Surf City news.",
        },
        {
            "title": "Surf City 2 — nueva concesión hotelera",
            "link": "https://www.elsalvador.com/new/",
            "pub_date": _rfc2822(fresh),
            "description": "Nueva concesión turística en Surf City 2.",
        },
    ])
    fake_fetch = lambda url, timeout: feed  # noqa: E731

    candidates = news_search.fetch_candidates(
        whitelist={"El Diario de Hoy": "https://example.com/feed"},
        fetcher=fake_fetch,
        now=now,
    )
    # Only the fresh article survives.
    assert len(candidates) == 1
    assert candidates[0].title == "Surf City 2 — nueva concesión hotelera"


def test_fetch_candidates_isolates_per_outlet_failures():
    """One outlet returning garbage or raising shouldn't break the run."""
    now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(days=1)

    good_feed = _make_feed_xml([{
        "title": "Playa El Tunco — nueva inversión",
        "link": "https://laprensagrafica.com/playa-tunco/",
        "pub_date": _rfc2822(fresh),
        "description": "Inversión turística en la playa.",
    }])

    def fake_fetch(url: str, timeout: int) -> bytes:
        if "broken" in url:
            raise ConnectionError("simulated outlet down")
        if "malformed" in url:
            return b"<this is not valid xml"
        return good_feed

    candidates = news_search.fetch_candidates(
        whitelist={
            "Broken Outlet": "https://broken.example.com/feed",
            "Malformed Outlet": "https://malformed.example.com/feed",
            "Good Outlet": "https://good.example.com/feed",
        },
        fetcher=fake_fetch,
        now=now,
    )
    assert len(candidates) == 1
    assert candidates[0].source_name == "Good Outlet"


def test_fetch_candidates_keyword_filter_off_returns_all_in_window():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(days=2)
    feed = _make_feed_xml([
        {
            "title": "Random sports news",
            "link": "https://elmundo.sv/sports/",
            "pub_date": _rfc2822(fresh),
            "description": "Totally unrelated.",
        },
    ])
    fake_fetch = lambda url, timeout: feed  # noqa: E731

    candidates = news_search.fetch_candidates(
        whitelist={"El Mundo": "https://example.com/feed"},
        fetcher=fake_fetch,
        now=now,
        keyword_filter=False,
    )
    # Filter off → keyword-irrelevant article still surfaces.
    assert len(candidates) == 1


def test_fetch_candidates_caps_at_max():
    """fetch_candidates returns at most news_search.MAX_CANDIDATES per call."""
    now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    # Build a feed with 30 relevant items
    items = []
    for i in range(30):
        items.append({
            "title": f"Surf City {i} update",
            "link": f"https://example.com/{i}",
            "pub_date": _rfc2822(now - timedelta(hours=i)),
            "description": "Surf City news.",
        })
    feed = _make_feed_xml(items)
    fake_fetch = lambda url, timeout: feed  # noqa: E731

    candidates = news_search.fetch_candidates(
        whitelist={"El Diario de Hoy": "https://example.com/feed"},
        fetcher=fake_fetch,
        now=now,
    )
    assert len(candidates) == news_search.MAX_CANDIDATES


def test_fetch_candidates_skips_items_missing_required_fields():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    fresh = now - timedelta(days=1)
    feed = _make_feed_xml([
        {
            "title": "",  # missing title → skip
            "link": "https://example.com/no-title",
            "pub_date": _rfc2822(fresh),
            "description": "Surf City news",
        },
        {
            "title": "Surf City story",
            "link": "",  # missing link → skip
            "pub_date": _rfc2822(fresh),
            "description": "Surf City news",
        },
        {
            "title": "Surf City — bridge announcement",
            "link": "https://example.com/good",
            "pub_date": _rfc2822(fresh),
            "description": "Surf City news",
        },
    ])
    fake_fetch = lambda url, timeout: feed  # noqa: E731

    candidates = news_search.fetch_candidates(
        whitelist={"El Diario de Hoy": "https://example.com/feed"},
        fetcher=fake_fetch,
        now=now,
    )
    assert len(candidates) == 1
    assert candidates[0].source_url == "https://example.com/good"


def test_fetch_candidates_newest_first():
    """Output is sorted newest-first so the LLM prompt reflects recency."""
    now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    items = []
    for i in range(5):
        items.append({
            "title": f"Surf City update {i}",
            "link": f"https://example.com/{i}",
            "pub_date": _rfc2822(now - timedelta(hours=i * 6)),
            "description": "Surf City news",
        })
    feed = _make_feed_xml(items)
    fake_fetch = lambda url, timeout: feed  # noqa: E731

    candidates = news_search.fetch_candidates(
        whitelist={"El Diario de Hoy": "https://example.com/feed"},
        fetcher=fake_fetch,
        now=now,
    )
    # i=0 is newest, i=4 is oldest → expect index 0 first.
    titles = [c.title for c in candidates]
    assert titles == [
        "Surf City update 0",
        "Surf City update 1",
        "Surf City update 2",
        "Surf City update 3",
        "Surf City update 4",
    ]


def test_strip_html_collapses_whitespace():
    """RSS descriptions often have <p> + entities — we want clean prose."""
    raw = "<p>Hello   <strong>world</strong></p><br/><p>another paragraph</p>"
    out = news_search._strip_html(raw)
    assert "<" not in out
    assert ">" not in out
    assert "  " not in out  # whitespace collapsed
