"""
BaseScraper — common HTTP plumbing for all site adapters.

Real network calls require `httpx` and `selectolax`. If either is unavailable,
or if the env var PULPO_OFFLINE=1 is set, scrapers fall back to fixture data
so the pipeline always runs end-to-end.

Site-specific scrapers subclass BaseScraper and implement:
  - LIST_URL: paginated index URL pattern with a {page} slot
  - parse_index_page(html) -> list[dict]   # at least {"url": ..., "source_id": ...}
  - parse_detail_page(html, partial) -> dict | None
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import urljoin

# Optional deps — fall back to offline mode if missing
try:
    import httpx  # type: ignore
    HTTPX_OK = True
except ImportError:
    HTTPX_OK = False

try:
    from selectolax.parser import HTMLParser  # type: ignore
    SELECTOLAX_OK = True
except ImportError:
    SELECTOLAX_OK = False

DEFAULT_HEADERS = {
    "User-Agent": (
        "pulpo-club/0.1 (+https://pulpo.club; aggregator) "
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15"
    ),
    "Accept-Language": "es-SV,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"

class BaseScraper:
    SOURCE: str = ""           # short slug, e.g. "goodlife"
    BASE_URL: str = ""         # https://example.com/
    LIST_URL: str = ""         # may contain "{page}"
    REQUEST_DELAY: float = 1.5 # seconds between requests; tune per site
    MAX_PAGES: int = 5
    FIXTURE_FILE: Optional[str] = None  # filename inside fixtures/ for offline mode

    def __init__(self, offline: Optional[bool] = None):
        self.offline = bool(offline) if offline is not None else (
            os.environ.get("PULPO_OFFLINE") == "1" or not HTTPX_OK or not SELECTOLAX_OK
        )
        # Allow ad-hoc tuning of the per-request delay (default class-level
        # value is the polite production setting). Useful for short test runs
        # against a few listings, where the 1.5s polite delay would push the
        # total wall-clock past sandbox/CI timeouts. Production cron should
        # leave PULPO_REQUEST_DELAY unset.
        env_delay = os.environ.get("PULPO_REQUEST_DELAY")
        if env_delay:
            try:
                self.REQUEST_DELAY = float(env_delay)
            except ValueError:
                pass  # ignore garbage; fall back to class default
        if not self.offline:
            self.client = httpx.Client(
                headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20.0
            )

    # ---- Hooks subclasses override ----
    def parse_index_page(self, html: str) -> list[dict]:
        raise NotImplementedError

    def parse_detail_page(self, html: str, partial: dict) -> Optional[dict]:
        raise NotImplementedError

    # ---- Engine ----
    def _fetch(self, url: str) -> str:
        time.sleep(self.REQUEST_DELAY)
        r = self.client.get(url)
        r.raise_for_status()
        return r.text

    def _absolute(self, url: str) -> str:
        return urljoin(self.BASE_URL, url)

    def crawl(self, limit: int = 30) -> list[dict]:
        """Yield raw normalized dicts. Falls back to fixtures if offline."""
        if self.offline:
            return self._load_fixtures(limit)
        out: list[dict] = []
        # Many themes (Avada/Fusion seen on oceanside) render the same listing
        # card multiple times for responsive variants, so the index page emits
        # duplicate URLs. We dedupe on absolute URL across the whole crawl —
        # this both prevents duplicate ranked records and saves HTTP roundtrips
        # against the broker.
        seen_urls: set[str] = set()
        for page in range(1, self.MAX_PAGES + 1):
            url = self.LIST_URL.format(page=page) if "{page}" in self.LIST_URL else self.LIST_URL
            try:
                index_html = self._fetch(url)
            except Exception as e:
                print(f"[{self.SOURCE}] index fetch failed: {e}")
                break
            partials = self.parse_index_page(index_html)
            if not partials:
                break
            for partial in partials:
                if len(out) >= limit:
                    break
                durl = partial.get("url")
                if not durl:
                    continue
                durl = self._absolute(durl)
                if durl in seen_urls:
                    continue
                seen_urls.add(durl)
                try:
                    detail_html = self._fetch(durl)
                except Exception as e:
                    print(f"[{self.SOURCE}] detail fetch failed for {durl}: {e}")
                    continue
                rec = self.parse_detail_page(detail_html, partial)
                if rec:
                    rec.setdefault("source_id", partial.get("source_id"))
                    rec.setdefault("url", durl)
                    rec.setdefault("scraped_at", datetime.now(timezone.utc).isoformat())
                    out.append(rec)
            if len(out) >= limit:
                break
        return out

    def _load_fixtures(self, limit: int) -> list[dict]:
        if not self.FIXTURE_FILE:
            return []
        path = FIXTURES_DIR / self.FIXTURE_FILE
        if not path.exists():
            return []
        with path.open() as f:
            data = json.load(f)
        # only this source's records
        recs = [r for r in data if r.get("source") == self.SOURCE]
        return recs[:limit]
