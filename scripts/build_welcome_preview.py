#!/usr/bin/env python3
"""Render the Pulpo Pro Welcome template against live ranked.json.

Produces two HTML files in web/ — one EN, one ES — that can be opened
in a browser for visual review. Mirrors the dry-run pattern of
`scripts/build_newsletter_dryrun.py` but targets the welcome template
specifically.

Usage:
    python3 scripts/build_welcome_preview.py
    python3 scripts/build_welcome_preview.py --out-dir web --tag v1
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.newsletter import build_issue  # noqa: E402
from automation.newsletter.store import email_hash  # noqa: E402
from automation.newsletter.templates import pulpo_pro_welcome  # noqa: E402
from automation.newsletter.types import Preference, Recipient  # noqa: E402


def _recipient(locale: str) -> Recipient:
    """Fresh-Pro recipient — display_name set, no saves yet, filter
    minimal. Mirrors what we'd expect to see for a real first-time
    Pro user the moment after Stripe confirms their first payment."""
    return Recipient(
        email_hash=email_hash(f"welcome-preview-{locale}@pulpo.club"),
        display_name="Sebastian",
        locale=locale,
        tier="pro",
        has_account=True,
        preference=Preference(
            departments=["La Libertad"],
            property_types=["land", "house"],
            max_price_usd=500_000,
            categories=[],
        ),
        saved_count=0,
        saves=[],
    )


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ranked", default="web/data/ranked.json")
    p.add_argument("--out-dir", default="web")
    p.add_argument("--tag", default="v1", help="version tag in output filename")
    p.add_argument("--issue-number", type=int, default=1,
                   help="picks issue number for the embedded date strip")
    args = p.parse_args()

    ranked_path = Path(args.ranked)
    if not ranked_path.exists():
        print(f"[welcome-preview] missing ranked.json at {ranked_path}", file=sys.stderr)
        return 1
    with ranked_path.open() as fh:
        ranked = json.load(fh)
    ranked = sorted(ranked, key=lambda x: x.get("rank") or 9_999)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    issue_date = datetime.now(timezone.utc)

    for locale in ("en", "es"):
        recipient = _recipient(locale)
        issue = build_issue(
            recipient=recipient,
            ranked_listings=ranked,
            issue_number=args.issue_number,
            issue_date=issue_date,
            history_rows=[],
        )
        html = pulpo_pro_welcome.render(issue)
        path = out_dir / f"newsletter-welcome-pro-{args.tag}-{locale}.html"
        path.write_text(html)
        size_kb = path.stat().st_size / 1024
        n_top = len(issue.picks_top)
        n_short = len(issue.picks_shortlist)
        print(
            f"[welcome-preview] locale={locale}  top={n_top}  short={n_short}  "
            f"{size_kb:.1f}KB → {path}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
