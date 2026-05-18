# PRD WS2 — Feasibility Probe

_Generated: 2026-05-18T23:37:36.797991+00:00_  
_Catalog size: **920 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 920 | 100.0% |
| `title` | 920 | 100.0% |
| `description>20` | 920 | 100.0% |
| `first_seen_at` | 920 | 100.0% |
| `scraped_at` | 920 | 100.0% |
| `days_listed` | 920 | 100.0% |
| `lat` | 918 | 99.8% |
| `lng` | 918 | 99.8% |
| `department` | 898 | 97.6% |
| `price_usd` | 895 | 97.3% |
| `area_m2` | 894 | 97.2% |
| `price_per_m2` | 869 | 94.5% |
| `zone` | 869 | 94.5% |
| `photo_urls>0` | 842 | 91.5% |
| `photos_count>0` | 842 | 91.5% |
| `zone_specific` | 590 | 64.1% |
| `broker_name` | 516 | 56.1% |
| `broker_phone` | 512 | 55.7% |
| `broker_email` | 512 | 55.7% |
| `is_in_development` | 377 | 41.0% |
| `is_beachfront` | 121 | 13.2% |
| `property_type!=land` | 87 | 9.5% |
| `is_repriced` | 7 | 0.8% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 15 | 1.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 102 | 11.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 204 | 22.2% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 277 | 30.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 306 | 33.3% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 144 | 15.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 199 | 21.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront` | 119 | 12.9% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 90 | 9.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 241 | 26.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 183 | 19.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 108 | 11.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 114 | 12.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 18 | 2.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 34 | 3.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 2 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 339 | 36.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 41 | 4.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 121 | 13.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 135 | 14.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 71 | 7.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 24 | 2.6% |
| 200-500 | 157 | 17.1% |
| >=500 | 739 | 80.3% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 497 | 946 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `encuentra24` | 4 | 1140 | 0.0% |
| `goodlife` | 39 | 642 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 23 | 1463 | 0.0% |
| `remax` | 333 | 965 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 468 | 50.9% |
| ALL 3 of 3 utility signals (PRD spec) | 75 | 8.2% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.