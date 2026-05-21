"""Generate web/sitemap.xml from the ranked listings.

Emits one entry per section path (homepage + Browse + each category) and
one per non-off-market listing. Off-market listings are paywalled; we
keep their URLs out of the public sitemap so Google doesn't surface
content the user can't access without a Pro account.

Section URL list mirrors web/app/lib/url-routing.ts. Keep them in sync —
adding a route there means adding it here.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Iterable
from xml.sax.saxutils import escape

SITE_ORIGIN = "https://pulpo.club"

# Paths that are public + indexable. Saved + Account require auth, so
# they're excluded — Google can crawl them but they have no useful
# content for an anonymous bot. /plans is public.
SECTION_ENTRIES: list[tuple[str, str, str]] = [
    # (path, changefreq, priority)
    ("/",                          "daily",   "1.0"),
    ("/browse",                    "daily",   "0.9"),
    ("/browse?cat=beachfront",     "daily",   "0.9"),
    ("/browse?cat=build_ready",    "daily",   "0.8"),
    ("/browse?cat=off_market",     "weekly",  "0.6"),
    ("/plans",                     "monthly", "0.5"),
]


def _today_iso() -> str:
    return _dt.date.today().isoformat()


def _url_node(loc: str, lastmod: str, changefreq: str, priority: str) -> str:
    # Keep alternates simple — point ?lang=es / ?lang=en at the same
    # path; Google reads <xhtml:link rel="alternate" hreflang="...">
    # for language variants.
    sep = "&amp;" if "?" in loc else "?"
    en_url = f"{SITE_ORIGIN}{loc}"
    es_url = f"{SITE_ORIGIN}{loc}{sep}lang=es"
    return (
        "  <url>\n"
        f"    <loc>{escape(en_url)}</loc>\n"
        f"    <lastmod>{lastmod}</lastmod>\n"
        f"    <changefreq>{changefreq}</changefreq>\n"
        f"    <priority>{priority}</priority>\n"
        f'    <xhtml:link rel="alternate" hreflang="en" href="{escape(en_url)}"/>\n'
        f'    <xhtml:link rel="alternate" hreflang="es" href="{escape(es_url)}"/>\n'
        f'    <xhtml:link rel="alternate" hreflang="x-default" href="{escape(en_url)}"/>\n'
        "  </url>\n"
    )


def _read_field(obj: Any, key: str, default: Any = None) -> Any:
    """Pull a field off a Listing dataclass or a plain dict."""
    if hasattr(obj, key):
        return getattr(obj, key, default)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _listing_id(obj: Any) -> str | None:
    # The FE adapter joins source + source_id with a dash. Backend
    # dataclasses store them separately. The sitemap must publish the
    # FE-shaped id — that's what /listing/:id resolves to in the SPA.
    explicit = _read_field(obj, "id")
    if explicit:
        return str(explicit)
    source = _read_field(obj, "source")
    source_id = _read_field(obj, "source_id")
    if source and source_id:
        return f"{source}-{source_id}"
    return None


def write_sitemap(out_path: Path, ranked: Iterable[Any]) -> int:
    """Write the sitemap. Returns the number of <url> entries written.

    Accepts either Listing dataclasses or plain dicts — pulls fields via
    `_read_field`, so the call site doesn't need to convert.
    """

    today = _today_iso()
    parts: list[str] = []
    parts.append('<?xml version="1.0" encoding="UTF-8"?>\n')
    parts.append(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
    )

    n = 0
    for path, changefreq, priority in SECTION_ENTRIES:
        parts.append(_url_node(path, today, changefreq, priority))
        n += 1

    for listing in ranked:
        # Skip off-market — paywalled, don't surface them.
        # Skip sold — dead URLs.
        if _read_field(listing, "source_type") == "off_market":
            continue
        if _read_field(listing, "is_sold"):
            continue
        listing_id = _listing_id(listing)
        if not listing_id:
            continue
        # Listing IDs are alphanumerics + dashes, but escape() handles
        # any future ID format that includes XML-meta chars defensively.
        parts.append(_url_node(f"/listing/{listing_id}", today, "weekly", "0.7"))
        n += 1

    parts.append("</urlset>\n")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("".join(parts), encoding="utf-8")
    return n


__all__ = ["write_sitemap", "SECTION_ENTRIES", "SITE_ORIGIN"]
