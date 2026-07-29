"""Content + perceptual hashing for within-listing photo dedup.

Image-pipeline audit 2026-07-29 (PR-F). A listing's photo_urls routinely
carry the same image twice — the broker's gallery repeats the hero, or
serves the same file under two CDN URLs. Before this module the pipeline
scored, and the gallery shipped, both copies.

Two hashes, both pure-Pillow (no new dependency):

- ``content_sha1(bytes)`` — sha1(bytes)[:16]. Byte-identical duplicates.
  Deliberately the SAME key convention as
  ``automation.picker_excluded._cache_key`` and
  ``automation.aesthetic_vision._cache_key`` so a photo has ONE identity
  across every store.

- ``dhash(bytes)`` — 64-bit difference hash. Catches re-encoded /
  re-compressed / lightly-resized near-duplicates that content_sha1
  misses (different bytes, same picture). Returns None when the image
  can't decode — callers fall back to exact-hash only.

``hamming(a, b)`` is the bit-distance between two dhashes; ``<= 6`` on a
64-bit hash is the near-duplicate threshold (≈ 90% agreement), tuned
conservative so two genuinely different photos never collapse.

``dedupe_within_listing(candidates)`` is the one entry point the pipeline
calls — pure, in-memory, order-preserving, mutates nothing it isn't
given.
"""
from __future__ import annotations

import hashlib
import io
from typing import Optional

# 64-bit dhash: 8 rows × 8 comparisons. Near-duplicate when the two
# hashes differ by at most this many bits. Conservative on purpose — a
# real second photo of the same property differs by far more than 6 bits.
DHASH_HAMMING_THRESHOLD = 6

# Minimum "structure" (set-bit population) a dhash must carry before it's
# eligible for perceptual near-matching. A flat / near-flat image (solid
# placeholder tile, blank swatch) produces a degenerate all-0 or all-1
# dhash; two DIFFERENT flat images would then falsely near-match at
# Hamming 0. Requiring both hashes to sit inside the band
# [MIN_STRUCTURE_BITS, 64 - MIN_STRUCTURE_BITS] means low-detail images
# only ever dedupe on an EXACT byte match, never perceptually. Real
# photos carry ~20-45 set bits, comfortably inside the band.
MIN_STRUCTURE_BITS = 8


def content_sha1(raw_bytes: bytes) -> str:
    """sha1(bytes)[:16] — the shared content-identity key. Matches
    picker_excluded._cache_key / aesthetic_vision._cache_key so a photo
    keys identically in every store."""
    return hashlib.sha1(raw_bytes).hexdigest()[:16]


def dhash(raw_bytes: bytes, hash_size: int = 8) -> Optional[int]:
    """Return a ``hash_size**2``-bit difference hash as an int, or None
    when the image can't decode.

    Grayscale → resize to (hash_size+1, hash_size) → for each row, bit is
    1 where the left pixel is brighter than its right neighbor. Robust to
    re-compression, mild resizing, and format changes; sensitive to real
    composition differences.
    """
    if not raw_bytes:
        return None
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img = img.convert("L").resize(
            (hash_size + 1, hash_size), Image.Resampling.LANCZOS
        )
    except Exception:
        return None

    # getdata() is deprecated in Pillow 14; tobytes() on an "L" image is
    # a flat row-major byte string of pixel values — same data, stable
    # across versions.
    pixels = img.tobytes()
    width = hash_size + 1
    bits = 0
    bit_index = 0
    for row in range(hash_size):
        row_start = row * width
        for col in range(hash_size):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            if left > right:
                bits |= 1 << bit_index
            bit_index += 1
    return bits


def hamming(a: int, b: int) -> int:
    """Bit-distance between two dhash ints."""
    return int((a ^ b).bit_count())


def dedupe_within_listing(
    candidates: list[dict],
    *,
    threshold: int = DHASH_HAMMING_THRESHOLD,
) -> list[dict]:
    """Mark duplicate candidates within ONE listing's pool, in place.

    Each candidate dict is expected to carry ``content`` (bytes) and a
    ``cheap_score`` (int). For each group of exact- or near-duplicate
    images, the highest ``cheap_score`` candidate is the representative
    (kept), and the rest are stamped:

        candidate["is_duplicate"] = True
        candidate["dup_of"] = <representative url>
        candidate["dup_reason"] = "exact" | "near"

    Also stamps ``content_sha1`` and ``dhash`` on every candidate for
    reuse (sidecar persistence, cross-run skip). Representatives get
    ``is_duplicate = False``. Order is preserved. Returns the same list.

    Scoping is strictly within the passed pool — cross-listing dedup is a
    deliberate non-goal here (two listings legitimately share a stock
    photo far less often than one gallery repeats an image, and a
    cross-listing merge would need listing identity this function does
    not have).
    """
    # First pass: stamp hashes.
    for c in candidates:
        raw = c.get("content")
        if not raw:
            c["content_sha1"] = None
            c["dhash"] = None
            c["is_duplicate"] = False
            continue
        c["content_sha1"] = content_sha1(raw)
        c["dhash"] = dhash(raw)
        c["is_duplicate"] = False

    # Second pass: greedy grouping. Walk in order; each candidate either
    # joins an existing representative's group (marking it duplicate) or
    # becomes a new representative. "Representative" = highest cheap_score
    # in the group, so if a later candidate outscores the current rep we
    # swap roles.
    representatives: list[dict] = []
    for c in candidates:
        if not c.get("content"):
            continue
        matched_rep = None
        for rep in representatives:
            if _same_image(c, rep, threshold):
                matched_rep = rep
                break
        if matched_rep is None:
            representatives.append(c)
            continue
        # Duplicate found — keep the higher cheap_score as representative.
        c_score = c.get("cheap_score") or 0
        rep_score = matched_rep.get("cheap_score") or 0
        if c_score > rep_score:
            # Promote c; demote the old rep into c's duplicate group.
            _mark_duplicate(matched_rep, of=c)
            representatives[representatives.index(matched_rep)] = c
        else:
            _mark_duplicate(c, of=matched_rep)
    return candidates


def _has_structure(h: int) -> bool:
    """True when a dhash carries enough tonal variation to be trusted for
    perceptual matching (i.e. it's not a flat / near-flat image)."""
    bits = int(h.bit_count())
    return MIN_STRUCTURE_BITS <= bits <= (64 - MIN_STRUCTURE_BITS)


def _same_image(a: dict, b: dict, threshold: int) -> bool:
    if a.get("content_sha1") and a["content_sha1"] == b.get("content_sha1"):
        return True
    ha, hb = a.get("dhash"), b.get("dhash")
    if ha is None or hb is None:
        return False
    # Only trust the perceptual hash when BOTH images have real structure.
    # Flat images fall through to exact-match only (handled above).
    if not (_has_structure(ha) and _has_structure(hb)):
        return False
    return hamming(ha, hb) <= threshold


def _mark_duplicate(dup: dict, *, of: dict) -> None:
    dup["is_duplicate"] = True
    dup["dup_of"] = of.get("url")
    if dup.get("content_sha1") and dup["content_sha1"] == of.get("content_sha1"):
        dup["dup_reason"] = "exact"
    else:
        dup["dup_reason"] = "near"
