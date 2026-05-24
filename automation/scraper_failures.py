"""Diagnostic-capture helper for scraper failures.

When a scraper raises or silently returns zero records, we want enough
context to either auto-repair (Phase 4) or hand a clean ticket to a
human. Today the only signal that leaves the runner is the truncated
``error_msg`` field in ``source_health_history.jsonl`` — 300 characters
of a Python repr, no response body, no headers. That's been
insufficient twice (realtyelsalvador's WAF block, encuent24's quiet
yield collapse). This module fixes the gap.

Output
------
One JSON file per failure at
``web/data/scraper_failures/<source>_<ts>_<failure_id>.json`` with:

    {
      "failure_id":  "abc12345",      # short, deterministic per (source, ts)
      "source":      "realtyelsalvador",
      "ts":          "2026-05-24T06:08:54.538512+00:00",
      "kind":        "exception" | "empty_yield",
      "exception":   {"class": "HTTPStatusError", "repr": "...", ...} | null,
      "request":     {"method": "GET", "url": "...", "headers": {...}} | null,
      "response":    {"status_code": 403, "headers": {...}, "body_snippet": "..."} | null,
      "context":     {...}             # caller-supplied breadcrumbs
    }

The pipeline appends a pointer (``failure_id`` field) to
``source_health_history.jsonl`` for the matching row so dashboards and
the watchdog can find the snapshot.

Telemetry must never block a run
--------------------------------
Every public function in this module catches its own exceptions and
returns ``None`` on internal failure. If the disk is full, the writer
package is broken, or the response is too large to serialize, we drop
the snapshot silently and let the nightly continue. The cost of losing
one diagnostic is far smaller than the cost of an aborted nightly.
"""
from __future__ import annotations
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


REPO = Path(__file__).resolve().parents[1]
FAILURES_DIR = REPO / "web" / "data" / "scraper_failures"

# Cap on captured response body bytes. Big enough to inspect a typical
# Cloudflare interstitial / WordPress error page; small enough that a
# misbehaving source dumping 50MB JSON doesn't fill the runner disk.
BODY_SNIPPET_BYTES = 4096

# How many failure snapshots to retain per source. Older files beyond
# this count get pruned on each write. Pulpo runs nightly, so 30 retains
# ~one month of history per source — plenty for auto-repair diffing and
# watchdog trend analysis without unbounded disk growth.
RETAIN_PER_SOURCE = 30


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_id(source: str, ts: str, salt: str = "") -> str:
    """Deterministic 8-char id from (source, ts, salt)."""
    h = hashlib.sha256(f"{source}|{ts}|{salt}".encode("utf-8")).hexdigest()
    return h[:8]


def _serialize_exception(exc: Optional[BaseException]) -> Optional[dict]:
    if exc is None:
        return None
    try:
        return {
            "class":   type(exc).__name__,
            "module":  type(exc).__module__,
            "repr":    repr(exc)[:1000],
            "message": (str(exc) or "")[:1000],
        }
    except Exception:
        return {"class": "Unknown", "repr": "<unserializable>", "message": ""}


def _serialize_response(response: Any) -> Optional[dict]:
    """Best-effort capture of an httpx.Response or Playwright Response.

    The two libraries have different APIs — we duck-type via attribute
    access. Any AttributeError or serialization failure → return None.
    """
    if response is None:
        return None
    try:
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(response, "status", None)  # Playwright Response
        if callable(status):
            status = status()
        # Headers can be a dict, an httpx Headers (multidict), or a method.
        raw_headers = getattr(response, "headers", None)
        if callable(raw_headers):
            raw_headers = raw_headers()
        headers: dict[str, str] = {}
        if raw_headers is not None:
            try:
                for k, v in dict(raw_headers).items():
                    headers[str(k)[:128]] = str(v)[:512]
            except Exception:
                pass
        # Body via .text (httpx) or .text() coroutine (Playwright is async,
        # we don't await — Playwright callers pass body separately if needed).
        body_snippet: Optional[str] = None
        text_attr = getattr(response, "text", None)
        if isinstance(text_attr, str):
            body_snippet = text_attr[:BODY_SNIPPET_BYTES]
        elif callable(text_attr):
            try:
                body_snippet = str(text_attr())[:BODY_SNIPPET_BYTES]
            except Exception:
                pass
        return {
            "status_code":  int(status) if status is not None else None,
            "headers":      headers or None,
            "body_snippet": body_snippet,
        }
    except Exception:
        return None


def _prune_old_snapshots(source: str, keep: Optional[int] = None) -> None:
    """Delete oldest ``<source>_*.json`` beyond ``keep``. Silent on error.

    ``keep`` resolves at call time (not import time) so tests that
    monkeypatch ``RETAIN_PER_SOURCE`` work as expected. Sort uses the
    timestamp embedded in the filename (set by the writer) rather than
    ``mtime`` — multiple writes in the same second can share an mtime
    and break the ordering on fast filesystems.
    """
    if keep is None:
        keep = RETAIN_PER_SOURCE
    try:
        files = sorted(
            FAILURES_DIR.glob(f"{source}_*.json"),
            key=lambda p: p.name,  # filename contains the iso timestamp
            reverse=True,
        )
        for stale in files[keep:]:
            try:
                stale.unlink()
            except OSError:
                pass
    except Exception:
        pass


def write_failure_snapshot(
    source: str,
    *,
    kind: str = "exception",
    exception: Optional[BaseException] = None,
    response: Any = None,
    request_url: Optional[str] = None,
    request_method: str = "GET",
    request_headers: Optional[dict] = None,
    request_body: Optional[Any] = None,
    context: Optional[dict] = None,
    ts: Optional[str] = None,
) -> Optional[str]:
    """Write a diagnostic snapshot for ``source``. Returns the failure_id.

    Returns ``None`` on internal failure — telemetry never blocks the
    pipeline. Callers should treat the failure_id as opaque and pass it
    into ``source_health_history.jsonl`` for cross-referencing.
    """
    try:
        FAILURES_DIR.mkdir(parents=True, exist_ok=True)
        ts = ts or _now_iso()

        # Salt the id with the exception class so two failures in the same
        # second (different errors) don't collide.
        salt = type(exception).__name__ if exception else kind
        failure_id = _short_id(source, ts, salt)

        # Sanitize ts for filename use (replace ':' which is illegal on Windows).
        ts_safe = ts.replace(":", "-")
        path = FAILURES_DIR / f"{source}_{ts_safe}_{failure_id}.json"

        payload: dict = {
            "failure_id": failure_id,
            "source":     source,
            "ts":         ts,
            "kind":       kind,
            "exception":  _serialize_exception(exception),
            "request":    None,
            "response":   _serialize_response(response),
            "context":    context or {},
        }

        if request_url:
            req_headers_clean: dict[str, str] = {}
            if request_headers:
                try:
                    for k, v in dict(request_headers).items():
                        # Don't leak auth / cookie material in artifacts.
                        kl = str(k).lower()
                        if kl in ("authorization", "cookie", "x-api-key"):
                            req_headers_clean[str(k)[:64]] = "<redacted>"
                        else:
                            req_headers_clean[str(k)[:64]] = str(v)[:256]
                except Exception:
                    pass
            req_block: dict = {
                "method":  request_method,
                "url":     request_url[:2048],
                "headers": req_headers_clean or None,
            }
            if request_body is not None:
                try:
                    req_block["body_snippet"] = str(request_body)[:1024]
                except Exception:
                    pass
            payload["request"] = req_block

        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _prune_old_snapshots(source)
        return failure_id
    except Exception as e:
        # Last-resort: print to stderr so the nightly log shows we tried.
        try:
            print(f"[scraper_failures] capture failed for {source}: {e}")
        except Exception:
            pass
        return None


def is_enabled() -> bool:
    """Returns False when ``PULPO_DISABLE_FAILURE_CAPTURE=1`` (test escape hatch)."""
    return os.environ.get("PULPO_DISABLE_FAILURE_CAPTURE") != "1"
