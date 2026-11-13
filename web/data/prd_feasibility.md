# PRD WS2 — Feasibility Probe

_Generated: 2026-09-26T07:58:29.560689+00:00_  
_Catalog size: **1701 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1701 | 100.0% |
| `title` | 1701 | 100.0% |
| `first_seen_at` | 1701 | 100.0% |
| `scraped_at` | 1701 | 100.0% |
| `days_listed` | 1701 | 100.0% |
| `lat` | 1699 | 99.9% |
| `lng` | 1699 | 99.9% |
| `price_usd` | 1673 | 98.4% |
| `description>20` | 1630 | 95.8% |
| `department` | 1606 | 94.4% |
| `zone` | 1563 | 91.9% |
| `photo_urls>0` | 1155 | 67.9% |
| `photos_count>0` | 1155 | 67.9% |
| `zone_specific` | 1058 | 62.2% |
| `area_m2` | 980 | 57.6% |
| `price_per_m2` | 952 | 56.0% |
| `is_in_development` | 580 | 34.1% |
| `broker_name` | 460 | 27.0% |
| `broker_phone` | 426 | 25.0% |
| `broker_email` | 426 | 25.0% |
| `property_type!=land` | 290 | 17.0% |
| `is_beachfront` | 160 | 9.4% |
| `is_repriced` | 88 | 5.2% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 5 | 0.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 12 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 160 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 224 | 13.2% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 231 | 13.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 288 | 16.9% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 149 | 8.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 157 | 9.2% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 99 | 5.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 213 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 165 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 125 | 7.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 11 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 143 | 8.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 4.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 440 | 25.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 161 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 129 | 7.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 71 | 4.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 654 | 38.4% |
| 200-500 | 197 | 11.6% |
| >=500 | 779 | 45.8% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 426 | 924 | 0.0% |
| `citymax` | 34 | 0 | 100.0% |
| `citymax_sc` | 161 | 138 | 0.0% |
| `csbr` | 270 | 99 | 0.0% |
| `essurf` | 34 | 0 | 100.0% |
| `goodlife` | 27 | 632 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 28 | 1469 | 0.0% |
| `realestate_au_sv` | 276 | 181 | 0.0% |
| `remax` | 259 | 1027 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 481 | 28.3% |
| ALL 3 of 3 utility signals (PRD spec) | 64 | 3.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.