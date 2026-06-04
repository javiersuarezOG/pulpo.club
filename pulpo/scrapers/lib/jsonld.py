"""JSON-LD finder — extract structured-data blocks from HTML.

Wraps the pattern lifted from `encuentra24.py` and `realtyelsalvador.py`
where the scraper greps `<script type="application/ld+json">` blocks
and filters by `@type`. Real-estate sites typically expose listings as
`Product`, `Residence`, `Place`, or `RealEstateListing` — picking the
right type is per-source, hence the optional `schema_type` filter.

The parser is tolerant:
- Empty / whitespace-only scripts return [].
- JSON parse errors are silently skipped (returned alongside good
  blocks rather than raising — partial data > zero data when one
  block on the page is malformed).
- Both single-object payloads and arrays are normalized to a flat list.
- @graph arrays are flattened (common in WordPress JSON-LD).
"""
from __future__ import annotations

import json
import re
from typing import Optional


_SCRIPT_RE = re.compile(
    r'<script[^>]+type\s*=\s*["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


def find_jsonld(html: str, schema_type: Optional[str] = None) -> list[dict]:
    """Extract every JSON-LD block from `html`.

    Args:
        html: page body as a string.
        schema_type: optional ``@type`` filter (e.g. ``"Product"`` or
            ``"Residence"``). Matches both string @type and array @type
            (Schema.org allows arrays). When None, every block is
            returned regardless of type.

    Returns: list of dicts. May be empty.
    """
    if not html:
        return []
    out: list[dict] = []
    for raw in _SCRIPT_RE.findall(html):
        block = (raw or "").strip()
        if not block:
            continue
        try:
            parsed = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        for entry in _flatten(parsed):
            if not isinstance(entry, dict):
                continue
            if schema_type is None or _type_matches(entry, schema_type):
                out.append(entry)
    return out


def _flatten(payload: object) -> list[object]:
    """Normalize single-object / array / @graph payloads to a flat list."""
    if isinstance(payload, list):
        result: list[object] = []
        for item in payload:
            result.extend(_flatten(item))
        return result
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        if isinstance(graph, list):
            return _flatten(graph)
        return [payload]
    return []


def _type_matches(entry: dict, want: str) -> bool:
    t = entry.get("@type")
    if isinstance(t, str):
        return t == want
    if isinstance(t, list):
        return want in t
    return False
