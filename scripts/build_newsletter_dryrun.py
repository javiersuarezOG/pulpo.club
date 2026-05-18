#!/usr/bin/env python3
"""Dry-run the newsletter renderer against the live ranked.json.

Produces one HTML file per cohort fixture in newsletter-drafts/, mimicking
the real send pipeline without touching Resend.

Usage:
    python3 scripts/build_newsletter_dryrun.py
    python3 scripts/build_newsletter_dryrun.py --recipient javier  # one fixture
    python3 scripts/build_newsletter_dryrun.py --issue-number 2 --locale es
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Make the automation/ package importable when run from the repo root.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.newsletter import build_issue, render_html  # noqa: E402
from automation.newsletter.store import email_hash  # noqa: E402
from automation.newsletter.types import Preference, Recipient  # noqa: E402


# ── Cohort fixtures ────────────────────────────────────────────────────
# Each fixture is a single Recipient + a description. Names + emails are
# synthetic and do NOT correspond to real users.

FIXTURES = [
    {
        "key": "pro-prefs",
        "label": "A · Pro + prefs (Javier in La Libertad)",
        "recipient": Recipient(
            email_hash=email_hash("javier-fixture@pulpo.club"),
            display_name="Javier",
            locale="en",
            tier="pro",
            has_account=True,
            preference=Preference(
                departments=["La Libertad"],
                property_types=["land", "house"],
                max_price_usd=500_000,
                categories=[],
            ),
        ),
    },
    {
        "key": "free-prefs",
        "label": "B · Free + prefs (paywalled below pick #1)",
        "recipient": Recipient(
            email_hash=email_hash("free-fixture@pulpo.club"),
            display_name="Sofía",
            locale="en",
            tier="free",
            has_account=True,
            preference=Preference(
                zones=["el-zonte", "el-tunco"],
                property_types=["land"],
                max_price_usd=250_000,
                categories=[],
            ),
        ),
    },
    {
        "key": "logged-no-prefs",
        "label": "C · Logged in, no prefs (fallback)",
        "recipient": Recipient(
            email_hash=email_hash("blank-fixture@pulpo.club"),
            display_name="Lucas",
            locale="en",
            tier="pro",
            has_account=True,
            preference=Preference(),
        ),
    },
    {
        "key": "anonymous",
        "label": "D · Anonymous email (welcome edition)",
        "recipient": Recipient(
            email_hash=email_hash("anon-fixture@pulpo.club"),
            display_name=None,
            locale="en",
            tier="free",
            has_account=False,
            preference=Preference(),
        ),
    },
    {
        "key": "pro-prefs-es",
        "label": "A · Pro + prefs (Spanish locale)",
        "recipient": Recipient(
            email_hash=email_hash("javier-es-fixture@pulpo.club"),
            display_name="Javier",
            locale="es",
            tier="pro",
            has_account=True,
            preference=Preference(
                departments=["La Libertad"],
                property_types=["land", "house"],
                max_price_usd=500_000,
                categories=[],
            ),
        ),
    },
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ranked", default="web/data/ranked.json")
    p.add_argument("--out-dir", default="newsletter-drafts")
    p.add_argument("--issue-number", type=int, default=2)
    p.add_argument("--recipient", default=None, help="filter to one fixture by key prefix")
    args = p.parse_args()

    ranked_path = Path(args.ranked)
    if not ranked_path.exists():
        print(f"[dryrun] missing ranked.json at {ranked_path}", file=sys.stderr)
        return 1
    with ranked_path.open() as fh:
        ranked = json.load(fh)
    # Make sure the list is in rank order.
    ranked = sorted(ranked, key=lambda x: x.get("rank") or 9_999)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    issue_date = datetime.now(timezone.utc)

    fixtures = FIXTURES
    if args.recipient:
        fixtures = [f for f in FIXTURES if f["key"].startswith(args.recipient)]
        if not fixtures:
            print(f"[dryrun] no fixture matches --recipient {args.recipient!r}", file=sys.stderr)
            return 1

    for fx in fixtures:
        issue = build_issue(
            recipient=fx["recipient"],
            ranked_listings=ranked,
            issue_number=args.issue_number,
            issue_date=issue_date,
            history_rows=[],  # no prior sends in dry-run
        )
        html = render_html(issue)
        slug = fx["key"]
        path = out_dir / f"dryrun-{issue.issue_id}-issue{args.issue_number:02d}-{slug}.html"
        path.write_text(html)
        n_top = len(issue.picks_top)
        n_short = len(issue.picks_shortlist)
        skip = "yes" if issue.skip_pick else "no"
        size_kb = path.stat().st_size / 1024
        print(
            f"[dryrun] {fx['label']:<50s}  cohort={issue.cohort:<16s} "
            f"top={n_top} short={n_short} skip={skip} {size_kb:.1f}KB → {path}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
