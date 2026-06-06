"""Persisted Weekly News Spotlight store.

The Weekly News Spotlight in every Pro email is READ from a committed
artifact (``web/data/news_spotlight.json``) — it is NOT fetched live at
send time. This decouples the email-send hot path (the Stripe-webhook-
triggered welcome / welcome-back emails that run on Vercel without a
DeepSeek key, plus the weekly cron) from the flaky RSS-fetch + LLM call,
and guarantees every Pro email cites a real article from a real outlet.

The artifact has ONE writer: ``scripts/refresh_news_spotlight.py`` runs in
the nightly pipeline (where ``DEEPSEEK_API_TOKEN`` lives), picks a fresh
article, and overwrites that locale's entry. On a slow news week the
refresh finds nothing and leaves the file untouched — so ``load_spotlight``
always returns the most recent REAL pick (carry-forward, no age cap).

Shape (``web/data/news_spotlight.json``)::

    {
      "en": {title, paragraph, source_name, source_url, source_date,
             candidates_seen, llm_cost_usd, picked_at, issue_number},
      "es": { ... }
    }

``picked_at`` / ``issue_number`` are lineage-only (post-mortems, freshness
canary) and are ignored when hydrating the ``NewsSpotlight`` dataclass.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .types import NewsSpotlight

# Repo-root-relative default. Tests override via PULPO_NEWS_SPOTLIGHT_PATH
# or an explicit ``path=`` argument so they never touch the real artifact.
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "web" / "data" / "news_spotlight.json"

_PATH_ENV = "PULPO_NEWS_SPOTLIGHT_PATH"


def _resolve_path(path=None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get(_PATH_ENV, "").strip()
    return Path(env) if env else _DEFAULT_PATH


def _read_all(path: Path) -> dict:
    """Whole-file read → dict. Missing file / malformed JSON → ``{}`` so the
    caller degrades to "no spotlight" rather than raising on a cold start."""
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def load_spotlight(locale: str, *, path=None) -> Optional[NewsSpotlight]:
    """Return the carried-forward ``NewsSpotlight`` for ``locale``.

    Returns ``None`` when the artifact is missing, the locale has never
    been populated, or the stored entry is incomplete. Never raises.

    ``title`` + ``paragraph`` + ``source_url`` are the minimum bar for a
    real, citable spotlight: an entry missing any of them renders nothing
    rather than half a story or a source-less filler. This is the
    contract that keeps "every shipped spotlight cites a real outlet"
    true even if the artifact is hand-edited.
    """
    entry = _read_all(_resolve_path(path)).get(locale)
    if not isinstance(entry, dict):
        return None
    if not entry.get("title") or not entry.get("paragraph") or not entry.get("source_url"):
        return None
    try:
        return NewsSpotlight(
            title=str(entry["title"]),
            paragraph=str(entry["paragraph"]),
            source_name=str(entry.get("source_name") or ""),
            source_url=str(entry["source_url"]),
            source_date=str(entry.get("source_date") or ""),
            candidates_seen=int(entry.get("candidates_seen") or 0),
            llm_cost_usd=float(entry.get("llm_cost_usd") or 0.0),
        )
    except (TypeError, ValueError):
        return None


def save_spotlight(
    locale: str,
    spotlight: NewsSpotlight,
    *,
    path=None,
    picked_at: Optional[str] = None,
    issue_number: Optional[int] = None,
) -> dict:
    """Overwrite the ``locale`` entry with ``spotlight``, preserving every
    other locale already in the file. Atomic (temp-file + ``os.replace``)
    so a crash mid-write can't corrupt the carry-forward source of truth.
    Returns the written entry dict.
    """
    p = _resolve_path(path)
    data = _read_all(p)
    entry: dict = {
        "title": spotlight.title,
        "paragraph": spotlight.paragraph,
        "source_name": spotlight.source_name,
        "source_url": spotlight.source_url,
        "source_date": spotlight.source_date,
        "candidates_seen": spotlight.candidates_seen,
        "llm_cost_usd": spotlight.llm_cost_usd,
    }
    if picked_at:
        entry["picked_at"] = picked_at
    if issue_number is not None:
        entry["issue_number"] = issue_number
    data[locale] = entry

    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, p)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return entry
