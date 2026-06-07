"""Open Graph + Twitter Card meta extractor for sources without JSON-LD.

Xitios is the canonical example: detail pages expose no JSON-LD but
carry rich ``og:title`` / ``og:description`` / ``og:image`` tags that
contain the full listing spec as free text. This extractor pulls those
fields and lets per-source price/area regex patterns finish the job.

Tolerant by design — missing tags return ``None`` rather than raising,
and the body is treated as a string of HTML, no DOM parser required.
"""
from __future__ import annotations

import re
from html import unescape
from typing import Optional


_META_RE = re.compile(
    r'<meta\s+[^>]*?'
    r'(?:property|name)\s*=\s*["\']og:([a-z_:]+)["\']'
    r'[^>]*?content\s*=\s*["\']([^"\']*)["\']'
    r'[^>]*?/?>',
    re.IGNORECASE,
)

_META_RE_REVERSE = re.compile(
    r'<meta\s+[^>]*?'
    r'content\s*=\s*["\']([^"\']*)["\']'
    r'[^>]*?(?:property|name)\s*=\s*["\']og:([a-z_:]+)["\']'
    r'[^>]*?/?>',
    re.IGNORECASE,
)


def extract_og(html: str) -> dict:
    """Pull every ``og:*`` meta tag from ``html`` into a dict.

    Returns a dict keyed by the og: sub-name (e.g. ``"title"``,
    ``"description"``, ``"image"``). ``"image"`` is collected as a list
    so multi-image carousels survive; all other keys keep the first
    occurrence (matches what social-card consumers do).

    Example return:
        {"title": "Casa en El Tunco",
         "description": "Vista al mar · $ 590,000 · 7,000 varas cuadradas",
         "image": ["https://.../1.jpg", "https://.../2.jpg"]}
    """
    if not html:
        return {}
    out: dict = {}
    for match in _META_RE.findall(html):
        sub, content = match
        _stash(out, sub.lower(), content)
    # Handle attribute-order-reversed tags (some CMS templates emit
    # content="..." before property="og:...").
    for match in _META_RE_REVERSE.findall(html):
        content, sub = match
        _stash(out, sub.lower(), content)
    return out


def og_images(html: str) -> list[str]:
    """Return de-duplicated ``og:image`` URLs in page order."""
    images = extract_og(html).get("image") or []
    out: list[str] = []
    seen: set[str] = set()
    for image in images:
        if not isinstance(image, str):
            continue
        url = unescape(image).strip()
        if url.startswith("http") and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def prepend_og_images(html: str, urls: list[str]) -> list[str]:
    """Prepend Open Graph image URLs ahead of scraper gallery URLs.

    Social-card metadata is the broker's explicit cover-photo signal. Some
    CMS/SaaS stacks omit that first image from their gallery payload, so
    treating ``og:image`` as just a fallback can make Pulpo miss the intended
    hero. This helper preserves gallery order after the OG image(s) and
    de-duplicates by exact URL.
    """
    out: list[str] = []
    seen: set[str] = set()
    for url in [*og_images(html), *(urls or [])]:
        if not isinstance(url, str):
            continue
        clean = unescape(url).strip()
        if clean.startswith("http") and clean not in seen:
            seen.add(clean)
            out.append(clean)
    return out


def _stash(out: dict, key: str, value: str) -> None:
    if not value:
        return
    if key == "image":
        out.setdefault("image", [])
        if value not in out["image"]:
            out["image"].append(value)
        return
    out.setdefault(key, value)


def find_first(text: str, patterns: tuple[str, ...]) -> Optional[str]:
    """Apply each regex pattern to ``text``; return the first capture group of the first match."""
    if not text:
        return None
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return m.group(1)
            except IndexError:
                return m.group(0)
    return None
