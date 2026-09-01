"""Contract: every caller of a Cloudflare-fronted provider API sets a User-Agent.

Cloudflare fronts `api.clerk.com` and `api.resend.com` and rejects the
default `Python-urllib/3.x` User-Agent with error 1010 ("banned based on
your browser's signature") *before* auth is evaluated. Measured
2026-08-09 against both providers with an invalid bearer token, so the
User-Agent was the only variable:

    Python-urllib/3.12                     -> clerk 403/1010  resend 403/1010
    curl/8.4.0                             -> clerk 401       resend 400
    pulpo-monitor/1.0 (+https://pulpo.club) -> clerk 401       resend 400

Any non-default UA clears the edge and the request is then judged on its
credentials, which is what we want.

Why this test exists rather than just the fix: PR #642 diagnosed these
1010s as the *GitHub-Actions runner* being blocked and migrated the
checks to the Vercel runtime. The migration carried the same urllib
default UA, so it kept getting 1010 — it changed the wrong variable. The
failure then stayed invisible for ~74 days because PULPO_CRON_SECRET was
never provisioned, so the endpoint was never called successfully and
nobody saw the 1010 it was still returning.

A UA is a one-line thing to forget in a new monitor, and forgetting it
fails in a way that looks like a provider outage. So it is enforced at
the wire, in the same grep-based producer-contract style as
tests/api/email_type_contract.test.js.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

# Providers observed to 1010 on the default urllib UA. Add a host here
# when a new Cloudflare-fronted provider is called from Python.
CLOUDFLARE_FRONTED = re.compile(r"api\.(?:clerk|resend)\.com")

SEARCH_ROOTS = ("api", "scripts", "automation")


def _python_files():
    for root in SEARCH_ROOTS:
        yield from (REPO / root).rglob("*.py")


def _provider_callers() -> list[Path]:
    """Files that both build a urllib Request and name a fronted provider."""
    out = []
    for path in _python_files():
        text = path.read_text(errors="replace")
        if "urllib.request.Request" not in text:
            continue
        if not CLOUDFLARE_FRONTED.search(text):
            continue
        out.append(path)
    return sorted(out)


def test_provider_callers_are_discoverable():
    """Guard the guard: if this hits zero the contract silently passes."""
    callers = _provider_callers()
    assert callers, (
        "no provider-calling files found — the detection heuristic broke, "
        "so this contract would pass vacuously"
    )


@pytest.mark.parametrize(
    "path", _provider_callers(), ids=lambda p: str(p.relative_to(REPO))
)
def test_provider_caller_sets_user_agent(path: Path):
    rel = path.relative_to(REPO)
    text = path.read_text(errors="replace")
    assert "User-Agent" in text, (
        f"{rel} calls a Cloudflare-fronted provider API (api.clerk.com / "
        f"api.resend.com) via urllib but never sets a User-Agent. The "
        f"default 'Python-urllib/3.x' is rejected at the Cloudflare edge "
        f"with error 1010 before auth runs, which surfaces as a fake "
        f"'provider unavailable'. Set a plain descriptive UA such as "
        f"'pulpo-monitor/1.0 (+https://pulpo.club)' — do NOT impersonate "
        f"a browser."
    )


@pytest.mark.parametrize(
    "path", _provider_callers(), ids=lambda p: str(p.relative_to(REPO))
)
def test_user_agent_is_not_browser_impersonation(path: Path):
    """A descriptive UA is enough; pretending to be Chrome is not okay.

    It misrepresents us to the provider and is fragile — the moment they
    tighten fingerprinting on a real browser signature we would be
    indistinguishable from the traffic they are trying to block.
    """
    rel = path.relative_to(REPO)
    text = path.read_text(errors="replace")
    for marker in ("Mozilla/5.0", "AppleWebKit", "Chrome/", "Safari/"):
        assert marker not in text, (
            f"{rel} appears to impersonate a browser User-Agent ({marker!r}). "
            f"A plain descriptive UA clears Cloudflare 1010 on its own — "
            f"verified against both providers. Use "
            f"'pulpo-monitor/1.0 (+https://pulpo.club)'."
        )
