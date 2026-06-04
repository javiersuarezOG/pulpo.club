"""Stable per-listing fingerprint for cross-source dedup.

Mirrors the fingerprinting in `automation/duplicate_detection.py` but
exposes it as a per-scraper utility so a new scraper can detect overlap
with existing inventory at crawl time (telemetry only — never drops
listings).

Fingerprint shape: SHA1 hex of a normalized tuple of (url, title,
price_usd_rounded, area_m2_rounded, zone). Two listings with identical
fingerprints are very likely the same physical property listed by two
brokers.

This is a **content fingerprint**, not an identity hash. It's deliberate
that price + area get rounded — two brokers listing the same lot rarely
agree on exact area within a few square meters. A 5% / 50m² tolerance
matches the dedup audit's existing thresholds.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


def _g(li: Any, name: str) -> Any:
    if isinstance(li, dict):
        return li.get(name)
    return getattr(li, name, None)


def _normalize_url(url: Any) -> str:
    if not isinstance(url, str):
        return ""
    s = url.strip().lower()
    # Strip query string + fragment + trailing slash. Same listing under
    # different UTM tags or ref params would otherwise fingerprint apart.
    s = re.sub(r"[?#].*$", "", s)
    s = s.rstrip("/")
    return s


def _normalize_title(title: Any) -> str:
    if not isinstance(title, str):
        return ""
    s = title.lower().strip()
    # Collapse runs of whitespace; strip punctuation. Brokers tend to
    # vary capitalization, exclamation marks, and dashes on the same
    # property.
    s = re.sub(r"[^\w\s]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _round_price(price: Any) -> int:
    """Round price to the nearest $1k — defends against two brokers
    quoting $325,000 vs $324,900 on the same property."""
    if not isinstance(price, (int, float)):
        return 0
    return int(round(price / 1000.0)) * 1000


def _round_area(area: Any) -> int:
    """Round area to the nearest 50 m²."""
    if not isinstance(area, (int, float)):
        return 0
    return int(round(area / 50.0)) * 50


def listing_fingerprint(li: Any) -> str:
    """Return a stable SHA1 hex fingerprint for `li`.

    Same physical listing → same hex even if URL has different UTMs or
    price differs by <$1k. Different listings → different hex.
    """
    parts = (
        _normalize_url(_g(li, "url")),
        _normalize_title(_g(li, "title")),
        str(_round_price(_g(li, "price_usd"))),
        str(_round_area(_g(li, "area_m2"))),
        str(_g(li, "zone") or ""),
    )
    payload = "|".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha1(payload).hexdigest()
