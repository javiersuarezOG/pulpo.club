"""Safety guarantee tests for automation/posthog_client.py.

Telemetry must NEVER block the pipeline. The two failure modes that the
client absorbs silently are:
  1. POSTHOG_PROJECT_TOKEN missing (CI without the secret, local runs)
  2. The posthog SDK import failing or raising at runtime

Both must result in capture() being a no-op rather than propagating.
"""
from __future__ import annotations
import sys

import pytest


@pytest.fixture(autouse=True)
def _reset_module(monkeypatch):
    """Reset the singleton's module-level state. Earlier tests in the suite
    may have imported automation.run (which imports posthog_client at module
    load) with POSTHOG_PROJECT_TOKEN set in env, leaving _client populated.
    sys.modules pop alone doesn't unwind that since `from automation import
    posthog_client` re-binds to the cached submodule. Mutate state directly.
    """
    monkeypatch.delenv("POSTHOG_PROJECT_TOKEN", raising=False)
    if "automation.posthog_client" in sys.modules:
        mod = sys.modules["automation.posthog_client"]
        setattr(mod, "_client", None)
        setattr(mod, "_init_attempted", False)
        setattr(mod, "_run_id", None)
    yield


def test_capture_is_noop_without_token():
    """No env token → capture returns silently, no client instantiated."""
    from automation import posthog_client
    posthog_client.set_run_id("test-run-id")
    posthog_client.capture("pipeline_started", {"sources_count": 3})
    assert posthog_client._client is None


def test_capture_swallows_sdk_errors(monkeypatch):
    """SDK present but client.capture raises → no exception escapes."""
    monkeypatch.setenv("POSTHOG_PROJECT_TOKEN", "phc_dummy_for_test")
    from automation import posthog_client

    class _BrokenClient:
        def capture(self, *_, **__):
            raise RuntimeError("simulated SDK failure")

        def flush(self):
            pass

    monkeypatch.setattr(posthog_client, "_client", _BrokenClient())
    monkeypatch.setattr(posthog_client, "_init_attempted", True)
    posthog_client.capture("pipeline_started", {"foo": "bar"})


def test_set_run_id_returns_uuid_when_unset():
    from automation import posthog_client
    rid = posthog_client.set_run_id()
    assert isinstance(rid, str) and len(rid) >= 32


def test_set_run_id_accepts_explicit():
    from automation import posthog_client
    rid = posthog_client.set_run_id("explicit-id")
    assert rid == "explicit-id"
