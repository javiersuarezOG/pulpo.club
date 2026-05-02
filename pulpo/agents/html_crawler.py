"""
HtmlIndexCrawler — composable HTML index→detail page walker.

Not a base class. Sources that need paginated HTML crawling instantiate
this and call walk(). Sources with different strategies (embedded JSON,
REST API, etc.) ignore it entirely.
"""
from __future__ import annotations
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urljoin

try:
    import httpx
    HTTPX_OK = True
except ImportError:
    HTTPX_OK = False

try:
    from selectolax.parser import HTMLParser  # noqa: F401  # re-exported for scrapers
    SELECTOLAX_OK = True
except ImportError:
    SELECTOLAX_OK = False

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures"

DEFAULT_HEADERS = {
    "User-Agent": (
        "pulpo-club/0.1 (+https://pulpo.club; aggregator) "
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15"
    ),
    "Accept-Language": "es-SV,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def is_offline(flag: Optional[bool] = None) -> bool:
    """Resolve offline mode: explicit flag > env var > dep availability."""
    if flag is not None:
        return bool(flag)
    return os.environ.get("PULPO_OFFLINE") == "1" or not HTTPX_OK or not SELECTOLAX_OK


def load_fixtures(source_slug: str, fixture_file: str, limit: int) -> list[dict]:
    """Load fixture records for source_slug from fixtures/fixture_file."""
    path = FIXTURES_DIR / fixture_file
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return [r for r in data if r.get("source") == source_slug][:limit]


def make_client() -> "httpx.Client":
    if not HTTPX_OK:
        raise RuntimeError("httpx not installed — cannot make HTTP client")
    delay = os.environ.get("PULPO_REQUEST_DELAY")
    # delay is used in walk(), not here; we just build the client
    return httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=20.0)


def walk(
    client: "httpx.Client",
    base_url: str,
    list_url: str,
    parse_index: Callable[[str], list[dict]],
    parse_detail: Callable[[str, dict], Optional[dict]],
    max_pages: int = 5,
    request_delay: float = 1.5,
    limit: int = 30,
) -> list[dict]:
    """
    Walk paginated HTML index + per-listing detail pages.

    parse_index(html) -> list[{"url": ..., "source_id": ...}]
    parse_detail(html, partial) -> dict | None
    """
    return walk_with_meta(
        client=client, base_url=base_url, list_url=list_url,
        parse_index=parse_index, parse_detail=parse_detail,
        max_pages=max_pages, request_delay=request_delay, limit=limit,
    )["records"]


def walk_with_meta(
    client: "httpx.Client",
    base_url: str,
    list_url: str,
    parse_index: Callable[[str], list[dict]],
    parse_detail: Callable[[str, dict], Optional[dict]],
    max_pages: int = 5,
    request_delay: float = 1.5,
    limit: int = 30,
) -> dict:
    """
    Like walk() but returns a coverage-audit dict:
      {"records": [...], "max_pages_hit": bool, "limit_hit": bool}

    max_pages_hit: True when the loop exhausted max_pages with results still
      coming in — there are likely more listings we didn't fetch.
    limit_hit: True when the caller's `limit` cap stopped the crawl before
      pagination ended naturally.
    """
    try:
        request_delay = float(os.environ.get("PULPO_REQUEST_DELAY") or request_delay)
    except ValueError:
        pass

    out: list[dict] = []
    seen_urls: set[str] = set()
    limit_hit = False
    last_had_partials = False

    for page in range(1, max_pages + 1):
        url = list_url.format(page=page) if "{page}" in list_url else list_url
        try:
            time.sleep(request_delay)
            r = client.get(url)
            r.raise_for_status()
        except Exception as e:
            print(f"[html_crawler] index fetch failed ({url}): {e}")
            break

        partials = parse_index(r.text)
        if not partials:
            last_had_partials = False
            break
        last_had_partials = True

        new_this_page = False
        for partial in partials:
            if len(out) >= limit:
                limit_hit = True
                break
            durl = partial.get("url", "")
            if not durl:
                continue
            durl = urljoin(base_url, durl) if not durl.startswith("http") else durl
            if durl in seen_urls:
                continue
            seen_urls.add(durl)
            new_this_page = True

            try:
                time.sleep(request_delay)
                dr = client.get(durl)
                dr.raise_for_status()
            except Exception as e:
                print(f"[html_crawler] detail fetch failed ({durl}): {e}")
                continue

            rec = parse_detail(dr.text, partial)
            if rec:
                rec.setdefault("source_id", partial.get("source_id"))
                rec.setdefault("url", durl)
                rec.setdefault("scraped_at", datetime.now(timezone.utc).isoformat())
                out.append(rec)

        if limit_hit:
            break

        # WordPress and similar CMSs wrap around when page N exceeds the last
        # real page — returning the same listing URLs indefinitely. Detect this
        # by stopping as soon as a full page yields zero new URLs.
        if not new_this_page:
            last_had_partials = False
            break
    else:
        # for loop completed all max_pages without a break
        max_pages_hit = last_had_partials
        return {"records": out, "max_pages_hit": max_pages_hit, "limit_hit": limit_hit}

    return {"records": out, "max_pages_hit": False, "limit_hit": limit_hit}
