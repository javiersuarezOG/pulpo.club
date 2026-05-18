"""Per-source photo URL upgrade helper (Phase 4 O1).

Scrapers call ``upgrade_photo_urls(source, urls, payload=None)`` after
they assemble their ``photo_urls`` list. The helper looks up the source
in ``photo_config.json`` and applies the configured ``full_res`` strategy
to substitute card-thumb URLs with full-resolution variants.

Strategies (see ``photo_config.schema.json``):

- ``noop``                     — no transform, return urls unchanged.
- ``url_replace``              — per-rule string or regex substitution.
- ``field_swap``               — read alternate field(s) from the parsed
                                 site payload (e.g. JSON ``image_wm``).
- ``wordpress_size_strip``     — drop ``-WIDTHxHEIGHT`` from WP-Media
                                 generated size variants.
- ``cloudfront_image_handler`` — decode base64 image-handler payload
                                 (``{"bucket":..., "key":..., "edits":
                                 {"resize":{...}}}``), raise/drop the
                                 resize width, re-encode.

The helper is import-safe: no network at import time. ``validate_via_head``
HEAD calls happen inside ``upgrade_photo_urls`` and are opt-in per site.
"""

from __future__ import annotations

import base64
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

_CONFIG_PATH = Path(__file__).parent / "photo_config.json"


@lru_cache(maxsize=1)
def load_photo_config() -> dict:
    """Read photo_config.json. Cached for the lifetime of the process."""
    try:
        return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "sources": {}, "defaults": {}}


def _source_entry(source: str) -> dict:
    cfg = load_photo_config()
    return (cfg.get("sources") or {}).get(source) or {}


def _defaults() -> dict:
    return load_photo_config().get("defaults") or {}


def source_weight(source: str) -> float:
    """Return the per-source deprioritize_weight (default 1.0).

    Used by automation/run.py::_pick_best_photo_url to multiply the
    composite hero score. ``< 1.0`` drops the source below peers.
    """
    entry = _source_entry(source)
    if "deprioritize_weight" in entry:
        return float(entry["deprioritize_weight"])
    if "deprioritize_weight" in _defaults():
        return float(_defaults()["deprioritize_weight"])
    return 1.0


def min_source_long_side_px(source: str) -> int:
    """Return the per-source min source long-side gate (default 1080)."""
    entry = _source_entry(source)
    if "min_source_long_side_px" in entry:
        return int(entry["min_source_long_side_px"])
    if "min_source_long_side_px" in _defaults():
        return int(_defaults()["min_source_long_side_px"])
    return 1080


def upgrade_photo_urls(
    source: str,
    urls: list[str],
    payload: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Apply the configured full-res strategy for ``source`` to ``urls``.

    ``payload`` carries the parsed site response when ``field_swap`` is
    used (e.g. bienesraices' ``prop`` dict). Other strategies ignore it.

    Returns a new list. On any error (bad rule, decode failure) we fall
    back to the original URLs so a misconfiguration never empties the
    photo list — that would silently disable hero downloads.
    """
    if not urls:
        return urls

    entry = _source_entry(source)
    full_res = entry.get("full_res") or {}
    strategy = full_res.get("strategy", "noop")
    rules = full_res.get("rules") or []
    validate = bool(
        full_res.get(
            "validate_via_head",
            _defaults().get("validate_via_head", False),
        )
    )

    try:
        if strategy == "noop":
            upgraded = list(urls)
        elif strategy == "url_replace":
            upgraded = [_apply_url_replace(u, rules) for u in urls]
        elif strategy == "wordpress_size_strip":
            upgraded = [_apply_wordpress_size_strip(u, rules) for u in urls]
        elif strategy == "cloudfront_image_handler":
            upgraded = [_apply_cloudfront_image_handler(u, rules) for u in urls]
        elif strategy == "field_swap":
            upgraded = _apply_field_swap(urls, payload, rules)
        else:
            upgraded = list(urls)
    except Exception:
        return list(urls)

    if validate:
        upgraded = [
            _head_validated(new, original)
            for new, original in zip(upgraded, urls)
        ]
    return upgraded


# ─── strategies ──────────────────────────────────────────────────────────


def _apply_url_replace(url: str, rules: list[dict]) -> str:
    """Apply each rule's match → replace against the URL string.

    Rules apply in order. Set ``regex: true`` to treat ``match`` as a
    regex (default literal). The replacement format mirrors stdlib —
    ``re.sub`` for regex rules, ``str.replace`` for literal rules.
    """
    out = url
    for rule in rules:
        match = rule.get("match")
        replace = rule.get("replace", "")
        if not match:
            continue
        if rule.get("regex"):
            out = re.sub(match, replace, out)
        else:
            out = out.replace(match, replace)
    return out


def _apply_wordpress_size_strip(url: str, rules: list[dict]) -> str:
    """Strip the ``-WIDTHxHEIGHT`` suffix WP inserts into size variants.

    When ``rules`` is empty this falls back to the canonical regex
    ``-\\d+x\\d+(\\.[a-z0-9]+)$`` → ``\\1``. A non-empty ``rules`` list
    lets per-site overrides extend the pattern without forking the
    strategy name.
    """
    if rules:
        return _apply_url_replace(url, rules)
    return re.sub(r"-\d+x\d+(\.[a-z0-9]+)$", r"\1", url, flags=re.IGNORECASE)


def _apply_field_swap(
    urls: list[str],
    payload: Optional[dict],
    rules: list[dict],
) -> list[str]:
    """Swap low-res URLs for a high-res sibling field on the payload.

    Each rule may declare ``from_field`` + ``to_field``. When the
    payload exposes ``to_field`` (a string URL or list of strings), the
    matching entries replace ``urls``. Missing fields fall back to the
    original list so a partial config never empties the photo set.
    """
    if not payload:
        return list(urls)
    upgraded = list(urls)
    for rule in rules:
        to_field = rule.get("to_field")
        if not to_field or to_field not in payload:
            continue
        value = payload.get(to_field)
        if isinstance(value, str) and value.startswith("http"):
            upgraded = [value] + [u for u in upgraded if u != value]
        elif isinstance(value, list):
            new_urls = [v for v in value if isinstance(v, str) and v.startswith("http")]
            if new_urls:
                upgraded = new_urls + [u for u in upgraded if u not in new_urls]
    return upgraded


def _apply_cloudfront_image_handler(url: str, rules: list[dict]) -> str:
    """Decode a base64 AWS image-handler payload, mutate resize, re-encode.

    AWS Serverless Image Handler URLs encode the transform as a base64
    blob in the path: ``https://<cdn>/<base64-json>`` where the JSON is
    e.g. ``{"bucket":"x","key":"y","edits":{"resize":{"width":1024}}}``.

    Supported rule keys:
    - ``drop_resize``: bool — remove the ``resize`` edit entirely so the
      origin serves the source-resolution image.
    - ``raise_resize_to``: int — set ``edits.resize.width`` to this value
      (and remove ``height`` to preserve aspect ratio).
    """
    parts = url.split("/")
    if not parts:
        return url
    last = parts[-1]
    # Image-handler payloads are URL-safe base64 of UTF-8 JSON. Anything
    # that doesn't decode + parse → not a payload, leave the URL alone.
    try:
        padded = last + "=" * (-len(last) % 4)
        decoded = base64.b64decode(padded, validate=False).decode("utf-8")
        cfg = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return url
    if not isinstance(cfg, dict) or "edits" not in cfg:
        return url

    edits = cfg.get("edits") or {}
    for rule in rules:
        if rule.get("drop_resize"):
            edits.pop("resize", None)
        if "raise_resize_to" in rule:
            target = int(rule["raise_resize_to"])
            resize = edits.get("resize") or {}
            if not isinstance(resize, dict):
                resize = {}
            resize["width"] = target
            resize.pop("height", None)
            edits["resize"] = resize
    cfg["edits"] = edits
    encoded = base64.b64encode(
        json.dumps(cfg, separators=(",", ":")).encode("utf-8")
    ).decode("ascii").rstrip("=")
    parts[-1] = encoded
    return "/".join(parts)


# ─── HEAD validation ────────────────────────────────────────────────────


def _head_validated(new_url: str, fallback_url: str) -> str:
    """Issue a HEAD against ``new_url``; on >= 400 or error use ``fallback_url``."""
    if new_url == fallback_url:
        return new_url
    try:
        import httpx
    except ImportError:
        return fallback_url
    try:
        r = httpx.head(new_url, timeout=3.0, follow_redirects=True)
        if r.status_code >= 400:
            return fallback_url
    except Exception:
        return fallback_url
    return new_url
