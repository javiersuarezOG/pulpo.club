#!/usr/bin/env python3
"""HeroV5 home-conversion readout (PRD P1-7, plan PR-4B).

HeroV5 became the default home (#623, ramp around 2026-05-25). PRD asks
Data Science to compare home conversion before/after to decide whether
to restore a Pro CTA. This script runs that comparison reproducibly so
the markdown decision doc in docs/decisions/herov5-conversion-readout.md
stays grounded in real PostHog data.

Funnel:
  paid_home_rendered → cta_routed → free_month_modal.shown
  → upgrade.checkout_started → stripe.checkout_completed

Decision rule (from PRD + plan):
  - down >10% post-ramp AND p<0.05 (two-proportion z-test) → restore CTA
  - within +/-10% → keep discovery-led home
  - low traffic in either window (<100 events) → "inconclusive — extend
    window"

Env:
  POSTHOG_HOST                  default "https://eu.i.posthog.com"
  POSTHOG_PROJECT_ID            required
  POSTHOG_PERSONAL_API_KEY      required
  HEROV5_RAMP_DATE              default "2026-05-25" (override per #623)
  WINDOW_DAYS                   default 7

Usage:
  POSTHOG_PROJECT_ID=... POSTHOG_PERSONAL_API_KEY=... \
    python3 scripts/posthog_herov5_conversion.py
  # → prints markdown table + recommendation. Append to
  #    docs/decisions/herov5-conversion-readout.md.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import urllib.error
import urllib.request


# Funnel events the comparison cares about. Lifted from
# web/app/telemetry/events.ts — keep in sync if registry renames a step.
FUNNEL_EVENTS: tuple[str, ...] = (
    "paid_home_rendered",
    "cta_routed",
    "free_month_modal.shown",
    "upgrade.checkout_started",
    "stripe.checkout_completed",
)


def env(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed: {exc.code} {detail}") from exc


def count_events(host: str, project: str, key: str, event: str,
                 start: dt.datetime, end: dt.datetime) -> int:
    hogql = (
        f"SELECT count() AS n FROM events "
        f"WHERE event = '{event}' "
        f"AND timestamp >= toDateTime('{start.isoformat()}') "
        f"AND timestamp < toDateTime('{end.isoformat()}')"
    )
    data = post_json(
        f"{host.rstrip('/')}/api/projects/{project}/query/",
        {"Authorization": f"Bearer {key}"},
        {"query": {"kind": "HogQLQuery", "query": hogql}},
    )
    rows = data.get("results") or []
    if not rows or not rows[0] or rows[0][0] is None:
        return 0
    try:
        return int(rows[0][0])
    except (TypeError, ValueError):
        return 0


def two_proportion_z(p1_succ: int, p1_total: int,
                     p2_succ: int, p2_total: int) -> tuple[float, float] | None:
    """Two-proportion z-test for conversion-rate difference.

    Returns (z_score, p_value) or None when either window has zero
    trials (test undefined). Two-sided p-value via the normal
    approximation — fine at the event counts we expect (hundreds+).
    """
    if p1_total == 0 or p2_total == 0:
        return None
    p1 = p1_succ / p1_total
    p2 = p2_succ / p2_total
    p_pool = (p1_succ + p2_succ) / (p1_total + p2_total)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / p1_total + 1 / p2_total))
    if se == 0:
        return None
    z = (p2 - p1) / se
    # Two-sided p-value, normal approximation.
    p_val = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return (z, p_val)


def fetch_window(host: str, project: str, key: str,
                 start: dt.datetime, end: dt.datetime) -> dict[str, int]:
    return {event: count_events(host, project, key, event, start, end)
            for event in FUNNEL_EVENTS}


def render_markdown(pre: dict[str, int], post: dict[str, int],
                    pre_window: tuple[dt.datetime, dt.datetime],
                    post_window: tuple[dt.datetime, dt.datetime]) -> str:
    out: list[str] = []
    out.append("| Step | Pre-HeroV5 | Post-HeroV5 | Δ |")
    out.append("|---|---:|---:|---:|")
    for event in FUNNEL_EVENTS:
        pre_n = pre.get(event, 0)
        post_n = post.get(event, 0)
        if pre_n > 0:
            delta_pct = (post_n - pre_n) / pre_n * 100
            delta = f"{delta_pct:+.1f}%"
        else:
            delta = "—"
        out.append(f"| `{event}` | {pre_n} | {post_n} | {delta} |")

    # End-to-end conversion rate: stripe.checkout_completed / paid_home_rendered
    pre_top = pre.get("paid_home_rendered", 0)
    pre_bot = pre.get("stripe.checkout_completed", 0)
    post_top = post.get("paid_home_rendered", 0)
    post_bot = post.get("stripe.checkout_completed", 0)
    pre_rate = (pre_bot / pre_top * 100) if pre_top else None
    post_rate = (post_bot / post_top * 100) if post_top else None
    out.append("")
    out.append(f"**Pre-HeroV5 window**: {pre_window[0].date()} → {pre_window[1].date()}")
    out.append(f"**Post-HeroV5 window**: {post_window[0].date()} → {post_window[1].date()}")
    out.append("")
    if pre_rate is None or post_rate is None:
        out.append("**End-to-end conversion**: insufficient data (paid_home_rendered=0 in one window)")
        out.append("")
        out.append("## Recommendation: inconclusive — extend window")
        return "\n".join(out)
    delta_rate = post_rate - pre_rate
    out.append("**End-to-end conversion** (paid_home_rendered → stripe.checkout_completed):")
    out.append(f"- Pre: {pre_rate:.2f}% ({pre_bot}/{pre_top})")
    out.append(f"- Post: {post_rate:.2f}% ({post_bot}/{post_top})")
    out.append(f"- Δ: {delta_rate:+.2f} pp ({(delta_rate / pre_rate * 100) if pre_rate else 0:+.1f}% relative)")
    out.append("")
    z_result = two_proportion_z(pre_bot, pre_top, post_bot, post_top)
    if z_result is None:
        out.append("**Significance test**: undefined (zero trials).")
        decision = "inconclusive — extend window"
    else:
        z, p_val = z_result
        out.append(f"**Significance test**: z={z:.2f}, p={p_val:.4f}")
        if pre_top < 100 or post_top < 100:
            decision = "inconclusive — low traffic (<100 events in one window); extend window"
        elif pre_rate == 0:
            decision = "inconclusive — pre-window conversion is zero"
        else:
            relative_drop = (pre_rate - post_rate) / pre_rate
            significant = p_val < 0.05
            if significant and relative_drop > 0.10:
                decision = "restore Pro CTA — conversion down >10% relative AND p<0.05"
            elif abs(relative_drop) <= 0.10:
                decision = "keep discovery-led home — conversion within ±10%"
            else:
                decision = "monitor — large delta but not statistically significant; extend window"
    out.append("")
    out.append(f"## Recommendation: {decision}")
    return "\n".join(out)


def main() -> int:
    host = env("POSTHOG_HOST", "https://eu.i.posthog.com")
    project = env("POSTHOG_PROJECT_ID")
    key = env("POSTHOG_PERSONAL_API_KEY")
    if not project or not key:
        print("POSTHOG_PROJECT_ID and POSTHOG_PERSONAL_API_KEY are required", file=sys.stderr)
        return 1

    ramp_iso = env("HEROV5_RAMP_DATE", "2026-05-25")
    window_days = int(env("WINDOW_DAYS", "7"))
    ramp = dt.datetime.fromisoformat(ramp_iso).replace(tzinfo=dt.timezone.utc)
    pre = (ramp - dt.timedelta(days=window_days), ramp)
    post = (ramp, ramp + dt.timedelta(days=window_days))

    print(f"# HeroV5 conversion readout — generated {dt.datetime.now(dt.timezone.utc).isoformat()}")
    print(f"Ramp date: {ramp.date()}; window: {window_days} days each side\n")

    pre_counts = fetch_window(host, project, key, *pre)
    post_counts = fetch_window(host, project, key, *post)
    print(render_markdown(pre_counts, post_counts, pre, post))
    return 0


if __name__ == "__main__":
    sys.exit(main())
