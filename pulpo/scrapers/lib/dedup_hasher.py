"""Stable per-listing fingerprints for dedup.

Two fingerprints, two jobs.

**Property fingerprint** (``listing_fingerprint`` / ``property_fingerprint``) is
the **cross-source** signal: same physical property listed by two brokers should
collide. URL is deliberately excluded — including it means
``santizo.com/casa/123`` and ``encuentra24.com/sv-casa-456`` for the same lot
fingerprint apart, and the cross-source overlap matrix in
``automation/dedup_audit.py`` systematically under-counts duplicates.

Property fingerprint inputs: normalized title, price (nearest $1k), area
(nearest 50 m²), zone slug.

**Identity fingerprint** (``identity_fingerprint``) is the **within-source**
signal: same listing re-fetched from the same site over consecutive nightlies
should collide so the existence ledger can recognize "same listing as before".
Inputs: ``(source, source_id)``. Stable across crawls iff the scraper emits a
stable ``source_id``.

History: pre-2026-06 ``listing_fingerprint`` mixed URL into the hash. That
shipped silently miscounting overlap across sources like Santizo (which
cross-posts to Encuentra24 via the agency profile). The 2026-06 audit found
this and the split below is the fix. Existing callers of
``listing_fingerprint`` keep working — only the URL-derived collisions change,
and the change is the intended one.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


def _g(li: Any, name: str) -> Any:
    if isinstance(li, dict):
        return li.get(name)
    return getattr(li, name, None)


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


def property_fingerprint(li: Any) -> str:
    """Cross-source content fingerprint. URL deliberately excluded.

    Two listings with identical fingerprints are very likely the same
    physical property listed by two brokers. Used by the dedup audit's
    cross-source overlap matrix; never drops listings, telemetry only.
    """
    parts = (
        _normalize_title(_g(li, "title")),
        str(_round_price(_g(li, "price_usd"))),
        str(_round_area(_g(li, "area_m2"))),
        str(_g(li, "zone") or ""),
    )
    payload = "|".join(parts).encode("utf-8", errors="replace")
    return hashlib.sha1(payload).hexdigest()


def identity_fingerprint(li: Any) -> str:
    """Within-source stable identity. ``(source, source_id)`` based.

    Used by the existence ledger to recognize a re-fetched listing across
    consecutive nightlies. Two listings with the same identity_fingerprint
    are the **same record from the same source** — distinct from
    cross-source dedup, which is property_fingerprint's job.

    Returns the SHA1 hex of ``"<source>|<source_id>"``. Falls back to
    URL when ``source_id`` is missing — better than a no-op collision,
    but the scraper should be fixed to emit ``source_id`` properly.
    """
    source = _g(li, "source") or ""
    source_id = _g(li, "source_id")
    if source_id is None or source_id == "":
        # Defensive fallback: URL is at least stable per-source.
        source_id = _g(li, "url") or ""
    payload = f"{source}|{source_id}".encode("utf-8", errors="replace")
    return hashlib.sha1(payload).hexdigest()


# Backward-compat alias. Existing callers (``automation/dedup_audit.py``,
# tests) keep working; their semantic intent has always been the
# cross-source property fingerprint, so the URL exclusion is a fix, not
# a behavior change. The cross-source overlap matrix now catches the
# Santizo-on-Encuentra24 class of duplicates it used to miss.
listing_fingerprint = property_fingerprint
