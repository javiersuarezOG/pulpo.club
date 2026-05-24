"""Shared scraper base — single source of truth for the cross-cutting
concerns every Pulpo scraper needs.

Why this exists
---------------
Pulpo has 8 production scrapers today plus 4 about to land. Every one of
them re-implements the same six steps in slightly-different ways:

  1. open an httpx session with retries + rate-limit + UA rotation
  2. extract a candidate dict from the upstream payload
  3. run it through `classify_property_type` (multi-signal type guard)
  4. upgrade its photo URLs via `upgrade_photo_urls`
  5. enforce the house/condo vacation-zone + waterfront-keyword filter
  6. return `{"records": [...], "max_pages_hit": bool, "limit_hit": bool}`

When that pipeline diverges across 8+ files, fixing a host's new
Cloudflare rule means editing 8+ files. The realtyelsalvador WAF
incident is the canonical example: only one scraper had moved to the
polite layer; the rest were still on the legacy single-UA path.

This module makes the steps composable, not inherited. Scrapers stay
plain classes — they import these helpers and call them. Nothing
forces a scraper to use them (encuent24's Playwright path won't), but
every new scraper SHOULD.

What's here
-----------
- ``polite_get_for(slug)``      — thin wrapper over _runtime.polite_get
                                  that injects the slug's Policy. The
                                  one HTTP call every scraper makes.
- ``finalize_record(...)``      — runs photo upgrade + classifier +
                                  vacation-zone filter on a near-final
                                  record dict. Returns the record with
                                  `_type_*` fields populated, or None
                                  if the vacation gate rejects it.
- ``OfflineFixtureMixin``       — class-level slug + FIXTURE_FILE +
                                  the offline guard. Eliminates the
                                  if-offline branch from every crawl().

What's NOT here
---------------
- A base class. Composition over inheritance — scrapers stay flat.
- HTML parsing helpers. selectolax is fine where it's used; no need
  for a shim.
- Per-source pagination. Every source's pagination is different
  enough that the abstraction cost would exceed the savings.
"""
from __future__ import annotations
import re
from typing import Callable, Optional

from pulpo.agents.html_crawler import is_offline, load_fixtures
from pulpo.scrapers._photo_url_upgrade import upgrade_photo_urls
from pulpo.scrapers._policy import get_policy
from pulpo.scrapers._runtime import polite_get
from pulpo.scrapers._type_classifier import classify_property_type
from automation.property_types import VACATION_ZONES, WATERFRONT_KEYWORDS

# Single compiled fallback for the waterfront-keyword filter — the same
# pattern was being re-compiled in every scraper module.
WATERFRONT_RE: re.Pattern = re.compile("|".join(WATERFRONT_KEYWORDS), re.IGNORECASE)


def polite_get_for(slug: str) -> Callable:
    """Return a `polite_get`-bound callable preconfigured for `slug`.

    Usage:
        get = polite_get_for(self.slug)
        resp = get(client, url)               # rate-limited, UA-rotated
        resp = get(client, url, extra_headers={...})

    Resolves the source's `Policy` once at scraper-construction time so
    each request doesn't re-look it up. The returned callable mirrors
    `polite_get`'s signature minus `source=` and `policy=`.
    """
    policy = get_policy(slug)

    def _get(client, url: str, *, extra_headers: Optional[dict] = None):
        return polite_get(
            client, url,
            source=slug, policy=policy, extra_headers=extra_headers,
        )

    return _get


def passes_vacation_gate(
    *, property_type: str, location_text: str, title: str, description: str,
) -> bool:
    """Vacation-zone + waterfront-keyword filter for house/condo.

    Returns True for land (no gate — inland lots are valid inventory).
    For house/condo, returns True iff:
      - the location string contains a known VACATION_ZONE slug, OR
      - the title or description contains a WATERFRONT_KEYWORDS match.

    The check is the same shape applied in every existing scraper's
    type-specific branch — moved here so a single edit (e.g. adding
    a new lake zone) updates every consumer.
    """
    if property_type not in ("house", "condo"):
        return True
    loc_blob = (location_text or "").lower().replace(" ", "-")
    zone_is_vacation = any(z in loc_blob for z in VACATION_ZONES)
    if zone_is_vacation:
        return True
    text_blob = f"{title}\n{description}"
    return bool(WATERFRONT_RE.search(text_blob))


def finalize_record(
    record: dict,
    *,
    slug: str,
    broker_type: str,
    broker_type_field: str = "",
    photo_payload: Optional[dict] = None,
) -> Optional[dict]:
    """Run the standard cross-cutting steps on a near-final record dict.

    Steps, in order:
      1. Upgrade `photo_urls` via `upgrade_photo_urls(slug, urls, payload=...)`.
         (Mutates record["photo_urls"] in place.)
      2. Apply the vacation-zone gate for house/condo (drops inland
         built listings unless title/desc has a waterfront keyword).
      3. Run the multi-signal `classify_property_type`, attach
         `_type_signals`, `_type_confidence`, `_type_total`.
      4. If the classifier disagrees with `broker_type`, set
         `validation_status="flagged"` + append `type_classifier_disagree`.

    Returns the record (possibly mutated) on success, or None if the
    vacation gate dropped it. The broker_type stays authoritative for
    shipping — the classifier disagreement only flags for human review.
    """
    record["photo_urls"] = upgrade_photo_urls(
        slug, record.get("photo_urls") or [], payload=photo_payload,
    )

    if not passes_vacation_gate(
        property_type=broker_type,
        location_text=record.get("location_text", ""),
        title=record.get("title", ""),
        description=record.get("description", ""),
    ):
        return None

    ptype, signals, confidence, total = classify_property_type({
        "broker_type_field": broker_type_field or broker_type,
        "url":               record.get("url", ""),
        "photo_urls":        record["photo_urls"],
        "title":             record.get("title", ""),
        "description":       record.get("description", ""),
    }, fallback_type=broker_type)
    record["_type_signals"]    = [s.to_dict() for s in signals]
    record["_type_confidence"] = confidence
    record["_type_total"]      = total
    if ptype != broker_type:
        record["validation_status"] = "flagged"
        record.setdefault("validation_warnings", []).append("type_classifier_disagree")

    return record


class OfflineFixtureMixin:
    """Mixin: provides ``_offline_or_fixtures(limit)`` so subclasses
    don't repeat the if-offline boilerplate in every crawl().

    Subclass requirements:
      - ``slug``         class attribute, the source slug
      - ``FIXTURE_FILE`` class attribute, defaults to "sample_listings.json"
      - ``self.offline`` instance attribute (set in __init__)
    """

    FIXTURE_FILE: str = "sample_listings.json"

    def _offline_or_fixtures(
        self, limit: int, *, override_offline: bool | None = None,
    ) -> Optional[list[dict]]:
        """If offline mode resolves True, return fixture records.
        Otherwise return None and let the caller proceed online.
        """
        flag = override_offline if override_offline is not None else getattr(self, "offline", None)
        if is_offline(flag):
            return load_fixtures(self.slug, self.FIXTURE_FILE, limit)
        return None
