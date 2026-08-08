"""ig_queue_io.py — one normaliser for web/data/ig_queue.json.

The queue has been serialised in TWO shapes historically, and they broke the
pipeline against each other (2026-08-02 incident):

  - a DICT ``{"version","batch","items":[...]}`` — what ig_autopilot,
    ig_publish, and ig_queue_apply all expect; and
  - a bare top-level LIST ``[item, item, ...]`` — what the manual staging
    script ``scripts/build_ig_batch.py`` emitted, which crashed the
    publisher (``list.get``), the generator (``list.setdefault``), and the
    operator skip tool (``not isinstance(obj, dict)``) all at once.

This module is the single seam: read EITHER shape → ``(items, meta)``, and
always hand back a DICT payload so every reader/writer agrees again. Pure,
no I/O beyond ``load``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Tuple

_DEFAULT_META = {"version": 1, "batch": "autopilot"}


def normalize(data) -> Tuple[list, dict]:
    """Return ``(items, meta)`` from a parsed queue that may be a list, a
    dict, or junk. ``meta`` is the dict wrapper minus ``items`` (defaults for
    a bare list)."""
    if isinstance(data, list):
        return data, dict(_DEFAULT_META)
    if isinstance(data, dict):
        items = data.get("items") or []
        meta = {k: v for k, v in data.items() if k != "items"} or dict(_DEFAULT_META)
        return list(items), meta
    return [], dict(_DEFAULT_META)


def as_dict(items: list, meta: dict | None = None) -> dict:
    """Wrap ``items`` in the canonical dict payload (the shape we always
    write). ``items`` is embedded by reference so in-place edits persist."""
    m = dict(_DEFAULT_META)
    m.update(meta or {})
    return {**m, "items": items}


def load(path) -> Tuple[list, dict]:
    """Read the queue file in either shape → ``(items, meta)``; ``([], meta)``
    when the file is missing."""
    p = Path(path)
    if not p.exists():
        return [], dict(_DEFAULT_META)
    return normalize(json.loads(p.read_text(encoding="utf-8")))
