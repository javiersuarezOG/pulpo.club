#!/usr/bin/env python3
"""End-to-end CSP alert verification: fires a synthetic csp.violation
event into PostHog so the upserted alert (see
scripts/posthog_setup_csp_alert.py) actually posts to Slack.

PRD P1-8 — Slack wiring becomes meaningful only when verified
end-to-end. Use this after running `posthog_setup_csp_alert.py` so
oncall sees a real Slack ping land instead of trusting the upsert
output alone.

Env vars:
  POSTHOG_PROJECT_TOKEN     — PostHog public ingest token (required).
  POSTHOG_INGEST_HOST       — defaults to https://eu.i.posthog.com.
  PULPO_CSP_TEST_LABEL      — optional override for the test label;
                              defaults to "csp-alert-test:<utc>".

Run: `python3 scripts/posthog_test_csp_alert.py`
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request


INGEST_DEFAULT = "https://eu.i.posthog.com"


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def main() -> int:
    parser = argparse.ArgumentParser(description="Fire one synthetic csp.violation event.")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the payload but don't POST. Useful for diff review.",
    )
    args = parser.parse_args()

    token = env("POSTHOG_PROJECT_TOKEN")
    if not token:
        print("POSTHOG_PROJECT_TOKEN is required", file=sys.stderr)
        return 1

    ingest = env("POSTHOG_INGEST_HOST", INGEST_DEFAULT)
    label = env(
        "PULPO_CSP_TEST_LABEL",
        f"csp-alert-test:{dt.datetime.now(dt.timezone.utc).isoformat()}",
    )

    payload = {
        "api_key": token,
        "event": "csp.violation",
        "distinct_id": "server:csp-alert-test",
        "properties": {
            "label": label,
            "synthetic": True,
            "directive": "script-src",
            "blocked_uri": "https://example-csp-test.invalid/blocked",
            "document_uri": "https://pulpo.club/csp-test",
            "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        },
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2))
        return 0

    url = f"{ingest.rstrip('/')}/capture/"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"OK {r.status} label={label}")
    except urllib.error.HTTPError as exc:
        print(f"PostHog ingest returned {exc.code}: {exc.read().decode('utf-8', errors='replace')[:200]}",
              file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"PostHog ingest unreachable: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
