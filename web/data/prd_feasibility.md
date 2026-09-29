# PRD WS2 — Feasibility Probe

_Generated: 2026-09-29T08:55:50.186339+00:00_  
_Catalog size: **1702 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1702 | 100.0% |
| `title` | 1702 | 100.0% |
| `first_seen_at` | 1702 | 100.0% |
| `scraped_at` | 1702 | 100.0% |
| `days_listed` | 1702 | 100.0% |
| `lat` | 1700 | 99.9% |
| `lng` | 1700 | 99.9% |
| `price_usd` | 1674 | 98.4% |
| `description>20` | 1629 | 95.7% |
| `department` | 1614 | 94.8% |
| `zone` | 1569 | 92.2% |
| `photo_urls>0` | 1150 | 67.6% |
| `photos_count>0` | 1150 | 67.6% |
| `zone_specific` | 1079 | 63.4% |
| `area_m2` | 977 | 57.4% |
| `price_per_m2` | 949 | 55.8% |
| `is_in_development` | 582 | 34.2% |
| `broker_name` | 461 | 27.1% |
| `broker_phone` | 425 | 25.0% |
| `broker_email` | 425 | 25.0% |
| `property_type!=land` | 289 | 17.0% |
| `is_beachfront` | 160 | 9.4% |
| `is_repriced` | 86 | 5.1% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 5 | 0.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 12 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 160 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 224 | 13.2% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 231 | 13.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 288 | 16.9% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 148 | 8.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 157 | 9.2% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 99 | 5.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 212 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 165 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 125 | 7.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 11 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 144 | 8.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 4.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 438 | 25.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 161 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 127 | 7.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 73 | 4.3% |
| <50 chars | 0 | 0.0% |
| 50-200 | 658 | 38.7% |
| 200-500 | 197 | 11.6% |
| >=500 | 774 | 45.5% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 425 | 925 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 160 | 138 | 0.0% |
| `csbr` | 271 | 99 | 0.0% |
| `essurf` | 34 | 0 | 100.0% |
| `goodlife` | 27 | 632 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 28 | 1469 | 0.0% |
| `realestate_au_sv` | 281 | 181 | 0.0% |
| `remax` | 254 | 1035 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 480 | 28.2% |
| ALL 3 of 3 utility signals (PRD spec) | 65 | 3.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.