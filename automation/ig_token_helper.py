"""ig_token_helper.py — one-shot CLI to mint the IG publisher's secrets.

Two outputs needed for PR-4's publisher + cron workflow:

  IG_ACCESS_TOKEN  long-lived (60d) user token from Meta Graph API
  IG_USER_ID       numeric ID of @pulpo.club's Business Account

Manually doing this via Graph API Explorer is ~10 clicks + paste +
clicks-again-because-the-exchange-step-is-hidden.  This script does the
ceremony in one command:

  1. Trades a short-lived user token for the 60d long-lived one
  2. Lists the operator's pages, picks the Pulpo page (or prompts if
     multiple match)
  3. Reads the page's `instagram_business_account.id` field
  4. Prints both values in a copy-paste-ready block:

        export IG_ACCESS_TOKEN='...'
        export IG_USER_ID='17841...'

  5. Prints the gh-cli commands to set them as GH Actions secrets, and
     reminds the operator to mirror to Vercel env if any non-cron path
     ever ends up calling the IG API.

Inputs (env vars; CLI flags override):

  META_APP_ID         App ID from developers.facebook.com/apps
  META_APP_SECRET     App secret (same place)
  IG_SHORT_TOKEN      Short-lived user token from
                      developers.facebook.com/tools/explorer
                      (with permissions: instagram_basic,
                      instagram_content_publish, instagram_manage_comments,
                      pages_show_list, pages_read_engagement)
                      NOTE: instagram_manage_comments is REQUIRED for the
                      publisher's first-comment step (the full listing spec
                      + hashtags). Without it the post still publishes but
                      the first comment is skipped.
  IG_PAGE_HINT        (optional) Substring of the Pulpo page name to
                      auto-select when the user has multiple pages.

CLI:

  python3 -m automation.ig_token_helper \\
      [--app-id ...] [--app-secret ...] [--short-token ...] \\
      [--page-hint pulpo] [--json]

`--json` prints the result as a JSON object (for piping into other
tools).  Default is human-readable + copy-paste-ready.

Why not bake this into the publisher itself: the token-mint flow runs
ONCE every 60 days (or on credential rotation), the publisher runs
hourly.  Keeping the credential-mint code out of the hot path means
the publisher never accidentally re-mints a token and never needs the
APP_SECRET (which would be wider blast-radius than ACCESS_TOKEN if
leaked).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


GRAPH_BASE = "https://graph.facebook.com/v21.0"


# ── HTTP helpers (stdlib only — keeps the helper installable even on
# a freshly cloned repo without `pip install httpx`) ──────────────────

def _http_get(url: str) -> dict:
    """Plain GET → JSON dict.  Raises on non-2xx."""
    req = Request(url, headers={"User-Agent": "pulpo-ig-token-helper/1"})
    with urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"non-JSON response from {url}: {body[:200]}") from e


# ── Step 1: short-lived → long-lived exchange ────────────────────────

def exchange_for_long_lived_token(
    short_token: str, app_id: str, app_secret: str
) -> dict:
    """Returns the parsed Graph response.  On success: {"access_token":
    "...", "token_type": "bearer", "expires_in": 5183944}."""
    url = f"{GRAPH_BASE}/oauth/access_token?" + urlencode({
        "grant_type":         "fb_exchange_token",
        "client_id":          app_id,
        "client_secret":      app_secret,
        "fb_exchange_token":  short_token,
    })
    return _http_get(url)


# ── Step 2: pick the Pulpo Facebook Page ─────────────────────────────

def list_pages(long_lived_token: str) -> list[dict]:
    """Return all pages the operator manages."""
    url = f"{GRAPH_BASE}/me/accounts?" + urlencode({
        "access_token": long_lived_token,
        "fields":       "id,name,instagram_business_account",
        "limit":        100,
    })
    resp = _http_get(url)
    return resp.get("data", []) or []


def pick_pulpo_page(pages: list[dict], hint: Optional[str]) -> dict:
    """Choose the page that maps to @pulpo.club.  Resolution order:
       1. If only one page, use it.
       2. If hint is provided, match by case-insensitive substring on
          the page name.
       3. Otherwise raise — operator must pass --page-hint.
    """
    if not pages:
        raise RuntimeError(
            "no Facebook pages found.  The short-lived token may be "
            "missing the pages_show_list permission, or the operator's "
            "account doesn't manage any pages."
        )
    # Short-circuit ONLY when there's exactly one page AND no explicit
    # hint — a hint should still be honoured (a single page that doesn't
    # match the hint suggests a wrong account, not "auto-pick it").
    if len(pages) == 1 and not hint:
        return pages[0]
    if hint:
        needle = hint.strip().lower()
        candidates = [p for p in pages if needle in (p.get("name") or "").lower()]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            names = ", ".join(repr(p.get("name")) for p in candidates)
            raise RuntimeError(
                f"multiple pages match hint {hint!r}: {names} — "
                "tighten --page-hint or pick manually."
            )
        names = ", ".join(repr(p.get("name")) for p in pages)
        raise RuntimeError(
            f"no page name contains {hint!r}.  Available: {names}"
        )
    names = ", ".join(repr(p.get("name")) for p in pages)
    raise RuntimeError(
        f"{len(pages)} pages found, pass --page-hint to disambiguate. "
        f"Available: {names}"
    )


# ── Step 3: extract IG Business Account ID ───────────────────────────

def ig_user_id_from_page(page: dict, long_lived_token: str) -> str:
    """Return the IG Business Account ID linked to `page`.

    /me/accounts already returns `instagram_business_account.id` when
    the page is IG-linked.  We re-query the page directly as a
    fallback in case the field wasn't expanded by the list call."""
    ig = page.get("instagram_business_account") or {}
    if isinstance(ig, dict) and ig.get("id"):
        return str(ig["id"])
    page_id = page.get("id")
    if not page_id:
        raise RuntimeError("page record has no id")
    url = f"{GRAPH_BASE}/{page_id}?" + urlencode({
        "access_token": long_lived_token,
        "fields":       "instagram_business_account",
    })
    resp = _http_get(url)
    ig = resp.get("instagram_business_account") or {}
    if not ig.get("id"):
        raise RuntimeError(
            f"page {page.get('name')!r} (id={page_id}) is not linked "
            "to an Instagram Business Account.  Link via "
            "Meta Business Suite → Settings → Accounts → Instagram."
        )
    return str(ig["id"])


# ── orchestration ────────────────────────────────────────────────────

def mint(
    short_token: str,
    app_id: str,
    app_secret: str,
    *,
    page_hint: Optional[str] = None,
) -> dict[str, Any]:
    exchange = exchange_for_long_lived_token(short_token, app_id, app_secret)
    long_lived = exchange.get("access_token")
    if not long_lived:
        raise RuntimeError(
            f"long-lived exchange failed: {exchange!r}"
        )
    expires_in = exchange.get("expires_in")
    pages = list_pages(long_lived)
    page = pick_pulpo_page(pages, page_hint)
    ig_id = ig_user_id_from_page(page, long_lived)
    return {
        "IG_ACCESS_TOKEN":  long_lived,
        "IG_USER_ID":       ig_id,
        "expires_in_s":     expires_in,
        "expires_in_days":  round(expires_in / 86400, 1) if expires_in else None,
        "page_id":          page.get("id"),
        "page_name":        page.get("name"),
    }


# ── CLI ──────────────────────────────────────────────────────────────

def _print_human(result: dict) -> None:
    print()
    print("=" * 64)
    print("Pulpo IG publisher — secrets minted")
    print("=" * 64)
    print()
    print(f"  Page:          {result['page_name']!r} (id={result['page_id']})")
    if result.get("expires_in_days"):
        print(f"  Token expiry:  ~{result['expires_in_days']} days")
    print()
    print("─" * 64)
    print("Copy-paste-ready (shell):")
    print("─" * 64)
    print()
    print(f"export IG_ACCESS_TOKEN={result['IG_ACCESS_TOKEN']!r}")
    print(f"export IG_USER_ID={result['IG_USER_ID']!r}")
    print()
    print("─" * 64)
    print("Set as GitHub Actions secrets:")
    print("─" * 64)
    print()
    print(f"gh secret set IG_ACCESS_TOKEN --body {result['IG_ACCESS_TOKEN']!r}")
    print(f"gh secret set IG_USER_ID --body {result['IG_USER_ID']!r}")
    print("gh secret set IG_PAUSED --body ''   # empty = publishing enabled")
    print()
    print("=" * 64)
    print("Reminder: rotate every ~50 days (the long-lived token is 60d).")
    print("Re-run this helper with a fresh short-lived token to refresh.")
    print("=" * 64)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mint IG_ACCESS_TOKEN + IG_USER_ID for the publisher.",
    )
    parser.add_argument(
        "--app-id", default=os.environ.get("META_APP_ID"),
        help="Meta app ID (env: META_APP_ID)",
    )
    parser.add_argument(
        "--app-secret", default=os.environ.get("META_APP_SECRET"),
        help="Meta app secret (env: META_APP_SECRET)",
    )
    parser.add_argument(
        "--short-token", default=os.environ.get("IG_SHORT_TOKEN"),
        help="Short-lived user token from Graph API Explorer (env: IG_SHORT_TOKEN)",
    )
    parser.add_argument(
        "--page-hint", default=os.environ.get("IG_PAGE_HINT", "pulpo"),
        help=(
            "Substring of the Pulpo page name (env: IG_PAGE_HINT, default 'pulpo')."
            "  Used when the operator manages multiple Facebook pages."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print result as a JSON object instead of human-readable.",
    )
    args = parser.parse_args(argv)

    missing = [
        n for n, v in (
            ("--app-id / META_APP_ID",         args.app_id),
            ("--app-secret / META_APP_SECRET", args.app_secret),
            ("--short-token / IG_SHORT_TOKEN", args.short_token),
        ) if not v
    ]
    if missing:
        print(f"missing required input: {missing}", file=sys.stderr)
        return 2

    try:
        result = mint(
            args.short_token, args.app_id, args.app_secret,
            page_hint=args.page_hint,
        )
    except Exception as e:
        print(f"[ig_token_helper] mint failed: {e}", file=sys.stderr)
        return 1

    if args.json:
        # Strip nothing — JSON consumers can pick what they need.
        print(json.dumps(result, indent=2))
    else:
        _print_human(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
