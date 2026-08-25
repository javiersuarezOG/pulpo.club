#!/usr/bin/env python3
"""Active probe for the Telegram bot's webhook registration.

Why this exists alongside the `telegram` family in
check_webhook_health.py: that family is a *passive* heartbeat — it
notices that events stopped arriving. For a bot whose traffic is
organic and initially near zero, that signal is slow and noisy; a
7-day window is the only honest threshold, and "nobody messaged us"
is a growth fact rather than an outage.

This probe asks Telegram directly instead, so it catches the real
failure modes regardless of whether any user has written in:

  * the webhook was deregistered (someone ran deleteWebhook, or a
    second setWebhook elsewhere stole it)
  * the registered URL drifted away from production
  * Telegram is failing to deliver (last_error_message is set, which
    is how a rotated secret or a 5xx-ing handler shows up)
  * deliveries are piling up unacknowledged (pending_update_count)

Exit code is always 0 unless --strict. Per CLAUDE.md's never-silent-
freeze rule this alerts, it does not block: a red probe should page a
human, not fail a workflow that other checks share.

Usage:
    python3 scripts/check_telegram_webhook.py
    python3 scripts/check_telegram_webhook.py --strict   # self-test only
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

TIMEOUT_S = 15
# Enough that a brief spike is not an alert; small enough that a wedged
# handler is caught within a couple of health runs.
PENDING_ALERT_THRESHOLD = 50


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def get_webhook_info(token: str):
    url = f"https://api.telegram.org/bot{token}/getWebhookInfo"
    req = urllib.request.Request(url, headers={"accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8"))


def slack(text: str) -> None:
    hook = env("SLACK_WEBHOOK_URL")
    if not hook:
        print("SLACK_WEBHOOK_URL unset; skipping Slack ping.")
        return
    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        hook, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            resp.read()
    except Exception as exc:  # noqa: BLE001 - alerting must never raise
        print(f"Slack ping failed: {exc.__class__.__name__}")


def evaluate(info: dict, expected_url: str) -> list:
    """Return a list of human-readable problems. Pure, so it is testable."""
    problems = []
    result = (info or {}).get("result") or {}
    url = (result.get("url") or "").strip()

    if not url:
        problems.append(
            "No webhook URL is registered — the bot is receiving nothing. "
            "Re-run setWebhook (see docs/telegram-bot.md)."
        )
    elif expected_url and url != expected_url:
        problems.append(
            f"Registered webhook URL is `{url}` but production expects "
            f"`{expected_url}`. A stale registration means updates are going "
            f"somewhere else."
        )

    last_error = result.get("last_error_message")
    if last_error:
        problems.append(
            f"Telegram reports a delivery error: `{last_error}` "
            f"(at {result.get('last_error_date')}). A rotated secret or a "
            f"failing handler looks like this."
        )

    pending = result.get("pending_update_count") or 0
    if pending > PENDING_ALERT_THRESHOLD:
        problems.append(
            f"{pending} updates are queued and unacknowledged — the handler "
            f"is likely erroring or timing out."
        )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on problems. For the guardrail's own self-test; "
             "never for the scheduled run, which must not block other checks.",
    )
    args = parser.parse_args()

    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        # Not an error: the bot is simply not configured in this
        # environment. Same shape as the repo's other *_not_configured
        # paths — silence about a feature that does not exist.
        print("[telegram_probe] TELEGRAM_BOT_TOKEN unset; skipping.")
        return 0

    expected_url = env("TELEGRAM_WEBHOOK_URL")

    try:
        info = get_webhook_info(token)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        msg = f"could not reach Telegram getWebhookInfo: {exc.__class__.__name__}"
        print(f"[telegram_probe] {msg}")
        slack(f":warning: Telegram webhook probe — {msg}")
        return 1 if args.strict else 0

    if not info.get("ok"):
        msg = f"getWebhookInfo returned ok=false: {info.get('description')}"
        print(f"[telegram_probe] {msg}")
        slack(f":rotating_light: Telegram webhook probe — {msg}")
        return 1 if args.strict else 0

    problems = evaluate(info, expected_url)
    result = info.get("result") or {}

    if problems:
        detail = "\n".join(f"• {p}" for p in problems)
        print(f"[telegram_probe] PROBLEMS\n{detail}")
        slack(f":rotating_light: *Telegram bot webhook*\n{detail}")
        return 1 if args.strict else 0

    print(
        "[telegram_probe] ok "
        f"url={result.get('url')} pending={result.get('pending_update_count', 0)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
