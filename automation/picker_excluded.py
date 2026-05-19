"""Persistent picker-exclusion cache.

A photo whose cheap_quality_score falls below
``photo_quality.picker_min_cheap_score()`` is too poor to ever justify a
VLM booster call. We flag it once and remember the verdict in
``web/data/picker_excluded.json`` so future nightly runs (and the one-off
``repick_heroes.py`` CLI) skip both the floor evaluation AND the
aesthetic-vision call for those candidates.

Schema mirrors ``web/data/llm_vision_cache.json`` deliberately — same
sha1(bytes)[:16] key, same dict-at-top-level shape, same load-with-fallback
semantics — so a future merge of the two stores stays trivial. Each entry:

    {
      "<sha1_hex_16>": {
        "reason": "cheap_score_below_floor",
        "cheap_score": <int 0-100>,
        "floor": <int 0-100>,
        "ts": "<ISO-8601 UTC>",
      },
      ...
    }

The file is committed to the repo (same convention as the aesthetic
cache) so a CI workflow on a fresh runner has the cache available without
running a warm-up.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent
_STORE_PATH = _REPO_ROOT / "web" / "data" / "picker_excluded.json"


def _cache_key(raw_bytes: bytes) -> str:
    """sha1(bytes)[:16] — matches aesthetic_vision._cache_key so a single
    photo always has the same key in both stores."""
    return hashlib.sha1(raw_bytes).hexdigest()[:16]


def _load() -> dict:
    try:
        return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save(store: dict) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def is_excluded(raw_bytes: bytes, store: Optional[dict] = None) -> bool:
    """O(1) lookup. Pass ``store`` to amortize the JSON read across many
    candidates in one run."""
    if store is None:
        store = _load()
    return _cache_key(raw_bytes) in store


def mark_excluded(
    raw_bytes: bytes,
    *,
    cheap_score: int,
    floor: int,
    reason: str = "cheap_score_below_floor",
    store: Optional[dict] = None,
    save: bool = True,
) -> dict:
    """Add a candidate to the exclusion store. Returns the store (loaded
    fresh if not passed). When ``save=False`` the caller is responsible
    for invoking :func:`save_store` after batching mutations — useful for
    a many-candidate loop in run.py / repick_heroes.py.
    """
    if store is None:
        store = _load()
    store[_cache_key(raw_bytes)] = {
        "reason": reason,
        "cheap_score": int(cheap_score),
        "floor": int(floor),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    if save:
        _save(store)
    return store


def load_store() -> dict:
    """Public re-export for callers that want to amortize the read."""
    return _load()


def save_store(store: dict) -> None:
    """Public re-export."""
    _save(store)


def _set_store_path_for_testing(path: Path) -> None:
    """Tests redirect the on-disk store into tmp_path to avoid mutating
    the real ``web/data/picker_excluded.json``."""
    global _STORE_PATH
    _STORE_PATH = path
