"""Weekly news search for the newsletter's Weekly News Spotlight block.

Pulls the last 7 days of articles from a curated whitelist of El
Salvador news outlets (RSS feeds), filters to topics relevant to a
beach/lake property buyer, and returns a ranked list of candidate
articles. The LLM-driven pick + summarize step lives in `llm_news.py`.

Design choices:
  • Stdlib only — no `feedparser` / `requests` dependencies. The RSS 2.0
    feeds we hit are simple enough for `xml.etree.ElementTree`.
  • Per-outlet failures are swallowed — if one feed is down or returns
    malformed XML, the rest still run. The renderer's fallback path in
    `_weekly_news_spotlight_html` handles a zero-candidate week.
  • Keyword filter is liberal: we'd rather over-include and let the LLM
    rank than miss a relevant story. Editor: tune `KEYWORDS` over time
    based on what surfaces vs. what gets picked.

When adding a new outlet:
  1. Find its RSS / Atom feed URL (usually `/feed`, `/rss`, `/feed/rss`
     or linked from `<head><link rel="alternate" type="application/rss+xml">`).
  2. Add a row to `WHITELIST`. Use the outlet's editorial name
     (capitalization matters — that's what the newsletter cites).
  3. If the feed is Atom-only, extend `_parse_feed` to handle the
     `<entry>` shape — currently it's RSS 2.0 (`<item>`).
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable

# Editorial whitelist. Order doesn't matter — the LLM ranks across all
# outlets together. Keep the source_name as the outlet's editorial
# title (what the newsletter cites) so the renderer's "Reported by …"
# line reads cleanly.
WHITELIST: dict[str, str] = {
    "El Diario de Hoy":   "https://www.elsalvador.com/feed/",
    "La Prensa Gráfica":  "https://www.laprensagrafica.com/feed/",
    "El Mundo":           "https://elmundo.sv/feed/",
    "Diario El Salvador": "https://diarioelsalvador.com/feed/",
    "La Página":          "https://www.lapagina.com.sv/feed/",
}

# Relevance keywords. Liberal on purpose — the LLM ranker decides what's
# actually useful. We just want to keep the LLM's input window manageable
# by filtering out coverage of unrelated topics (politics, sports, crime).
# All matching is lowercase substring on title + summary.
KEYWORDS: tuple[str, ...] = (
    # Coastal / regional
    "surf city", "tunco", "sunzal", "zonte", "cuco", "las flores",
    "tamanique", "chiltiup", "bitcoin beach",
    # Lakes
    "coatepeque", "ilopango", "suchitl",
    # Infra / policy that affects coastal real estate
    "lempa", "fovial", "mitur", "puente", "carretera",
    "concesión hotelera", "concesión turística", "obra costanera",
    "litoral", "costa", "playa", "lago",
    # Real-estate adjacent
    "real estate", "bienes raíces", "inmobiliaria",
    "hotel", "desarrollo turístico", "inversión turística",
)

# Cap candidates passed to the LLM. 20 keeps the prompt under ~3K tokens
# while still giving the model enough range to find the most useful pick.
MAX_CANDIDATES = 20

# Per-outlet HTTP timeout. Newsletter cron runs weekly with a fixed
# 20-minute job budget; 10s per outlet × 5 outlets = 50s worst case.
DEFAULT_TIMEOUT_S = 10


@dataclass
class CandidateArticle:
    """One last-7-days RSS item from a whitelisted outlet."""

    source_name: str
    source_url: str
    title: str
    summary: str
    published_at: datetime


def fetch_candidates(
    *,
    window_days: int = 7,
    timeout: int = DEFAULT_TIMEOUT_S,
    keyword_filter: bool = True,
    whitelist: dict[str, str] | None = None,
    now: datetime | None = None,
    fetcher=None,
) -> list[CandidateArticle]:
    """Pull last-7-days articles from the whitelisted outlets.

    Returns a newest-first list of candidates. Per-outlet failures
    (network, HTTP error, malformed XML, missing pubDate) are
    swallowed silently — the LLM ranker handles zero-candidate weeks
    via the renderer's deterministic fallback.

    `fetcher` is dependency-injected for tests — a callable taking the
    feed URL + timeout and returning the raw XML bytes. Defaults to a
    real HTTP fetch.
    """
    sources = whitelist if whitelist is not None else WHITELIST
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=window_days)
    fetch = fetcher or _http_fetch

    out: list[CandidateArticle] = []
    for source_name, feed_url in sources.items():
        try:
            xml_bytes = fetch(feed_url, timeout)
        except Exception:
            # Network / HTTP issue — skip this outlet, try the next.
            continue
        if not xml_bytes:
            continue
        try:
            items = list(_parse_feed(xml_bytes))
        except ET.ParseError:
            continue
        for item in items:
            if item.published_at < cutoff:
                continue
            if keyword_filter and not _matches_keyword(item.title, item.summary):
                continue
            out.append(CandidateArticle(
                source_name=source_name,
                source_url=item.url,
                title=item.title,
                summary=item.summary,
                published_at=item.published_at,
            ))

    # Newest first — the LLM gets a sense of recency in the prompt order.
    out.sort(key=lambda c: c.published_at, reverse=True)
    return out[:MAX_CANDIDATES]


# ── Internal helpers ─────────────────────────────────────────────────


@dataclass
class _RawItem:
    url: str
    title: str
    summary: str
    published_at: datetime


def _http_fetch(url: str, timeout: int) -> bytes:
    """Stdlib HTTP GET with a polite User-Agent header. Raises on
    network / HTTP error — caller decides whether to swallow."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Pulpo-Newsletter/1.0 (+https://pulpo.club)",
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        return fh.read()


def _parse_feed(xml_bytes: bytes) -> Iterable[_RawItem]:
    """Iterate `<item>` elements of an RSS 2.0 feed. Atom feeds use
    `<entry>` — we don't handle those yet (none of the whitelisted
    outlets ship Atom). When that changes, extend here."""
    root = ET.fromstring(xml_bytes)
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc_raw = item.findtext("description") or ""
        summary = _strip_html(desc_raw).strip()
        pub_date_str = item.findtext("pubDate") or ""
        try:
            pub_dt = parsedate_to_datetime(pub_date_str)
            if pub_dt is None:
                continue
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if not title or not link:
            continue
        yield _RawItem(url=link, title=title, summary=summary, published_at=pub_dt)


_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(html: str) -> str:
    """Strip tags + collapse whitespace. RSS descriptions often carry
    embedded `<p>` / `<a>` / `<img>` from the article's lead — we want
    just the prose for the LLM prompt."""
    return _WS_RE.sub(" ", _TAG_RE.sub("", html))


def _matches_keyword(title: str, summary: str) -> bool:
    """Case-insensitive substring match against `KEYWORDS`. Liberal on
    purpose — false-positives are cheap (LLM ranks them down); a
    false-negative loses a relevant story for the week."""
    text = f"{title} {summary}".lower()
    return any(kw in text for kw in KEYWORDS)
