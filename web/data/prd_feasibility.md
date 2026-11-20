# PRD WS2 — Feasibility Probe

_Generated: 2026-11-20T10:52:11.047449+00:00_  
_Catalog size: **1479 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1479 | 100.0% |
| `title` | 1479 | 100.0% |
| `first_seen_at` | 1479 | 100.0% |
| `scraped_at` | 1479 | 100.0% |
| `days_listed` | 1479 | 100.0% |
| `price_usd` | 1451 | 98.1% |
| `lat` | 1441 | 97.4% |
| `lng` | 1441 | 97.4% |
| `description>20` | 1405 | 95.0% |
| `department` | 1386 | 93.7% |
| `zone` | 1347 | 91.1% |
| `photo_urls>0` | 1239 | 83.8% |
| `photos_count>0` | 1239 | 83.8% |
| `area_m2` | 1179 | 79.7% |
| `price_per_m2` | 1151 | 77.8% |
| `zone_specific` | 930 | 62.9% |
| `is_in_development` | 542 | 36.6% |
| `broker_name` | 490 | 33.1% |
| `broker_phone` | 454 | 30.7% |
| `broker_email` | 454 | 30.7% |
| `property_type!=land` | 289 | 19.5% |
| `is_beachfront` | 160 | 10.8% |
| `is_repriced` | 66 | 4.5% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 9 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 157 | 10.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 231 | 15.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 259 | 17.5% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 310 | 21.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 157 | 10.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 157 | 10.6% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 126 | 8.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 228 | 15.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 174 | 11.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 127 | 8.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 18 | 1.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 144 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 1.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 70 | 4.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 445 | 30.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 34 | 2.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 182 | 12.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 140 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 74 | 5.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 417 | 28.2% |
| 200-500 | 153 | 10.3% |
| >=500 | 835 | 56.5% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 454 | 944 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 165 | 138 | 0.0% |
| `csbr` | 240 | 100 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 29 | 632 | 0.0% |
| `oceanside` | 25 | 1465 | 0.0% |
| `remax` | 317 | 1015 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 510 | 34.5% |
| ALL 3 of 3 utility signals (PRD spec) | 71 | 4.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.