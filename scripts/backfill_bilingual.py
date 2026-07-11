#!/usr/bin/env python3
"""
One-time / on-demand bilingual backfill for already-committed ranked data.

The nightly pipeline self-heals going forward: `apply_fallbacks` now
UPGRADES any monolingual title/USP string to a bilingual `{en, es}` dict,
and `ensure_bilingual` fills genuine broker text via DeepSeek. But the
data already committed to `web/data/*.json` keeps its monolingual strings
until the next nightly regenerates it. This script applies the same fix
immediately so a Spanish-locale user stops seeing English listing copy
without waiting a nightly cycle.

What it does per record:
  1. Deterministic bilingual upgrade (free, no API): re-run the template
     fallback so a monolingual `title_canonical` string / string-entry
     `reasons_to_buy` becomes bilingual.
  2. Optional DeepSeek translate-fill (`--llm`): translate a genuine
     single-language broker `title`/`description` for any listing the
     template fallback couldn't cover. Requires DEEPSEEK_API_TOKEN.

Dry-run by default — prints coverage before/after and writes nothing.
Pass `--write` to persist. Operates on the file list you give it, e.g.:

    python3 scripts/backfill_bilingual.py \
        web/data/ranked.json web/data/ranked.list.json \
        web/data/ranked.PA.json web/data/ranked.list.PA.json

    python3 scripts/backfill_bilingual.py --write --llm web/data/ranked.json

Because `web/data/*.json` is pipeline-owned, prefer letting the nightly
regenerate it; use `--write` only for an immediate remediation, and open
the resulting data change as its own PR (do not mix with code).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from automation.ai_enrichment_fallback import apply_fallbacks  # noqa: E402
from automation.ensure_bilingual import ensure_bilingual  # noqa: E402


def _bilingual(v) -> bool:
    return isinstance(v, dict) and bool(v.get("en")) and bool(v.get("es"))


def _reasons_ok(v) -> bool:
    return isinstance(v, list) and bool(v) and all(_bilingual(x) for x in v)


def _coverage(rows: list[dict]) -> tuple[int, int]:
    n = len(rows) or 1
    t = sum(1 for r in rows if _bilingual(r.get("title_canonical")))
    return round(100 * t / n), n


def main() -> int:
    ap = argparse.ArgumentParser(description="Bilingual backfill for ranked data.")
    ap.add_argument("files", nargs="+", help="ranked*.json files to process")
    ap.add_argument("--write", action="store_true", help="persist changes (default: dry-run)")
    ap.add_argument("--llm", action="store_true",
                    help="also DeepSeek-translate genuine broker text (needs DEEPSEEK_API_TOKEN)")
    ap.add_argument("--cache", default="web/data/bilingual_fill.json",
                    help="reusable translate cache path")
    args = ap.parse_args()

    total_upgraded = 0
    total_filled = 0
    for f in args.files:
        path = Path(f)
        if not path.exists():
            print(f"[backfill] SKIP missing {f}")
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            print(f"[backfill] SKIP {f}: not a list")
            continue

        pct_before, n = _coverage(rows)
        upgraded = sum(1 for r in rows if apply_fallbacks(r))
        total_upgraded += upgraded

        filled = 0
        if args.llm:
            m = ensure_bilingual(rows, Path(args.cache),
                                 log_path=Path("web/data/bilingual_fill_log.jsonl"))
            filled = m.get("filled", 0)
            total_filled += filled
            if m.get("skipped_no_token"):
                print("[backfill] --llm requested but DEEPSEEK_API_TOKEN missing; "
                      "deterministic upgrade applied, translate-fill skipped")

        pct_after, _ = _coverage(rows)
        usps_bad = sum(1 for r in rows
                       if isinstance(r.get("reasons_to_buy"), list)
                       and r["reasons_to_buy"]
                       and not _reasons_ok(r.get("reasons_to_buy")))
        print(f"[backfill] {f}: {n} rows | title bilingual {pct_before}% -> {pct_after}% "
              f"| upgraded={upgraded} filled(llm)={filled} | residual mono-usps={usps_bad}")

        if args.write:
            from automation._atomic import atomic_write_json
            atomic_write_json(path, rows, indent=2, default=str)
            print(f"[backfill]   wrote {f}")

    mode = "WROTE" if args.write else "DRY-RUN (no files written; pass --write to persist)"
    print(f"[backfill] done — {mode}. total upgraded={total_upgraded} filled={total_filled}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
