#!/usr/bin/env python3
"""Refresh the Weekly News Spotlight artifact (``web/data/news_spotlight.json``).

Runs in the nightly pipeline, where ``DEEPSEEK_API_TOKEN`` is available.
For each locale it fetches RSS candidates + LLM-picks the most relevant
article and, IF a real pick comes back, overwrites that locale's entry.
On a slow news week (no pick) it leaves the existing entry untouched —
carry-forward guarantees every Pro email keeps citing the most recent
REAL article, no matter how far back that was.

This is the ONLY writer of the artifact. The email-send path
(``automation.newsletter.build_issue._make_news_spotlight``) only reads it,
so the Stripe-webhook-triggered welcome emails on Vercel — which have no
DeepSeek key — still render real, attributed news.

Exit code is always 0 (the nightly wraps this in ``continue-on-error``):
a flaky news fetch must never block the data PR. The freshness canary
(separate nightly step) is what pages when a locale has no seed at all.

Usage::

    python3 scripts/refresh_news_spotlight.py [--locales en,es] [--path PATH]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow ``python3 scripts/refresh_news_spotlight.py`` from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.newsletter import news_store  # noqa: E402

LOCALES = ("en", "es")

# Per-locale outcomes.
REFRESHED = "refreshed"            # fresh LLM pick written
CARRIED_FORWARD = "carried_forward"  # no fresh pick; prior real article kept
NO_SEED = "no_seed"               # no fresh pick AND no prior seed → empty spotlight


def refresh(*, locales=LOCALES, fetch_fn=None, now=None, path=None, log=print) -> dict:
    """Refresh each locale's spotlight. Returns ``{locale: outcome}``.

    ``fetch_fn`` defaults to ``llm_news.fetch_pick_and_summarize`` and is
    dependency-injected in tests. ``now`` stamps ``picked_at`` for lineage.
    """
    if fetch_fn is None:
        from automation.newsletter import llm_news
        fetch_fn = llm_news.fetch_pick_and_summarize
    now = now or datetime.now(timezone.utc)
    picked_at = now.strftime("%Y-%m-%d")

    results: dict[str, str] = {}
    for lc in locales:
        try:
            spot = fetch_fn(locale=lc)
        except Exception as exc:  # noqa: BLE001 — a flaky fetch must carry forward, not crash
            spot = None
            log(f"[news-spotlight] {lc}: fetch raised ({exc!r}); carrying forward")

        if spot is not None:
            news_store.save_spotlight(lc, spot, path=path, picked_at=picked_at)
            results[lc] = REFRESHED
            log(f"[news-spotlight] {lc}: refreshed → {spot.source_name} · {spot.source_url}")
            continue

        existing = news_store.load_spotlight(lc, path=path)
        if existing is not None:
            results[lc] = CARRIED_FORWARD
            log(
                f"[news-spotlight] {lc}: no fresh pick; carrying forward "
                f"{existing.source_name} · {existing.source_url}"
            )
        else:
            results[lc] = NO_SEED
            log(
                f"::warning::[news-spotlight] {lc}: no fresh pick AND no prior "
                f"seed — spotlight will be EMPTY for this locale"
            )
    return results


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--locales", default=",".join(LOCALES),
                    help="comma-separated locale codes (default: en,es)")
    ap.add_argument("--path", default=None,
                    help="override artifact path (default: web/data/news_spotlight.json)")
    args = ap.parse_args(argv)
    locales = tuple(x.strip() for x in args.locales.split(",") if x.strip())
    results = refresh(locales=locales, path=args.path)
    print(f"[news-spotlight] summary: {results}")
    # Never non-zero — the nightly carries forward on any failure. Cold-start
    # (no_seed) is surfaced by the freshness canary, not by failing here.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
