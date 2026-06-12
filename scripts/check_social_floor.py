#!/usr/bin/env python3
"""Social-floor canary: alert when /api/social/listings' top-50 loses its
hires-eligible inventory.

What this guards
----------------
``web/tests/contracts/social-api.test.ts`` (the required PR ``contract``
check) asserts that the top-50 of ``/api/social/listings`` contains at
least one listing whose hires source clears the 4:5 canonical crop:
``hires_width >= 1080 AND hires_height >= 1350 AND hires_available is
not False``. pulpo-social's production pre-filter mirrors the same
logic — when the count hits 0, daily Instagram/Facebook publishing
finds 0 candidates AND every open PR fails the required check.

The 2026-06-12 incident
-----------------------
The nightly data commit (#861, generated with photo/ranking PRs
#851-#860 live) dropped the eligible-in-top-50 count from 1 (already
razor-thin) to 0 — the first eligible listing fell to index 116. The
contract test runs only against PR previews and SKIPS on main pushes,
so main looked green while every open PR failed. Nothing alerted;
discovery took a human noticing PR checks failing. This is the second
occurrence of the silent-0-candidates class (precedent: the
hero_photo_path / PULPO_PHOTO_BUDGET_S budget bug) — hence this
positive check on every nightly, per CLAUDE.md's "NEVER let a webhook
go silent" positive-heartbeat philosophy.

Why alert-only
--------------
This canary NEVER blocks the nightly's data commit. The 2026-05-26 →
2026-06-01 six-day data freeze (CLAUDE.md: "NEVER let the nightly
freeze data without a Slack page") was caused by a canary gating the
commit path; a stale site is worse than a quiet Instagram day. The
workflow step that runs this script carries ``continue-on-error: true``
— even a CRITICAL verdict only pages Slack and emits telemetry.

Coupling warning
----------------
``passes_quality_gate`` + ``sort_by_rank`` below MIRROR
``api/social/listings.js`` (``passesQualityGate`` + the rank_score-desc
sort). The eligibility criterion mirrors the contract test's
``findEligibleListingId``. If either changes, this script — and the
thresholds below — must change in the same PR.

Consumers
---------
- Slack channel behind ``SLACK_WEBHOOK_URL`` (CRITICAL page / WARN note).
- PostHog event ``social_floor.checked`` (all computed metrics +
  verdict; queryable for trend dashboards/alerts).

Usage
-----
::

    python3 scripts/check_social_floor.py [--json] [--dry-run] \\
        --data-dir web/data \\
        --run-url https://github.com/.../actions/runs/12345
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ── Eligibility criterion (mirrors web/tests/contracts/social-api.test.ts
#    findEligibleListingId — the 4:5 crop is the strictest canonical) ──
TARGET_W = 1080
TARGET_H = 1350
TOP_N = 50  # the contract test pages through limit=50

# ── Verdict thresholds ───────────────────────────────────────────────
# Lesson from 2026-06-12: the floor sat at exactly 1 eligible listing
# for an unknown stretch before #861 tipped it to 0 — a razor-thin
# margin nobody saw because nothing measured it. CRITICAL means the
# contract test + pulpo-social's daily publish are broken RIGHT NOW;
# WARN means one more photo-pipeline or ranking change away from
# CRITICAL. Revisit these if api/social/listings.js's gate or the
# contract test's criterion changes.
CRITICAL_MAX = 0   # eligible_in_top50 == 0 → CRITICAL (Slack page, exit 1)
WARN_MAX = 2       # 1..2 → WARN (Slack warning, exit 0); >= 3 → OK


# ── Replicated gate + sort ───────────────────────────────────────────
# MIRRORS api/social/listings.js::passesQualityGate + the default
# (sort=rank) branch. Both files must change together — a drift here
# makes the canary lie about what the API actually serves.

def passes_quality_gate(listing: dict[str, Any]) -> bool:
    """Python mirror of api/social/listings.js::passesQualityGate."""
    if not listing.get("hero_photo_path"):
        return False
    if listing.get("price_usd") is None:
        return False
    # data_quality_score is 0..1 and populated for ~all rows; 0.5 is the
    # production threshold (same as featured_listing.py's pool).
    dqs = listing.get("data_quality_score")
    if (0 if dqs is None else dqs) < 0.5:
        return False
    # Soft signals — only reject when explicitly flagged.
    if listing.get("has_text_overlay") is True:
        return False
    if listing.get("has_marketing_overlay") is True:
        return False
    hpqs = listing.get("hero_photo_quality_score")
    if hpqs is not None and hpqs < 50:
        return False
    return True


def sort_by_rank(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Python mirror of listings.js's default sort: keep rows whose
    rank_score is a number, sort rank_score descending (stable)."""
    numeric = [
        row for row in listings
        if isinstance(row.get("rank_score"), (int, float))
        and not isinstance(row.get("rank_score"), bool)
    ]
    return sorted(numeric, key=lambda row: row["rank_score"], reverse=True)


def is_contract_eligible(listing: dict[str, Any]) -> bool:
    """Mirror of the contract test's criterion: hires source big enough
    for the 4:5 crop and not explicitly unavailable.

    Matches the JS exactly: ``hires_width ?? 0``, ``hires_height ?? 0``,
    ``hires_available !== false`` (None/missing is tolerated)."""
    w = listing.get("hires_width")
    h = listing.get("hires_height")
    w = 0 if w is None else w
    h = 0 if h is None else h
    available = listing.get("hires_available") is not False
    return bool(available and w >= TARGET_W and h >= TARGET_H)


# ── Metrics + verdict (pure; tests pin behaviour) ────────────────────

def compute_metrics(data: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute the social-floor metrics dict from raw ranked.json rows."""
    gate_passers = [row for row in data if passes_quality_gate(row)]
    ranked = sort_by_rank(gate_passers)
    top = ranked[:TOP_N]

    eligible_in_top = sum(1 for row in top if is_contract_eligible(row))

    first_eligible_index: Optional[int] = None
    for i, row in enumerate(ranked):
        if is_contract_eligible(row):
            first_eligible_index = i
            break

    # hires_available distribution over the top-N surface — tells the
    # responder whether the floor broke via missing backfill (null),
    # explicit unavailability (false), or dimensions (true but small).
    dist = {"true": 0, "false": 0, "null": 0}
    for row in top:
        v = row.get("hires_available")
        if v is True:
            dist["true"] += 1
        elif v is False:
            dist["false"] += 1
        else:
            dist["null"] += 1

    return {
        "total_listings": len(data),
        "gate_passers": len(gate_passers),
        "ranked_with_score": len(ranked),
        "eligible_in_top50": eligible_in_top,
        "first_eligible_index": first_eligible_index,
        "hires_available_top50": dist,
        "target_w": TARGET_W,
        "target_h": TARGET_H,
    }


def verdict_for(eligible_in_top50: int) -> str:
    """Map the eligible count to CRITICAL / WARN / OK per the module
    thresholds."""
    if eligible_in_top50 <= CRITICAL_MAX:
        return "CRITICAL"
    if eligible_in_top50 <= WARN_MAX:
        return "WARN"
    return "OK"


def build_slack_message(metrics: dict[str, Any], verdict: str,
                        run_url: Optional[str]) -> str:
    """Pure: build the Slack body for a non-OK verdict."""
    n = metrics["eligible_in_top50"]
    first = metrics["first_eligible_index"]
    first_str = str(first) if first is not None else "none"
    dist = metrics["hires_available_top50"]
    if verdict == "CRITICAL":
        head = (
            ":rotating_light: *Social floor CRITICAL — 0 hires-eligible "
            "listings in /api/social/listings top-50.*\n"
            "Daily Instagram/Facebook publishing has 0 candidates and the "
            "required `contract` PR check fails on EVERY open PR."
        )
    else:
        head = (
            f":warning: *Social floor thin — only {n} hires-eligible "
            f"listing(s) in /api/social/listings top-50* (OK floor is "
            f"{WARN_MAX + 1}). One photo/ranking change from 0."
        )
    lines = [
        head,
        (
            f"• eligible_in_top50={n} first_eligible_index={first_str} "
            f"gate_passers={metrics['gate_passers']}"
        ),
        (
            f"• hires_available in top-50: true={dist['true']} "
            f"false={dist['false']} null={dist['null']}"
        ),
        (
            "• Criterion: hires_width≥1080 AND hires_height≥1350 AND "
            "hires_available≠false (mirrors social-api.test.ts)."
        ),
        "• Alert-only: the nightly data commit was NOT blocked.",
    ]
    if run_url:
        lines.append(f"<{run_url}|Open Actions run>")
    return "\n".join(lines)


# ── Side effects (Slack + PostHog) — best-effort, never raise ────────

def _post_slack(webhook_url: str, text: str) -> None:
    """Best-effort Slack POST. Errors print to stderr and do not raise."""
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except (urllib.error.URLError, TimeoutError) as e:
        # We never block the nightly on alerting.
        print(f"[social-floor] Slack POST failed: {e}", file=sys.stderr)


def capture_posthog(metrics: dict[str, Any], verdict: str) -> None:
    """Emit `social_floor.checked` via automation.posthog_client.capture
    (silent no-op without POSTHOG_PROJECT_TOKEN). Telemetry failure must
    never break the check — same posture as classify_nightly_outcome.py."""
    props = {**metrics, "verdict": verdict}
    # Flatten the nested distribution for easier HogQL querying.
    dist = props.pop("hires_available_top50", {}) or {}
    props["hires_available_true"] = dist.get("true")
    props["hires_available_false"] = dist.get("false")
    props["hires_available_null"] = dist.get("null")
    try:
        from automation.posthog_client import capture
        capture("social_floor.checked", props)
    except Exception as e:  # noqa: BLE001 — telemetry is best-effort
        print(f"[social-floor] posthog capture failed (non-fatal): {e!r}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Alert-only canary for the /api/social/listings hires floor."
    )
    parser.add_argument(
        "--data-dir", default="web/data",
        help="Directory containing ranked.json.",
    )
    parser.add_argument(
        "--run-url", default=None,
        help="GitHub Actions run URL embedded in the alert body.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print the metrics dict as JSON (machine-readable).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the alert body but do not POST to Slack.",
    )
    args = parser.parse_args(argv)

    ranked_path = Path(args.data_dir) / "ranked.json"
    try:
        with open(ranked_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as e:
        # A missing/corrupt ranked.json is its own incident class with its
        # own canaries; this check degrades loudly-but-cleanly.
        print(f"[social-floor] cannot read {ranked_path}: {e}", file=sys.stderr)
        return 1
    if not isinstance(data, list):
        print(f"[social-floor] {ranked_path} is not a list", file=sys.stderr)
        return 1

    metrics = compute_metrics(data)
    verdict = verdict_for(metrics["eligible_in_top50"])

    if args.json:
        print(json.dumps({**metrics, "verdict": verdict}, indent=2))
    else:
        first = metrics["first_eligible_index"]
        print(
            f"[social-floor] {verdict}: eligible_in_top50="
            f"{metrics['eligible_in_top50']} "
            f"first_eligible_index={first if first is not None else 'none'} "
            f"gate_passers={metrics['gate_passers']} "
            f"hires_available_top50={metrics['hires_available_top50']}"
        )

    capture_posthog(metrics, verdict)

    if verdict != "OK":
        text = build_slack_message(metrics, verdict, args.run_url)
        if args.dry_run:
            print(text)
            print("[social-floor] --dry-run: not posting.")
        else:
            webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
            if not webhook_url:
                print("[social-floor] SLACK_WEBHOOK_URL unset — skipping POST.")
            else:
                _post_slack(webhook_url, text)

    # Exit 1 on CRITICAL so the verdict is visible in step annotations;
    # the workflow step carries continue-on-error so this NEVER blocks
    # the data commit (see the freeze postmortem in CLAUDE.md).
    return 1 if verdict == "CRITICAL" else 0


if __name__ == "__main__":
    sys.exit(main())
