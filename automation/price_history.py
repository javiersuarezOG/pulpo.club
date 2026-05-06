"""
PRD §FR-3 — price history sidecar + is_repriced derivation.

Extracted from automation/run.py so it's:
  - independently importable (tests, ad-hoc analysis)
  - independently testable (no full pipeline needed)
  - a clean module boundary for the FR-3 contract

Sidecar shape (web/data/prices_history.json):
    {
      "<source>|<source_id>": [
        {"ts": "2026-05-04T12:00:00+00:00", "price_usd": 300000.0},
        {"ts": "2026-05-08T12:00:00+00:00", "price_usd": 270000.0}
      ],
      ...
    }

Append-only — entries are added only when the price actually moves, so
listings with stable prices contribute one row total. History is capped
at PRICE_HISTORY_MAX_ENTRIES per listing (~1 year of daily nightlies).

Public API:

    from automation.price_history import track_prices
    metrics = track_prices(listings, sidecar_path, started_iso)
    # listings now have li.is_repriced set (cross-run derived)
    # sidecar updated and written to disk
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

# Cap to bound storage growth. ~1 year of daily nightlies; PRD §10
# documents a 2-year retention policy as the longer-term target.
PRICE_HISTORY_MAX_ENTRIES = 365


def _g(li: Any, name: str) -> Any:
    """Read field from dict or dataclass-like object."""
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


def _set(li: Any, name: str, value: Any) -> None:
    if isinstance(li, dict):
        li[name] = value
    else:
        setattr(li, name, value)


def _load_history(path: Path) -> dict:
    """Load prices_history.json. Returns empty dict on any error."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def track_prices(listings: list[Any], sidecar_path: Path,
                 started_iso: str) -> dict[str, int]:
    """Update the prices_history sidecar and set is_repriced on listings.

    For each listing with a non-null price_usd:
      - Append (ts, price_usd) to its history entry, but ONLY if the price
        differs from the most recent recorded value. Listings with stable
        prices contribute one row total.
      - Cap history at PRICE_HISTORY_MAX_ENTRIES entries per listing.
      - Set is_repriced = True iff current price < min(any prior recorded
        price for that listing). False when stable. First-ever scrape
        (no prior entries) leaves the field at its per-scraper default —
        no signal yet, don't override.

    The sidecar is written back unconditionally so consumers can rely on
    the file existing.

    Returns:
      {"tracked": N, "repriced_this_run": K} where N is total tracked
      listings (in-history dict size) and K is how many flipped to
      is_repriced=True this run.
    """
    history_dict = _load_history(sidecar_path)
    repriced_count = 0

    for li in listings:
        price = _g(li, "price_usd")
        if price is None:
            continue
        key = f"{_g(li, 'source')}|{_g(li, 'source_id')}"
        listing_history = history_dict.get(key) or []

        # Append only when price moved (or it's the first record).
        last_price = listing_history[-1].get("price_usd") if listing_history else None
        if last_price is None or float(last_price) != float(price):
            listing_history.append({"ts": started_iso, "price_usd": float(price)})
            listing_history = listing_history[-PRICE_HISTORY_MAX_ENTRIES:]
            history_dict[key] = listing_history

        # is_repriced = current strictly less than min(prior prices).
        # Excluding the just-appended entry to avoid self-reference.
        prior_prices = [h["price_usd"] for h in listing_history[:-1]] if listing_history else []
        if prior_prices:
            if float(price) < min(prior_prices):
                _set(li, "is_repriced", True)
                repriced_count += 1
            else:
                _set(li, "is_repriced", False)
        # else: first scrape ever — leave per-scraper value untouched

    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    with sidecar_path.open("w", encoding="utf-8") as f:
        json.dump(history_dict, f, ensure_ascii=False)

    return {"tracked": len(history_dict), "repriced_this_run": repriced_count}
