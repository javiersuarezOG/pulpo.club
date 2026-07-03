"""
One-shot retroactive sold/delisted sweep over the existence ledger's
missing/stale backlog (plan 012).

The nightly probes at most PULPO_SOLD_PROBE_MAX entries per run; this
script clears an accumulated backlog in one sitting. Same classifier,
same transport policy, same ledger writes as the nightly — see
automation/sold_probe.py.

Usage:
    python3 scripts/probe_stale_listings.py --dry-run --limit 5
    python3 scripts/probe_stale_listings.py            # probe up to 200
    python3 scripts/probe_stale_listings.py --llm-budget 100
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Load .env if not already exported (DEEPSEEK_API_TOKEN for the LLM fallback)
if not os.environ.get("DEEPSEEK_API_TOKEN"):
    env_file = REPO / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from automation.listing_ledger import load_ledger, save_ledger  # noqa: E402
from automation.sold_probe import probe_missing_listings  # noqa: E402

LEDGER = REPO / "web" / "data" / "listings_ledger.json"
RANKED = REPO / "web" / "data" / "ranked.json"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=200,
                   help="max probe attempts (default 200)")
    p.add_argument("--dry-run", action="store_true",
                   help="classify + print; don't write the ledger")
    p.add_argument("--llm-budget", type=int, default=50,
                   help="max DeepSeek fallback calls (default 50)")
    args = p.parse_args()

    ledger = load_ledger(LEDGER)
    if not ledger:
        print(f"no ledger at {LEDGER} — nothing to probe")
        return

    urls_by_key: dict[str, str] = {}
    try:
        ranked = json.loads(RANKED.read_text(encoding="utf-8"))
        if isinstance(ranked, list):
            for row in ranked:
                if isinstance(row, dict) and row.get("url"):
                    urls_by_key[f"{row.get('source')}|{row.get('source_id')}"] = str(row["url"])
    except (OSError, json.JSONDecodeError):
        print(f"warning: could not read {RANKED} — entries without URLs are skipped")

    candidates = [
        k for k, e in ledger.items()
        if e.existence_status in ("missing_recently", "stale")
        and e.removal_reason is None
    ]
    print(f"ledger entries={len(ledger)} probe candidates={len(candidates)} "
          f"urls available={sum(1 for k in candidates if k in urls_by_key)}")

    before = {k: ledger[k].removal_reason for k in candidates}
    metrics = probe_missing_listings(
        ledger,
        urls_by_key=urls_by_key,
        max_probes=args.limit,
        llm_budget=args.llm_budget,
        now_iso=datetime.now(timezone.utc).isoformat(),
    )

    print(f"[sold_probe] probed={metrics['probed']} sold={metrics['sold']} "
          f"delisted={metrics['delisted']} unknown={metrics['unknown']} "
          f"active={metrics['active']} fetch_errors={metrics['fetch_errors']} "
          f"skipped_no_url={metrics['skipped_no_url']} "
          f"llm_calls={metrics['llm_calls']} cost=${metrics['cost_usd']:.4f}")

    changed = [
        k for k in candidates
        if ledger[k].removal_reason is not None and before.get(k) is None
    ]
    if changed:
        print(f"\nnew classifications ({len(changed)}):")
        print(f"  {'key':<45} {'reason':<10} detected_at")
        for k in sorted(changed):
            e = ledger[k]
            print(f"  {k:<45} {e.removal_reason:<10} {e.removal_detected_at}")
    else:
        print("\nno new classifications")

    if args.dry_run:
        print("\n--dry-run: ledger NOT written")
        return
    save_ledger(ledger, LEDGER)
    print(f"\nledger saved → {LEDGER}")


if __name__ == "__main__":
    main()
