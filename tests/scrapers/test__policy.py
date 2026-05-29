"""Unit tests for pulpo/scrapers/_policy.py — per-source scraper policy."""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers._policy import (  # noqa: E402
    DEFAULT_POLICY,
    POLICIES,
    Policy,
    get_policy,
    with_override,
)


def test_default_policy_field_defaults():
    p = DEFAULT_POLICY
    assert p.transport == "httpx"
    assert p.rate_limit_rps == 0.5
    assert p.jitter_ms == (200, 800)
    assert p.retry_max == 3
    assert p.user_agent_pool == "default"
    assert p.auto_repair is True
    assert p.capture_failure_snapshot is True


def test_unknown_source_returns_default():
    p = get_policy("does-not-exist")
    assert p is DEFAULT_POLICY


def test_known_source_returns_override():
    p = get_policy("encuentra24")
    assert p.transport == "playwright"
    assert p.user_agent_pool == "safari_macos"


def test_realtyelsalvador_auto_repair_disabled():
    """Reason: WAF / IP-based blocks aren't fixable by an LLM patch — we
    don't want Phase-4 auto-repair burning cycles on it."""
    p = get_policy("realtyelsalvador")
    assert p.auto_repair is False


def test_with_override_does_not_mutate_registry():
    original = get_policy("encuentra24")
    modified = with_override("encuentra24", rate_limit_rps=99.0)
    assert modified.rate_limit_rps == 99.0
    # Registry untouched.
    assert get_policy("encuentra24") is original
    assert get_policy("encuentra24").rate_limit_rps == original.rate_limit_rps


def test_policy_is_immutable():
    """frozen=True dataclass — mutation must raise."""
    import dataclasses
    p = get_policy("encuentra24")
    try:
        p.rate_limit_rps = 99.0  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Policy should be frozen")


def test_all_registered_sources_have_valid_transports():
    for source, policy in POLICIES.items():
        assert policy.transport in ("httpx", "playwright", "curl_cffi"), (
            f"{source} has invalid transport {policy.transport!r}"
        )
        assert policy.rate_limit_rps >= 0
        assert 0 <= policy.jitter_ms[0] <= policy.jitter_ms[1]
        assert policy.retry_max >= 1
