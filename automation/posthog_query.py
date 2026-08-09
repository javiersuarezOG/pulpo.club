"""posthog_query.py — minimal server-side PostHog HogQL reader.

The counterpart to posthog_client.py (which only *writes* events): this
runs a read query against the PostHog query API, mirroring the JS pattern
already in api/admin/newsletter/health.js. Used by ig_learning to pull
per-post attributed signups (the money-metric half of the Growth Hacker
loop).

Endpoint : POST {POSTHOG_HOST}/api/projects/{POSTHOG_PROJECT_ID}/query/
Auth     : Bearer {POSTHOG_PERSONAL_API_KEY}   (a *personal* key, read scope)
Env      : POSTHOG_HOST (default https://eu.posthog.com),
           POSTHOG_PROJECT_ID, POSTHOG_PERSONAL_API_KEY

Contract: soft-fail. Any missing env / import / HTTP / parse trouble
returns None (never raises), so a nightly with the secrets unset simply
degrades to engagement-only learning — the exact v1 behavior. Callers
must handle None.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def available() -> bool:
    """True only when both the read key and project id are present."""
    return bool(_env("POSTHOG_PERSONAL_API_KEY") and _env("POSTHOG_PROJECT_ID"))


def query(hogql: str, *, timeout: float = 30.0) -> Optional[list[dict]]:
    """Run a HogQL query; return a list of row dicts (column name -> value)
    or None on any trouble. Uses stdlib urllib so it works in the pipeline
    without extra deps."""
    if not available():
        return None
    host = _env("POSTHOG_HOST", "https://eu.posthog.com").rstrip("/")
    project = _env("POSTHOG_PROJECT_ID")
    key = _env("POSTHOG_PERSONAL_API_KEY")
    url = f"{host}/api/projects/{project}/query/"
    body = json.dumps({"query": {"kind": "HogQLQuery", "query": hogql}}).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as err:
        print(f"[posthog_query] read failed: {err}")
        return None
    return rows_to_dicts(payload)


def rows_to_dicts(payload: Optional[dict]) -> Optional[list[dict]]:
    """Turn PostHog's {columns, results} into a list of dicts. Pure; None on
    a shape it can't read."""
    if not isinstance(payload, dict):
        return None
    columns = payload.get("columns")
    results = payload.get("results")
    if not isinstance(columns, list) or not isinstance(results, list):
        return None
    out = []
    for row in results:
        if isinstance(row, list) and len(row) == len(columns):
            out.append(dict(zip(columns, row)))
    return out
