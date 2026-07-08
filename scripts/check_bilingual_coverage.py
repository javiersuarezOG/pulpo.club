#!/usr/bin/env python3
"""
Bilingual-coverage canary — alert (never block) when served listings carry
monolingual copy that would leak one language into the other locale.

Every listing rendered by the app must carry BOTH en + es on title,
description, and reasons-to-buy (the pipeline guarantees this: the
deterministic fallback emits bilingual templates and ensure_bilingual
translates genuine broker text). This canary is the trip-wire for a
regression — a scraper/enrichment/fallback change that starts shipping a
monolingual string again. It measures per-country coverage in the files
the frontend actually fetches (ranked.list*.json) and Slack-pages when a
field drops below threshold or ANY monolingual entry is present.

Per the "never silent-freeze data" guardrails in CLAUDE.md this NEVER
blocks the nightly: it always exits 0 unless run with --strict (used only
to prove the guardrail fires on a known-bad input in CI). A missing field
is NOT a leak — a listing with no description is fine; a listing with a
single-language description is the leak. So coverage is measured over
records that HAVE the field.

Usage:
    python3 scripts/check_bilingual_coverage.py --data-dir web/data
    SLACK_WEBHOOK_URL=... python3 scripts/check_bilingual_coverage.py --run-url "$URL"
    python3 scripts/check_bilingual_coverage.py --strict   # CI guardrail self-test
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

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# Reuse the pipeline's language heuristic so producer + guard agree.
from automation.ensure_bilingual import detect_lang  # noqa: E402

# Files the frontend fetches, per country. The apex serves ranked.list.json;
# PA serves ranked.list.PA.json. We check both so a per-country regression
# (PA enrichment down) is caught even when the SV apex is healthy.
_LIST_FILES = ["ranked.list.json", "ranked.list.PA.json"]

# Title should be ~100% (every listing gets a bilingual fallback title).
# Description/USPs are measured over records that carry them.
_DEFAULT_TITLE_THRESHOLD = 99.0
_DEFAULT_FIELD_THRESHOLD = 98.0


def _bilingual(v: Any) -> bool:
    return isinstance(v, dict) and bool(v.get("en")) and bool(v.get("es"))


def _present_title(v: Any) -> bool:
    return isinstance(v, (str, dict)) and bool(v)


def _present_reasons(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0


def _reasons_bilingual(v: Any) -> bool:
    return isinstance(v, list) and len(v) > 0 and all(_bilingual(x) for x in v)


# A bilingual description whose two sides are IDENTICAL (beyond a trivial
# length) was not actually translated — the same text sits in both slots,
# so one locale is reading the other's language. Titles are exempt: a short
# language-neutral title ("Villa 500", a bare place name) can legitimately
# match across languages; a real description cannot.
_IDENTICAL_MIN_CHARS = 25


def _identical_sides(v: Any) -> bool:
    return (
        _bilingual(v)
        and v["en"].strip() == v["es"].strip()
        and len(v["en"].strip()) >= _IDENTICAL_MIN_CHARS
    )


# Conservative wrong-slot detector: flag only when the .en side reads as
# Spanish AND the .es side reads as English — both heuristics agreeing that
# the languages are swapped. Requiring BOTH keeps false positives near-zero
# on ambiguous short strings (a single mis-detection never trips it). Guards
# the "DeepSeek put the wrong language in the right slot" bug class.
_SWAP_MIN_CHARS = 25


def _looks_swapped(v: Any) -> bool:
    if not _bilingual(v):
        return False
    en, es = v["en"].strip(), v["es"].strip()
    if len(en) < _SWAP_MIN_CHARS or len(es) < _SWAP_MIN_CHARS:
        return False
    return detect_lang(en) == "es" and detect_lang(es) == "en"


def audit_file(path: Path) -> Optional[dict]:
    """Return a coverage report for one ranked.list file, or None if absent."""
    if not path.exists():
        return None
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return {"file": path.name, "error": f"{type(e).__name__}: {e}"}
    if not isinstance(rows, list):
        return {"file": path.name, "error": "not a list"}

    n = len(rows)
    stats: dict[str, dict[str, int]] = {
        "title":       {"present": 0, "bilingual": 0, "mono": 0},
        "description": {"present": 0, "bilingual": 0, "mono": 0},
        "usps":        {"present": 0, "bilingual": 0, "mono": 0},
    }
    identical_desc = 0
    swapped_desc = 0
    for r in rows:
        tc = r.get("title_canonical")
        if _present_title(tc):
            stats["title"]["present"] += 1
            stats["title"]["bilingual" if _bilingual(tc) else "mono"] += 1
        dc = r.get("short_description_canonical")
        if _present_title(dc):
            stats["description"]["present"] += 1
            stats["description"]["bilingual" if _bilingual(dc) else "mono"] += 1
            if _identical_sides(dc):
                identical_desc += 1
            if _looks_swapped(dc):
                swapped_desc += 1
        rtb = r.get("reasons_to_buy")
        if _present_reasons(rtb):
            stats["usps"]["present"] += 1
            stats["usps"]["bilingual" if _reasons_bilingual(rtb) else "mono"] += 1

    def pct(field: str) -> float:
        p = stats[field]["present"]
        return 100.0 if p == 0 else round(100.0 * stats[field]["bilingual"] / p, 1)

    return {
        "file": path.name,
        "rows": n,
        "stats": stats,
        "pct": {f: pct(f) for f in stats},
        "identical_desc": identical_desc,
        "swapped_desc": swapped_desc,
    }


def failing(report: dict, title_threshold: float, field_threshold: float) -> list[str]:
    """Return human-readable failure lines for a report (empty = healthy)."""
    if "error" in report:
        return [f"`{report['file']}` unreadable: {report['error']}"]
    out: list[str] = []
    thresholds = {
        "title": title_threshold,
        "description": field_threshold,
        "usps": field_threshold,
    }
    for field, thr in thresholds.items():
        mono = report["stats"][field]["mono"]
        pc = report["pct"][field]
        if mono > 0 or pc < thr:
            out.append(
                f"`{report['file']}` {field}: {pc}% bilingual "
                f"({mono} monolingual of {report['stats'][field]['present']} present)"
            )
    identical = report.get("identical_desc", 0)
    if identical > 0:
        out.append(
            f"`{report['file']}` {identical} description(s) identical across "
            f"en/es (untranslated — same text in both locales)"
        )
    swapped = report.get("swapped_desc", 0)
    if swapped > 0:
        out.append(
            f"`{report['file']}` {swapped} description(s) with swapped languages "
            f"(en slot reads Spanish, es slot reads English)"
        )
    return out


def _post_slack(webhook_url: str, text: str) -> None:
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"[bilingual-coverage] Slack POST failed: {e}", file=sys.stderr)


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Bilingual-coverage canary (alert, never block).")
    ap.add_argument("--data-dir", default="web/data")
    ap.add_argument("--run-url", default=None)
    ap.add_argument("--title-threshold", type=float, default=_DEFAULT_TITLE_THRESHOLD)
    ap.add_argument("--field-threshold", type=float, default=_DEFAULT_FIELD_THRESHOLD)
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero on failure (CI guardrail self-test; nightly never uses this)")
    args = ap.parse_args(argv)

    data_dir = Path(args.data_dir)
    reports = [audit_file(data_dir / f) for f in _LIST_FILES]
    reports = [r for r in reports if r is not None]

    all_fail: list[str] = []
    for rep in reports:
        if "error" not in rep:
            print(f"[bilingual-coverage] {rep['file']}: {rep['rows']} rows | "
                  f"title {rep['pct']['title']}% | desc {rep['pct']['description']}% "
                  f"| usps {rep['pct']['usps']}%")
        all_fail.extend(failing(rep, args.title_threshold, args.field_threshold))

    if not all_fail:
        print("[bilingual-coverage] OK — all served listings bilingual on title/desc/usps ✓")
        return 0

    lines = ["*Pulpo: monolingual listing copy detected (i18n leak risk)*"]
    lines.extend("• " + f for f in all_fail)
    lines.append("A listing field present in only one language leaks that "
                 "language into the other locale. Fix: run the bilingual "
                 "backfill or investigate the enrichment/fallback regression.")
    if args.run_url:
        lines.append(f"<{args.run_url}|Open Actions run>")
    body = "\n".join(lines)
    print(body)

    webhook_url = os.environ.get("SLACK_WEBHOOK_URL", "")
    if webhook_url:
        _post_slack(webhook_url, body)
    else:
        print("[bilingual-coverage] SLACK_WEBHOOK_URL unset — skipping POST.")

    # Never block the nightly (CLAUDE.md: alert + backfill, don't freeze).
    return 1 if args.strict else 0


if __name__ == "__main__":
    sys.exit(main())
