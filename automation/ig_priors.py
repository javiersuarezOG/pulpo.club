"""ig_priors.py — cross-surface priors so the Growth Hacker starts smart.

The IG learning loop (ig_learning.py) is blind until IG posts accrue their
own engagement. But we already know a LOT about what converts — from the
website. This module reads on-site behavior out of PostHog, maps it onto
the same content dimensions the autopilot steers on, and writes priors the
loop can lean on while its own signal is thin.

The bridge: website signal is per-LISTING (card.clicked, paywall.shown),
while the loop learns per category / zone. So we join
``listing_id → ranked.json → color_key (property_type + coast) + zone`` and
aggregate. Story / emotion have no on-site equivalent, so they are NOT
seeded here — category + zone are the listing-selection levers this fills.

Signal is INTENT-WEIGHTED (Javi, 2026-08-09): a paywall hit (someone
clicked a listing and hit the wall — real buying intent) counts far more
than a plain card click. Per category/zone we take the MEAN intent per
listing (so a category isn't rewarded just for having more inventory
shown), then normalize to a bounded multiplier around the field mean — the
same [0.5, 2.0] shape ig_learning.pick_weight uses, so the consumer can
drop it in. A category/zone stays neutral (1.0) until MIN_LISTINGS distinct
listings back it (cold-start guard).

Contract: soft-fail. No PostHog read key → empty priors → the loop is
exactly as it is today. Never raises. Offline/CI safe.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from automation._atomic import atomic_write_json
from automation import posthog_query as _pq
from automation.ig_story_series import _color_key

RANKED_PATH = Path("web/data/ranked.json")
PRIORS_ARTIFACT = Path("web/data/ig_priors.json")

WINDOW_DAYS = 30
# A category/zone needs this many distinct signal-bearing listings before
# its prior is trusted — else neutral, so one hot listing can't swing it.
MIN_LISTINGS = 4

# Intent weights: a paywall hit (clicked a listing, hit the wall) is strong
# buying intent; a card click is browsing. Signups are site-level (not tied
# to one listing) so they're not per-listing here — the /go router already
# attributes IG signups per post in ig_learning v2.
_W_CLICK = 1.0
_W_PAYWALL = 5.0


def _listing_index(ranked_path: Optional[Path] = None) -> dict:
    """listing_id -> {color_key, zone} from ranked.json. Empty on trouble.
    Resolve the path at call time (not as a default) so tests/monkeypatch of
    RANKED_PATH take effect."""
    ranked_path = ranked_path or RANKED_PATH
    try:
        raw = json.loads(ranked_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = raw if isinstance(raw, list) else (raw.get("listings") or raw.get("items") or [])
    out: dict = {}
    for li in items:
        lid = f"{li.get('source')}__{li.get('source_id')}"
        try:
            ck = _color_key(li)
        except Exception:  # pragma: no cover - _color_key is defensive already
            ck = None
        out[lid] = {"color_key": ck, "zone": li.get("zone")}
    return out


def fetch_listing_intent(*, window_days: int = WINDOW_DAYS) -> dict:
    """Per-listing intent from PostHog: {listing_id: {clicks, paywall_hits}}.
    Empty {} when the read key is absent or the query fails (soft-fail)."""
    hogql = (
        "SELECT properties.listing_id AS lid, "
        "countIf(event = 'card.clicked') AS clicks, "
        "countIf(event = 'paywall.shown' AND properties.kind = 'listing_click') AS paywall_hits "
        "FROM events "
        "WHERE event IN ('card.clicked', 'paywall.shown') "
        "AND properties.listing_id != '' "
        f"AND timestamp > now() - INTERVAL {int(window_days)} DAY "
        "GROUP BY lid"
    )
    rows = _pq.query(hogql)
    if not rows:
        return {}
    out: dict = {}
    for r in rows:
        lid = r.get("lid")
        if not lid:
            continue
        out[lid] = {"clicks": int(r.get("clicks") or 0),
                    "paywall_hits": int(r.get("paywall_hits") or 0)}
    return out


def _intent(rec: dict) -> float:
    return _W_CLICK * rec.get("clicks", 0) + _W_PAYWALL * rec.get("paywall_hits", 0)


def _normalize(raw_means: dict) -> dict:
    """Turn {key: mean_intent} into {key: {weight, ...}} — weight is the
    ratio to the field mean, clamped to [0.5, 2.0]. Neutral (1.0) when there
    aren't ≥2 values to compare against."""
    trusted = {k: v["mean"] for k, v in raw_means.items() if v["trusted"]}
    avg = (sum(trusted.values()) / len(trusted)) if trusted else 0.0
    out = {}
    for k, v in raw_means.items():
        if v["trusted"] and avg > 0 and len(trusted) >= 2:
            weight = max(0.5, min(2.0, v["mean"] / avg))
        else:
            weight = 1.0
        out[k] = {"weight": round(weight, 4), "n_listings": v["n"],
                  "trusted": v["trusted"], "mean_intent": round(v["mean"], 4)}
    return out


def build_priors(intent_by_listing: dict, listing_index: dict, *, now_iso: str = "") -> dict:
    """Pure: per-listing intent + listing→(category,zone) index → priors.
    Deterministic, never raises."""
    cat_intents: dict = defaultdict(list)
    zone_intents: dict = defaultdict(list)
    matched = 0
    for lid, rec in intent_by_listing.items():
        meta = listing_index.get(lid)
        if not meta:
            continue
        score = _intent(rec)
        matched += 1
        if meta.get("color_key"):
            cat_intents[meta["color_key"]].append(score)
        if meta.get("zone"):
            zone_intents[meta["zone"]].append(score)

    def _means(bucket):
        return {k: {"mean": (sum(v) / len(v)) if v else 0.0, "n": len(v),
                    "trusted": len(v) >= MIN_LISTINGS}
                for k, v in bucket.items()}

    categories = _normalize(_means(cat_intents))
    zones = _normalize(_means(zone_intents))
    cat_trusted = {k: v["weight"] for k, v in categories.items() if v["trusted"]}
    zone_trusted = {k: v["weight"] for k, v in zones.items() if v["trusted"]}
    return {
        "version": 1,
        "computed_at": now_iso,
        "window_days": WINDOW_DAYS,
        "source": "website:card.clicked+paywall.shown (intent-weighted)",
        "n_listings_with_signal": matched,
        "categories": categories,
        "zones": zones,
        "leaders": {
            "category": max(cat_trusted, key=cat_trusted.get) if cat_trusted else None,
            "zone": max(zone_trusted, key=zone_trusted.get) if zone_trusted else None,
        },
    }


def run(*, now: Optional[datetime] = None) -> int:
    """Fetch on-site intent, build priors, write atomically. Returns the
    number of signal-bearing listings matched (0 on no key / trouble)."""
    now = now or datetime.now(timezone.utc)
    intent = fetch_listing_intent()
    index = _listing_index()
    priors = build_priors(intent, index, now_iso=now.isoformat())
    try:
        atomic_write_json(PRIORS_ARTIFACT, priors)
    except OSError as err:  # pragma: no cover - disk trouble
        print(f"[ig_priors] write failed: {err}")
        return 0
    lead = priors["leaders"]
    print(f"[ig_priors] {priors['n_listings_with_signal']} listing(s) with signal → "
          f"top category={lead.get('category')} zone={lead.get('zone')} → {PRIORS_ARTIFACT}")
    return priors["n_listings_with_signal"]


if __name__ == "__main__":  # pragma: no cover
    run()
