#!/usr/bin/env python3
"""Live probe of the public API. The alarm that would have caught the incident.

Build-time guardrails cannot see this failure class. On 2026-08-25 every
/api/v1 and /api/mcp endpoint returned 500 FUNCTION_INVOCATION_FAILED
while CI was fully green, because the fault existed only in Vercel's
emitted function bundle — not in any source a test could import. It was
found by a human opening the site days later.

So this hits the real endpoints on the real deployment and checks the
response is not merely 200 but SHAPED right: an endpoint that returns
an empty catalog is as broken as one that 500s, and only one of those
shows up as an error.

Exit code is always 0 unless --strict. Per CLAUDE.md's never-silent-
freeze rule this alerts rather than blocks: a red probe should page a
human, not fail a workflow other checks share.

Usage:
    python3 scripts/check_api_health.py
    python3 scripts/check_api_health.py --base https://<preview> --strict
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT_S = 30
DEFAULT_BASE = "https://pulpo.club"

# A floor, not an exact count — inventory moves nightly. Set well below
# the real catalog so it fires on "the data vanished", not on drift.
MIN_LISTINGS = 200
MIN_ZONES = 20


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def get(url: str, headers=None):
    req = urllib.request.Request(url, headers=headers or {"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def check(base: str, headers) -> list:
    """Return a list of human-readable problems. Pure enough to test."""
    problems = []

    # 1. liveness — the canary for the whole function bundle
    try:
        status, body = get(f"{base}/api/v1/ping", headers)
        if status != 200 or not body.get("ok"):
            problems.append(f"/api/v1/ping returned {status} {body}")
    except Exception as exc:  # noqa: BLE001
        problems.append(
            f"/api/v1/ping unreachable ({exc.__class__.__name__}). A 500 here means the "
            f"function bundle is broken — check the api/ boundary rule in docs/api-v1.md."
        )
        return problems  # nothing else will work either

    # 2. vocabulary — proves the catalog deployed AND parsed
    try:
        status, meta = get(f"{base}/api/v1/meta", headers)
        if status != 200:
            problems.append(f"/api/v1/meta returned {status}")
        else:
            if (meta.get("total") or 0) < MIN_LISTINGS:
                problems.append(
                    f"/api/v1/meta reports only {meta.get('total')} listings "
                    f"(floor {MIN_LISTINGS}) — the catalog may not have deployed."
                )
            if len(meta.get("zones") or []) < MIN_ZONES:
                problems.append(f"/api/v1/meta has {len(meta.get('zones') or [])} zones (floor {MIN_ZONES}).")
            if not meta.get("generated_at"):
                problems.append("/api/v1/meta has no generated_at — freshness is unverifiable.")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"/api/v1/meta failed: {exc.__class__.__name__}")

    # 3. the actual capability — results, correctly shaped
    try:
        status, page = get(f"{base}/api/v1/listings?limit=3&sub=land", headers)
        if status != 200:
            problems.append(f"/api/v1/listings returned {status}")
        else:
            rows = page.get("data") or []
            if not rows:
                problems.append("/api/v1/listings returned zero results for a broad query.")
            for r in rows:
                if "__" not in (r.get("id") or ""):
                    problems.append(f"listing id is not canonical: {r.get('id')!r}")
                    break
                if not str(r.get("url") or "").startswith("http"):
                    problems.append(f"listing url is not absolute: {r.get('url')!r}")
                    break
                # the PII boundary, checked on the live wire
                leaked = [k for k in ("broker_name", "broker_phone", "broker_email") if k in r]
                if leaked:
                    problems.append(f"PII LEAK: {', '.join(leaked)} present in a public response")
                    break
            # detail must resolve for an id the list just handed out
            if rows:
                lid = urllib.parse.quote(rows[0]["id"], safe="")
                dstatus, detail = get(f"{base}/api/v1/listings/{lid}", headers)
                if dstatus != 200 or not (detail.get("data") or {}).get("id"):
                    problems.append(f"/api/v1/listings/:id returned {dstatus} for an id from the list")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"/api/v1/listings failed: {exc.__class__.__name__}")

    # 4. MCP — a POST that must not 500
    try:
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        req = urllib.request.Request(
            f"{base}/api/mcp", data=body,
            headers={"content-type": "application/json", "accept": "application/json, text/event-stream"},
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            if resp.status >= 500:
                problems.append(f"/api/mcp returned {resp.status}")
    except urllib.error.HTTPError as exc:
        if exc.code >= 500:
            problems.append(f"/api/mcp returned {exc.code} — the MCP server is down.")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"/api/mcp failed: {exc.__class__.__name__}")

    return problems


def slack(text: str) -> None:
    hook = env("SLACK_WEBHOOK_URL")
    if not hook:
        print("SLACK_WEBHOOK_URL unset; skipping Slack ping.")
        return
    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(hook, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001 - alerting must never raise
        print(f"Slack ping failed: {exc.__class__.__name__}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", default=env("PULPO_API_BASE", DEFAULT_BASE))
    ap.add_argument("--strict", action="store_true",
                    help="Exit non-zero on problems. For self-tests and preview gating; "
                         "never for the scheduled run, which must not block sibling checks.")
    args = ap.parse_args()

    headers = {"accept": "application/json"}
    bypass = env("VERCEL_AUTOMATION_BYPASS_SECRET")
    if bypass:
        headers["x-vercel-protection-bypass"] = bypass

    problems = check(args.base.rstrip("/"), headers)

    if problems:
        detail = "\n".join(f"• {p}" for p in problems)
        print(f"[api_health] PROBLEMS at {args.base}\n{detail}")
        slack(f":rotating_light: *Pulpo API health* ({args.base})\n{detail}")
        return 1 if args.strict else 0

    print(f"[api_health] ok — {args.base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
