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

Day-1 source allowlist (per plan v2) = bienesraices, remax, century21,
oceanside, nexo. All five expose hi-res URLs already, so this module is
a no-op for them today. goodlife + encuentra24 transforms are
implemented but not enabled until Phase 4 of the plan (after the 5
clean sources prove out).
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
