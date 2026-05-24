"""Per-source scraper policy — single source of truth for how each
source should be crawled and how its failures should be handled.

Why a Python dict (not YAML)
----------------------------
1. No new runtime dep — yaml would force pyyaml into requirements.
2. Type-checkable. The `Policy` dataclass surfaces typos at import time.
3. Refactor-safe — IDEs follow renames.
4. Symmetric with `automation/property_types.py`, the other config-as-code
   module in this project.

Fields
------
- ``transport``         "httpx" | "playwright" — informational, used by
                        ``_runtime.polite_get`` callers to dispatch.
- ``rate_limit_rps``    Token-bucket cap, requests/sec. Honored by
                        ``_runtime.RateLimiter`` per-source instance.
- ``jitter_ms``         (min, max) — uniform random pause added before
                        each request, on top of the rate-limit budget.
- ``retry_max``         Number of attempts on transient failure (429,
                        5xx, network). Includes the first attempt.
- ``retry_backoff_base_s``  Exponential backoff base. Sleep on attempt
                        N is ``base * 2 ** (N-1)``; capped at 60s.
                        Honors ``Retry-After`` headers when present.
- ``user_agent_pool``   Key into ``_runtime.UA_POOLS``. The pool is
                        rotated per request to avoid single-UA fingerprint.
- ``auto_repair``       When True, Phase-4 auto-repair workflow may
                        propose a fix on failure. When False, failures
                        go straight to "needs human" (used for WAF /
                        proxy / auth problems an LLM can't fix).
- ``capture_failure_snapshot``  When True, ``automation.scraper_failures``
                        dumps response body + headers on failure. Default
                        True; only disable if the source emits secrets in
                        responses (none today).

Adding a new source
-------------------
1. Add an entry to ``POLICIES`` keyed by the source's ``slug``.
2. If you skip some fields, the defaults in ``Policy()`` apply.
3. The runtime falls back to ``DEFAULT_POLICY`` for unknown sources so
   one-off tests / new sources work without a config entry first.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Literal


Transport = Literal["httpx", "playwright"]


@dataclass(frozen=True)
class Policy:
    transport: Transport = "httpx"
    rate_limit_rps: float = 0.5            # 1 request every 2 seconds
    jitter_ms: tuple[int, int] = (200, 800)
    retry_max: int = 3
    retry_backoff_base_s: float = 1.5
    user_agent_pool: str = "default"
    auto_repair: bool = True
    capture_failure_snapshot: bool = True


DEFAULT_POLICY = Policy()


# Per-source overrides. Sources not listed here use DEFAULT_POLICY.
# Field-level defaults from ``Policy`` apply to anything omitted.
POLICIES: dict[str, Policy] = {
    # --- Working sources (no behavioral change at default policy) ----
    "bienesraices":     Policy(transport="httpx", rate_limit_rps=0.5),
    "remax":            Policy(transport="httpx", rate_limit_rps=0.5),
    "goodlife":         Policy(transport="httpx", rate_limit_rps=0.5),
    "oceanside":        Policy(transport="httpx", rate_limit_rps=2.0),  # single fast API call today
    "century21":        Policy(transport="httpx", rate_limit_rps=0.5),
    "nexo":             Policy(transport="httpx", rate_limit_rps=0.5),

    # --- New sources (PR-C ... PR-F) ---
    # CityMax: SSR-parse the Next.js Flight payload, 12 listings per page.
    # Public site so the safari_macos UA pool matches the typical visitor
    # fingerprint and avoids the bot-pool path.
    "citymax":          Policy(
        transport="httpx",
        rate_limit_rps=0.5,
        user_agent_pool="safari_macos",
    ),

    # --- encuent24: Playwright source, polite by default. Phase 3 will
    # widen its category set ~6x; the polite layer keeps that respectful.
    "encuentra24": Policy(
        transport="playwright",
        rate_limit_rps=0.5,
        jitter_ms=(400, 1200),
        user_agent_pool="safari_macos",
    ),

    # --- realtyelsalvador: header tweaks already attempted and failed
    # against the WP REST endpoint (Cloudflare WAF, IP-based). Phase 2
    # rewrites this to HTML scrape. Auto-repair is OFF — an LLM can't
    # bypass a WAF; failures need human attention.
    "realtyelsalvador": Policy(
        transport="httpx",
        rate_limit_rps=0.5,
        auto_repair=False,
    ),
}


def get_policy(source: str) -> Policy:
    """Return the policy for ``source``, or ``DEFAULT_POLICY`` if unknown."""
    return POLICIES.get(source, DEFAULT_POLICY)


def with_override(source: str, **overrides) -> Policy:
    """Tests only — return a per-call modified copy without mutating POLICIES."""
    return replace(get_policy(source), **overrides)
