"""ig_triggers.py — detect newsworthy listings to break the calendar.

The IG batch 1 calendar (shelf-driven, picked by the queue builder in
PR-3) covers the "always on" cadence.  Triggers cover the "this is worth
posting NOW" — a fresh bargain, a new top-rank entry, a sudden price
drop.  Each trigger has:

  - a deterministic data condition (no LLM, no judgment),
  - a frequency cap (max N per N-day window),
  - a priority (the queue injection in PR-3 honours the highest first),
  - a stable rationale string the caption writer renders verbatim.

For batch 1 the detector runs nightly and writes web/data/ig_triggers.json
*for observation only* — the queue builder ignores it until
IG_TRIGGERS_ENABLED=1 flips on (likely batch 2 once we see whether the
disqualifications hold up over a fortnight).

Six triggers per the original brief:

  1. BARGAIN_ALERT       price_vs_zone_pct ≤ −20% (default; tunable)
  2. TOP_RANK            entered the top N of the catalogue (rank ≤ N)
  3. PRICE_DROP          is_repriced AND previous_price > price_usd
  4. FRESH_AND_HOT       days_listed ≤ 7 AND rank ≤ 100
  5. ZONE_DOMINATION     ≥3 listings of same zone in top 50
                         (zone-level, not listing-level)
  6. COMPARABLE_CRASH    price_per_m2 ≤ 0.4 × zone median, with ≥3
                         comparables in the zone

Output: web/data/ig_triggers.json
{
  "version": 1,
  "computed_at": "...",
  "config":     {...},
  "stats":      {"scanned": 879, "candidates_per_trigger": {...}},
  "triggers":   [
    {
      "trigger":      "BARGAIN_ALERT",
      "listing_id":   "bienesraices__1059",
      "source":       "bienesraices",
      "source_id":    "1059",
      "rank":         49,
      "priority":     1,
      "data": {
        "price_vs_zone_pct": -93.0,
        "price_per_m2":      11.82,
        ...
      },
      "rationale":    "Precio por m² 93% debajo de la mediana de la zona.",
      "detected_at":  "..."
    },
    ...
  ]
}

Cap logic lives here (not in the queue builder) because the cap depends
only on the trigger output itself — once filtered, each entry is "ready
to inject" and the queue builder just picks priority + freshness.

CLI:
  python3 -m automation.ig_triggers [--ranked PATH] [--output PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from automation._atomic import atomic_write_json
from automation._config import env_float, env_int
from automation.ig_photo_gate import passes_gate


# ── tunables ───────────────────────────────────────────────────────────

def _config_snapshot() -> dict[str, Any]:
    """Snapshot of trigger thresholds + caps.  Embedded in output JSON
    so a sudden surge/drop in candidates can be traced to a config drift."""
    return {
        "bargain_pct_threshold":   env_float("IG_TRIG_BARGAIN_PCT",        -20.0),
        "bargain_cap_per_week":    env_int("IG_TRIG_BARGAIN_CAP",          2),
        "top_rank_threshold":      env_int("IG_TRIG_TOP_RANK",             15),
        "top_rank_cap_per_week":   env_int("IG_TRIG_TOP_RANK_CAP",         2),
        "price_drop_cap_per_week": env_int("IG_TRIG_PRICE_DROP_CAP",       2),
        "fresh_days_threshold":    env_int("IG_TRIG_FRESH_DAYS",           7),
        "fresh_rank_threshold":    env_int("IG_TRIG_FRESH_RANK",           100),
        "fresh_cap_per_week":      env_int("IG_TRIG_FRESH_CAP",            1),
        "zone_dom_count":          env_int("IG_TRIG_ZONE_DOM_COUNT",       3),
        "zone_dom_top_n":          env_int("IG_TRIG_ZONE_DOM_TOP_N",       50),
        "zone_dom_cap_per_week":   env_int("IG_TRIG_ZONE_DOM_CAP",         1),
        "comp_crash_ratio":        env_float("IG_TRIG_COMP_CRASH_RATIO",   0.40),
        "comp_crash_min_comps":    env_int("IG_TRIG_COMP_CRASH_MIN_COMPS", 3),
        "comp_crash_cap_per_week": env_int("IG_TRIG_COMP_CRASH_CAP",       1),
    }


# Trigger name constants — used by output records and by the queue
# builder in PR-3 when deciding injection priority.  Keep stable.
BARGAIN_ALERT     = "BARGAIN_ALERT"
TOP_RANK          = "TOP_RANK"
PRICE_DROP        = "PRICE_DROP"
FRESH_AND_HOT     = "FRESH_AND_HOT"
ZONE_DOMINATION   = "ZONE_DOMINATION"
COMPARABLE_CRASH  = "COMPARABLE_CRASH"

# Priority order — higher number = ranked higher when the queue builder
# decides which trigger to inject when multiple fire on the same day.
# Rationale: a true price-drop is the most newsworthy (proof of market
# movement); bargain and comp-crash compete for second place (both are
# value calls); top rank and fresh are softer signals; zone domination
# is a roundup, lowest urgency.
_PRIORITY = {
    PRICE_DROP:        5,
    BARGAIN_ALERT:     4,
    COMPARABLE_CRASH:  4,
    TOP_RANK:          3,
    FRESH_AND_HOT:     2,
    ZONE_DOMINATION:   1,
}


def _listing_id(li: dict) -> str:
    return f"{li.get('source', 'unknown')}__{li.get('source_id', 'unknown')}"


def _base_record(li: dict, trigger: str, rationale: str, **data: Any) -> dict:
    return {
        "trigger":     trigger,
        "listing_id":  _listing_id(li),
        "source":      li.get("source"),
        "source_id":   li.get("source_id"),
        "rank":        li.get("rank"),
        "priority":    _PRIORITY[trigger],
        "data":        data,
        "rationale":   rationale,
    }


# ── per-trigger detectors ──────────────────────────────────────────────
# Each returns an optional record (None = doesn't fire).  Pure functions
# over a single listing.

def _detect_bargain(li: dict, cfg: dict) -> Optional[dict]:
    pct = li.get("price_vs_zone_pct")
    if pct is None or pct > cfg["bargain_pct_threshold"]:
        return None
    return _base_record(
        li, BARGAIN_ALERT,
        f"Precio por m² {abs(int(round(pct)))}% debajo de la mediana de la zona.",
        price_vs_zone_pct=pct,
        price_per_m2=li.get("price_per_m2"),
        zone_price_per_m2_median=li.get("price_vs_zone_median"),
    )


def _detect_top_rank(li: dict, cfg: dict) -> Optional[dict]:
    rank = li.get("rank")
    if rank is None or rank > cfg["top_rank_threshold"]:
        return None
    return _base_record(
        li, TOP_RANK,
        f"Entró al top {cfg['top_rank_threshold']} del catálogo.",
        rank=rank,
        rank_score=li.get("rank_score"),
    )


def _detect_price_drop(li: dict, _cfg: dict) -> Optional[dict]:
    if not li.get("is_repriced"):
        return None
    prev = li.get("previous_price")
    curr = li.get("price_usd")
    if prev is None or curr is None or prev <= curr:
        return None
    delta_pct = round((curr - prev) / prev * 100, 1)
    return _base_record(
        li, PRICE_DROP,
        f"Bajó {abs(int(round(delta_pct)))}% — de ${int(prev):,} a ${int(curr):,}.",
        previous_price=prev,
        current_price=curr,
        delta_pct=delta_pct,
    )


def _detect_fresh_and_hot(li: dict, cfg: dict) -> Optional[dict]:
    dom = li.get("days_listed")
    rank = li.get("rank")
    if dom is None or rank is None:
        return None
    if dom > cfg["fresh_days_threshold"]:
        return None
    if rank > cfg["fresh_rank_threshold"]:
        return None
    return _base_record(
        li, FRESH_AND_HOT,
        f"Recién llegado ({dom} d) y ya entró al top {cfg['fresh_rank_threshold']}.",
        days_listed=dom,
        rank=rank,
    )


def _detect_comparable_crash(li: dict, cfg: dict) -> Optional[dict]:
    ppm = li.get("price_per_m2")
    comp_count = li.get("zone_comp_count")
    zone_median = li.get("price_vs_zone_median")
    if ppm is None or comp_count is None or zone_median is None:
        return None
    if comp_count < cfg["comp_crash_min_comps"]:
        return None
    if zone_median <= 0:
        return None
    ratio = ppm / zone_median
    if ratio > cfg["comp_crash_ratio"]:
        return None
    return _base_record(
        li, COMPARABLE_CRASH,
        f"Precio por m² {int(round((1 - ratio) * 100))}% debajo de {comp_count} comparables.",
        ppm=ppm,
        zone_median_ppm=zone_median,
        ratio=round(ratio, 3),
        comp_count=comp_count,
    )


_PER_LISTING_DETECTORS = (
    _detect_bargain,
    _detect_top_rank,
    _detect_price_drop,
    _detect_fresh_and_hot,
    _detect_comparable_crash,
)


# ── zone-level detector ────────────────────────────────────────────────

def _detect_zone_domination(
    listings: list[dict], cfg: dict
) -> list[dict]:
    """Whole-catalogue scan: any zone with ≥N listings in the top M.
    Returns one record per dominating zone (not per listing)."""
    top_n = cfg["zone_dom_top_n"]
    threshold = cfg["zone_dom_count"]
    top_slice = [li for li in listings if (li.get("rank") or 9999) <= top_n]
    by_zone: Counter[str] = Counter()
    representatives: dict[str, dict] = {}
    for li in top_slice:
        z = li.get("zone")
        if not z:
            continue
        by_zone[z] += 1
        # Keep the highest-rank (lowest number) representative for the post.
        if z not in representatives or (li.get("rank") or 9999) < (representatives[z].get("rank") or 9999):
            representatives[z] = li
    records: list[dict] = []
    for zone, count in by_zone.items():
        if count < threshold:
            continue
        rep = representatives[zone]
        records.append(_base_record(
            rep, ZONE_DOMINATION,
            f"Zona {zone}: {count} listings entre los {top_n} mejor rankeados.",
            zone=zone,
            count_in_top_n=count,
            top_n=top_n,
        ))
    return records


# ── caps ───────────────────────────────────────────────────────────────

def _cap_key(trigger: str) -> str:
    """Return the config key holding the per-week cap for `trigger`."""
    return {
        BARGAIN_ALERT:    "bargain_cap_per_week",
        TOP_RANK:         "top_rank_cap_per_week",
        PRICE_DROP:       "price_drop_cap_per_week",
        FRESH_AND_HOT:    "fresh_cap_per_week",
        ZONE_DOMINATION:  "zone_dom_cap_per_week",
        COMPARABLE_CRASH: "comp_crash_cap_per_week",
    }[trigger]


def apply_caps(records: list[dict], cfg: dict) -> list[dict]:
    """Trim each trigger group to its per-week cap, ordered by priority
    then rank.  Different triggers have different caps so a flurry of
    bargains doesn't drown out the single fresh-and-hot we found."""
    by_trigger: dict[str, list[dict]] = {}
    for r in records:
        by_trigger.setdefault(r["trigger"], []).append(r)

    capped: list[dict] = []
    for trigger, group in by_trigger.items():
        # Sort within trigger: highest priority first (constant per trigger,
        # but ranking by rank handles intra-trigger order — lower rank wins).
        group.sort(key=lambda r: (-(r.get("priority") or 0), r.get("rank") or 9999))
        cap = cfg[_cap_key(trigger)]
        capped.extend(group[:cap])
    # Final sort: priority desc, rank asc — useful for the queue builder.
    capped.sort(key=lambda r: (-(r.get("priority") or 0), r.get("rank") or 9999))
    return capped


# ── orchestration ──────────────────────────────────────────────────────

def detect_all(
    listings: Iterable[dict],
    *,
    cfg: Optional[dict] = None,
    computed_at: Optional[str] = None,
    require_ig_gate: bool = True,
) -> dict:
    """Run all detectors over `listings` and apply caps.  Returns the
    full output payload.

    require_ig_gate=True (default): a listing must pass the IG photo gate
    before any per-listing trigger fires on it.  We never alert on a
    listing the publisher can't actually post.  Zone domination ignores
    this flag (it's a roundup of the *catalogue*, not the IG-ready slice).
    """
    cfg = cfg or _config_snapshot()
    computed_at = computed_at or datetime.now(timezone.utc).isoformat()
    listings_list = list(listings)

    pre_cap: list[dict] = []
    per_trigger_pre_cap: Counter[str] = Counter()

    for li in listings_list:
        if require_ig_gate and not passes_gate(li):
            continue
        for det in _PER_LISTING_DETECTORS:
            rec = det(li, cfg)
            if rec is None:
                continue
            rec["detected_at"] = computed_at
            pre_cap.append(rec)
            per_trigger_pre_cap[rec["trigger"]] += 1

    # Zone domination is independent of the IG gate (catalogue-wide).
    for rec in _detect_zone_domination(listings_list, cfg):
        rec["detected_at"] = computed_at
        pre_cap.append(rec)
        per_trigger_pre_cap[rec["trigger"]] += 1

    capped = apply_caps(pre_cap, cfg)
    post_cap_by_trigger = Counter(r["trigger"] for r in capped)

    return {
        "version":      1,
        "computed_at":  computed_at,
        "config":       cfg,
        "stats": {
            "scanned":                  len(listings_list),
            "candidates_per_trigger":   dict(per_trigger_pre_cap),
            "after_cap_per_trigger":    dict(post_cap_by_trigger),
            "total_after_cap":          len(capped),
        },
        "triggers":     capped,
    }


# ── I/O ────────────────────────────────────────────────────────────────

DEFAULT_RANKED = Path("web/data/ranked.json")
DEFAULT_OUTPUT = Path("web/data/ig_triggers.json")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect IG-worthy triggers on ranked.json."
    )
    parser.add_argument(
        "--ranked", type=Path, default=DEFAULT_RANKED,
        help=f"Input ranked.json (default {DEFAULT_RANKED}).",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output ig_triggers.json (default {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--skip-gate", action="store_true",
        help="Skip the IG photo gate filter (e.g. for diagnostics).",
    )
    args = parser.parse_args(argv)

    if not args.ranked.exists():
        print(f"[ig_triggers] ranked input missing: {args.ranked}", file=sys.stderr)
        return 2

    listings = json.loads(args.ranked.read_text(encoding="utf-8"))
    payload = detect_all(listings, require_ig_gate=not args.skip_gate)
    atomic_write_json(args.output, payload, indent=2)

    s = payload["stats"]
    print(
        f"[ig_triggers] scanned={s['scanned']} pre_cap={s['candidates_per_trigger']} "
        f"post_cap={s['after_cap_per_trigger']} total={s['total_after_cap']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
