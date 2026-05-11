"""PostHog server-side client for pipeline telemetry.

Module-level singleton. Reads POSTHOG_PROJECT_TOKEN + POSTHOG_HOST from
env. When the token is missing or the SDK import fails, capture() is a
silent no-op (CI runs without the secret, local invocations without the
env var, the SDK package not installed yet, etc.). Never raises —
telemetry MUST NOT block the pipeline.

Identity model:
- distinct_id is fixed to "pipeline:nightly" so every pipeline event
  buckets under one identity (required for PostHog funnel queries to
  chain events from a single run).
- Per-run drill-down comes from the `run_id` property — UUID4 generated
  once per `automation.run` invocation via set_run_id(), threaded onto
  every subsequent capture() automatically.

Flushing: atexit hook calls _flush() so buffered events ship before the
process dies (including SystemExit from the regression guard, scraper
crashes, KeyboardInterrupt).
"""
from __future__ import annotations
import atexit
import os
import uuid
from typing import Any

_client: Any = None
_init_attempted = False
_run_id: str | None = None


def _init() -> Any:
    global _client, _init_attempted
    if _init_attempted:
        return _client
    _init_attempted = True
    token = os.getenv("POSTHOG_PROJECT_TOKEN", "").strip()
    if not token:
        return None
    host = os.getenv("POSTHOG_HOST", "https://eu.i.posthog.com").strip()
    try:
        from posthog import Posthog  # type: ignore
        _client = Posthog(project_api_key=token, host=host)
        atexit.register(_flush)
    except Exception as e:
        print(f"[posthog] init failed (non-fatal): {e!r}")
        _client = None
    return _client


def set_run_id(run_id: str | None = None) -> str:
    """Set the run_id property attached to every subsequent capture().

    Call once at the top of a pipeline run. Returns the generated id so
    callers can log it for cross-referencing with PostHog dashboards.
    """
    global _run_id
    _run_id = run_id or str(uuid.uuid4())
    return _run_id


def capture(event: str, props: dict[str, Any] | None = None) -> None:
    """Capture a pipeline event. Silent no-op when telemetry is disabled."""
    client = _init()
    if client is None:
        return
    payload = dict(props or {})
    if _run_id:
        payload.setdefault("run_id", _run_id)
    try:
        client.capture(distinct_id="pipeline:nightly", event=event, properties=payload)
    except Exception as e:
        print(f"[posthog] capture failed (non-fatal): {e!r}")


def _flush() -> None:
    if _client is None:
        return
    try:
        _client.flush()
    except Exception:
        pass
