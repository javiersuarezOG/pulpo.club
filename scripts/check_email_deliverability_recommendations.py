#!/usr/bin/env python3
"""Weekly Resend deliverability recommendation check.

Resend's dashboard can surface additional UI-only guidance, but this
script catches the API-visible failures that matter most for Pulpo:
unverified domains, unverified DNS records, and risky sender overrides.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def request_json(method: str, url: str, headers: dict[str, str] | None = None, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={**(headers or {}), **({"Content-Type": "application/json"} if payload is not None else {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed: {exc.code} {detail}") from exc


def slack(text: str) -> None:
    url = env("SLACK_WEBHOOK_URL")
    if not url:
        print(text)
        return
    request_json("POST", url, {}, {"text": text})


def domain_issues(domain: dict) -> list[str]:
    name = domain.get("name") or domain.get("domain") or domain.get("id") or "unknown-domain"
    issues: list[str] = []
    status = str(domain.get("status") or "").lower()
    if status and status not in {"verified", "success"}:
        issues.append(f"{name}: domain status is {status}")
    records = domain.get("records") or domain.get("dns_records") or []
    for record in records:
      record_status = str(record.get("status") or "").lower()
      record_type = record.get("record") or record.get("type") or "record"
      if record_status and record_status not in {"verified", "success"}:
          issues.append(f"{name}: DNS {record_type} status is {record_status}")
    return issues


def main() -> int:
    api_key = env("RESEND_API_KEY")
    if not api_key:
        raise SystemExit("RESEND_API_KEY is required")

    headers = {"Authorization": f"Bearer {api_key}"}
    data = request_json("GET", "https://api.resend.com/domains", headers)
    domains = data.get("data") if isinstance(data, dict) else data
    if not isinstance(domains, list):
        domains = []

    issues: list[str] = []
    for domain in domains:
        if isinstance(domain, dict):
            issues.extend(domain_issues(domain))

    sender = env("PULPO_ACTIVATION_FROM_EMAIL")
    if sender and "noreply@" in sender.lower():
        issues.append("PULPO_ACTIVATION_FROM_EMAIL uses noreply@; prefer hello@ for activation mail")
    if env("RESEND_FROM_NOREPLY").lower() in {"1", "true", "yes"}:
        issues.append("RESEND_FROM_NOREPLY is enabled")

    if issues:
        slack(":warning: Resend deliverability recommendations need attention:\n" + "\n".join(f"- {i}" for i in issues))
        return 1

    print("Resend deliverability check clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
