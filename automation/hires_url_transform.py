"""Per-source URL transforms for the hires photo pipeline.

The hires pipeline fetches the broker's NATIVE-resolution photo bytes
(bypassing the down-sample that creates the legacy 600x400 thumbnail).
For most sources the URL emitted by the scraper already points at the
full-resolution image. A few sources need a small rewrite:

- goodlife — WordPress media library serves sized variants with a
  ``-<W>x<H>`` suffix on the filename. Strip the suffix to get the
  original upload.
- encuentra24 — Cloudinary transform token ``t_or_fh_m`` selects a
  medium-fit variant. Replacing with ``t_full`` (or removing entirely)
  yields the source resolution.

Both transforms are intentionally idempotent — re-applying produces
the same output.

This module is the SINGLE place to add per-source URL rewriting. Adding
a new source = add a new ``if source == "<name>"`` branch + a unit test
in ``tests/test_hires_url_transform.py``.

Source-by-source upgrade ceilings, verified 2026-05-20 by probing each
CDN with parameter variants:

- bienesraices — EasyBroker CDN (assets.easybroker.com). URL pattern is
  ``?rasterize=true&version=<ts>`` and the CDN rejects (HTTP 400) every
  other rasterize / width / size variant. Native-res IS the rasterized
  1200×N image. No URL transform possible; the broker's CDN is the
  hard ceiling.
- remax — Two franchises:
    * remax-central.com.sv: ``-large.png`` filename suffix variant
      (not yet investigated; site times out from us-east).
    * remaxcaribbeanandcentralamerica.azureedge.net: already serves
      native-res ``HDPhotos/<file>.png`` (1192×2048+ verified). No
      transform needed.
- oceanside, century21, encuentra24, nexo — small-fleet sources, mostly
  no native-res URLs available from broker.

goodlife + encuentra24 transforms (WordPress size-suffix strip,
Cloudinary t_full) are implemented and active.
"""
from __future__ import annotations

import re

_WP_SIZE_SUFFIX = re.compile(r"-\d+x\d+(\.\w+)$")
_E24_CLOUDINARY_MEDIUM = "/t_or_fh_m/"
_E24_CLOUDINARY_FULL = "/t_full/"


def transform_hires_url(source: str, original_url: str) -> str:
    """Return the broker's full-resolution URL for the given source.

    Idempotent. For sources without a defined transform, returns the URL
    unchanged.
    """
    if not original_url:
        return original_url
    if source == "goodlife":
        return _WP_SIZE_SUFFIX.sub(r"\1", original_url)
    if source == "encuentra24":
        return original_url.replace(_E24_CLOUDINARY_MEDIUM, _E24_CLOUDINARY_FULL)
    return original_url


def describe_transform(source: str) -> str:
    """Return a short human-readable label for the transform applied.

    Used in sidecar metadata for forensic clarity.
    """
    if source == "goodlife":
        return "goodlife-strip-wp-size-suffix"
    if source == "encuentra24":
        return "encuentra24-cloudinary-t-full"
    return "none"
