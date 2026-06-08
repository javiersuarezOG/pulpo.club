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
- ``transport``         "httpx" | "playwright" | "curl_cffi" — informational,
                        used by ``_runtime.polite_get`` callers to dispatch.
                        ``curl_cffi`` is for hosts whose WAFs fingerprint on
                        TLS handshake (JA3/JA4) rather than just IP+UA;
                        bundles real Chrome/Safari handshake bytes via the
                        curl-impersonate fork.
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


Transport = Literal["httpx", "playwright", "curl_cffi"]


# curl_cffi browser impersonation profile. See
# https://github.com/lexiforest/curl_cffi/tree/main/curl_cffi/requests for
# the full pool. We default to a recent Chrome on macOS because that
# fingerprint matches the bulk of regional traffic the target WAFs see
# from real users.
CURL_CFFI_IMPERSONATE_DEFAULT = "chrome124"


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
    # Only consulted when ``transport == "curl_cffi"``. Names a browser
    # fingerprint bundled with curl_cffi (chrome124, safari17_0, ...).
    # Kept separate from ``user_agent_pool`` because the UA string and
    # the TLS fingerprint are independent decisions — curl_cffi sets
    # the handshake, the UA header is still chosen from the pool.
    curl_cffi_impersonate: str = CURL_CFFI_IMPERSONATE_DEFAULT


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
    # nexo: site redesigned to a Vite SPA in 2026-05 and put behind
    # Cloudflare managed-challenge mode. The new backend exposes a public
    # JSON API at /api/v1/public/listings — much cleaner than the old
    # 2017 HTML scrape — but Cloudflare's JA3 fingerprint check rejects
    # bare httpx requests from every IP, residential included. curl_cffi
    # (Chrome handshake impersonation) slips through and the API answers
    # normally. user_agent_pool stays "safari_macos" so the UA header
    # the WAF logs alongside the JA3 also looks like a Mac user.
    "nexo":             Policy(
        transport="curl_cffi",
        rate_limit_rps=0.5,
        user_agent_pool="safari_macos",
    ),

    # --- New sources (PR-C ... PR-F) ---
    # CityMax: SSR-parse the Next.js Flight payload, 12 listings per page.
    # Public site so the safari_macos UA pool matches the typical visitor
    # fingerprint and avoids the bot-pool path.
    #
    # Transport switched to curl_cffi 2026-06-08 after the 2026-06-08
    # nightly (run committed at 35338b1a0) had citymax + citymax_sc +
    # vivolatam (all CityMax-family) flip green→red simultaneously
    # (source_health_history.jsonl: failure_ids 963c2914 / d26d0d05 /
    # 3eafc7bd at 06:44 UTC). Local smoke from a residential Mac IP
    # yielded 3 listings cleanly under httpx; the GitHub Actions runner
    # IP returned empty bodies. Identical symptom class to elagente /
    # realtyelsalvador / nexo / agentiz pre-curl_cffi — TLS-fingerprint
    # WAF gate, not IP-only. Same fix: chrome124 handshake + safari_macos
    # UA so the JA3 and UA the WAF logs are aligned. auto_repair stays
    # False: an LLM can't talk past a WAF.
    "citymax":          Policy(
        transport="curl_cffi",
        rate_limit_rps=0.5,
        user_agent_pool="safari_macos",
        auto_repair=False,
    ),
    # citymax_sc (Santa Cruz / regional CityMax variant): same CityMax
    # CMS as `citymax` above, same WAF event, same fix. Previously had
    # no explicit policy entry — was running under DEFAULT_POLICY which
    # implies httpx. Adding explicitly so the fingerprint switch is
    # visible. failure_id d26d0d05 (2026-06-08 nightly).
    "citymax_sc":       Policy(
        transport="curl_cffi",
        rate_limit_rps=0.5,
        user_agent_pool="safari_macos",
        auto_repair=False,
    ),
    # vivolatam: built on the same CityMax CMS — same WAF rule caught
    # it in the 2026-06-08 outage (failure_id 3eafc7bd). Local smoke
    # yielded 3 fresh listings in 7.5s; runner IP returns empty.
    # Largest yield of the three (148 listings on 2026-06-07's nightly),
    # so a same-day fix is worth it.
    "vivolatam":        Policy(
        transport="curl_cffi",
        rate_limit_rps=0.5,
        user_agent_pool="safari_macos",
        auto_repair=False,
    ),
    # essurf (El Salvador Surf Real Estate): WordPress AgentFire v3 IDX,
    # POST to /wp-json/agentfire/v2/listing3/listings, 9 listings per
    # page across 24 pages. Light traffic so a higher rps is fine.
    "essurf":           Policy(
        transport="httpx",
        rate_limit_rps=1.0,
        user_agent_pool="safari_macos",
    ),
    # elagente: WordPress Houzez archive + per-listing detail HTML
    # parse. ~55 active listings = ~60 HTTP requests per nightly. Keep
    # rps polite (0.5) so we don't trip the host's WAF.
    #
    # Transport switched to curl_cffi 2026-05-29: PR #458's browser-
    # realistic headers shipped on httpx and the source stayed red
    # (HTTP 403 from GitHub Actions runner IPs). On retest the block
    # was reproducible from any environment with httpx's Python TLS
    # handshake and bypassable with curl_cffi's Chrome-impersonated
    # handshake — i.e. the WAF is fingerprinting JA3, not the IP. Same
    # transport switch applied to realtyelsalvador + nexo below.
    # auto_repair stays False: if the JA3-impersonation also stops
    # working in future, an LLM still can't talk its way past a WAF.
    "elagente":         Policy(
        transport="curl_cffi",
        rate_limit_rps=0.5,
        user_agent_pool="safari_macos",
        auto_repair=False,
    ),

    # --- encuent24: Playwright source, polite by default. Phase 3 will
    # widen its category set ~6x; the polite layer keeps that respectful.
    "encuentra24": Policy(
        transport="playwright",
        rate_limit_rps=0.5,
        jitter_ms=(400, 1200),
        user_agent_pool="safari_macos",
    ),

    # realtyelsalvador: previous diagnosis was "IP-based Cloudflare WAF
    # block." Retest on 2026-05-29 showed the block reproduces from a
    # residential IP with httpx (Python TLS handshake) AND clears with
    # curl_cffi's Chrome JA3 impersonation from the same IP — so the
    # WAF is gating on TLS fingerprint, not IP. Transport switched to
    # curl_cffi. user_agent_pool stays "default" since the previous
    # working diet of mixed UAs survived once the handshake matched.
    # auto_repair stays False: same reason as elagente above.
    "realtyelsalvador": Policy(
        transport="curl_cffi",
        rate_limit_rps=0.5,
        auto_repair=False,
    ),

    # agentiz: SV agency site with 5 hardcoded detail-page URLs (no
    # catalog grid). The pages return 200 + JSON-LD from a residential
    # Mac IP but the GitHub Actions runner gets empty bodies — same
    # symptom class as elagente/realtyelsalvador prior to their
    # curl_cffi switch (TLS-fingerprint gate, not IP-only). Failure id
    # 6e981b52 (2026-06-06 nightly empty_yield) was the trigger.
    # Transport switched to curl_cffi with default chrome124 + the
    # safari_macos UA pool so the UA the WAF logs alongside the JA3
    # matches the typical regional visitor profile. Rate limit and
    # jitter stay at scraper defaults — only 5 requests per run.
    # auto_repair stays False: LLMs can't talk past a WAF.
    "agentiz":          Policy(
        transport="curl_cffi",
        rate_limit_rps=0.5,
        user_agent_pool="safari_macos",
        auto_repair=False,
    ),

    # jamesedition: luxury portal sitting behind Cloudflare's
    # JS-challenge interstitial. 2026-06-05 live probe with httpx
    # returned HTTP 403 + "Just a moment..." HTML. curl_cffi with
    # chrome124 impersonation clears the challenge. Rate-limit kept
    # conservative (0.3 rps + 500-1500ms jitter) because luxury
    # portals tend to escalate fast on flooding. auto_repair False:
    # WAF state isn't fixable by an LLM.
    "jamesedition": Policy(
        transport="curl_cffi",
        rate_limit_rps=0.3,
        jitter_ms=(500, 1500),
        user_agent_pool="safari_macos",
        # Match TLS fingerprint to the UA: chrome124 (the default)
        # against a Safari UA tripped the Cloudflare challenge.
        # safari17_0 keeps the handshake + UA aligned.
        curl_cffi_impersonate="safari17_0",
        auto_repair=False,
    ),
}


def get_policy(source: str) -> Policy:
    """Return the policy for ``source``, or ``DEFAULT_POLICY`` if unknown."""
    return POLICIES.get(source, DEFAULT_POLICY)


def with_override(source: str, **overrides) -> Policy:
    """Tests only — return a per-call modified copy without mutating POLICIES."""
    return replace(get_policy(source), **overrides)
