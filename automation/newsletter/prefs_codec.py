"""Compact serialization of a free-member newsletter filter.

Free (email-only, non-Clerk) subscribers have no Clerk `publicMetadata`
to hold their filter, and Pulpo has no database. Their filter is stored on
the Resend contact's `last_name` field as a side-channel — mirroring the
existing `first_name = "pulpo-locale:<lc>"` hack in subscribers.py.

Why `last_name` and not Resend contact *properties*: the nightly pipeline
reads the whole audience with ONE `GET /audiences/:id/contacts` list call,
and Resend's list response does not include custom properties — reading
properties would force an O(N) per-contact `get`. The list DOES return
`last_name`, which Pulpo never renders (display names come from Clerk), so
it is free to reuse and reads for zero extra API calls.

Format (after the `pulpo-filter:` prefix): `k=v` pairs joined by `;`.
    pulpo-filter:pt=land,house;mx=500000;mn=0;z=el_tunco;cat=beachfront
Keys — all optional, empty ones omitted:
    pt  property_types (csv of slugs)     mx  max_price_usd (int)
    z   zones (csv of slugs)              mn  min_price_usd (int)
    cat categories (csv of slugs)

This module is the READER (pipeline). The WRITER is api/_prefs_codec.js —
the two MUST stay in lockstep; tests/newsletter/test_prefs_codec.py plus the
JS contract test enforce parity. Decode is total: any malformed input
yields an empty dict (→ empty Preference → the cohort fallback), never an
exception.
"""

from __future__ import annotations

from typing import Any

PREFIX = "pulpo-filter:"

# Slug lists we accept. Values outside [a-z0-9_-] are dropped defensively so a
# tampered link can never inject markup or separators back through decode.
_SLUG_KEYS = {"pt": "property_types", "z": "zones", "cat": "categories"}
_INT_KEYS = {"mx": "max_price_usd", "mn": "min_price_usd"}

_ALL_FIELDS = ("property_types", "zones", "categories", "max_price_usd", "min_price_usd")


def _clean_slug(s: str) -> str:
    return "".join(ch for ch in s.strip().lower() if ch.isalnum() or ch in "_-")


def _clean_slug_list(raw: str) -> list[str]:
    out: list[str] = []
    for part in raw.split(","):
        slug = _clean_slug(part)
        if slug and slug not in out:
            out.append(slug)
    return out


def decode(raw: Any) -> dict:
    """Parse a `last_name` value into a filter dict. Total — never raises.

    Returns {} for anything that isn't a well-formed `pulpo-filter:` string,
    which the caller maps to an empty Preference (no opinion).
    """
    if not isinstance(raw, str):
        return {}
    raw = raw.strip()
    if not raw.startswith(PREFIX):
        return {}
    body = raw[len(PREFIX):]
    out: dict = {}
    for pair in body.split(";"):
        if "=" not in pair:
            continue
        k, _, v = pair.partition("=")
        k = k.strip().lower()
        if k in _SLUG_KEYS:
            vals = _clean_slug_list(v)
            if vals:
                out[_SLUG_KEYS[k]] = vals
        elif k in _INT_KEYS:
            digits = "".join(ch for ch in v if ch.isdigit())
            if digits:
                n = int(digits)
                # min=0 carries no information (no floor) — drop it so the
                # encode↔decode round-trip is stable and Preference stays clean.
                if not (k == "mn" and n == 0):
                    out[_INT_KEYS[k]] = float(n)
    return out


def encode(pref: dict) -> str:
    """Serialize a filter dict to a `last_name` value (incl. prefix).

    Empty filter → "" (caller clears the contact's last_name). Kept in sync
    with api/_prefs_codec.js `encode`; the contract test pins the format.
    """
    parts: list[str] = []
    for short, field in _SLUG_KEYS.items():
        vals = pref.get(field)
        if isinstance(vals, list):
            slugs = [s for s in (_clean_slug(str(x)) for x in vals) if s]
            if slugs:
                parts.append(f"{short}={','.join(slugs)}")
    for short, field in _INT_KEYS.items():
        v = pref.get(field)
        if isinstance(v, (int, float)) and v > 0:
            parts.append(f"{short}={int(v)}")
    if not parts:
        return ""
    return PREFIX + ";".join(parts)
