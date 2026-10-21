# PRD WS2 — Feasibility Probe

_Generated: 2026-10-20T08:12:27.532730+00:00_  
_Catalog size: **1781 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1781 | 100.0% |
| `title` | 1781 | 100.0% |
| `first_seen_at` | 1781 | 100.0% |
| `scraped_at` | 1781 | 100.0% |
| `days_listed` | 1781 | 100.0% |
| `lat` | 1779 | 99.9% |
| `lng` | 1779 | 99.9% |
| `price_usd` | 1753 | 98.4% |
| `description>20` | 1707 | 95.8% |
| `department` | 1672 | 93.9% |
| `zone` | 1625 | 91.2% |
| `photo_urls>0` | 1189 | 66.8% |
| `photos_count>0` | 1189 | 66.8% |
| `zone_specific` | 1128 | 63.3% |
| `area_m2` | 1018 | 57.2% |
| `price_per_m2` | 990 | 55.6% |
| `is_in_development` | 590 | 33.1% |
| `broker_name` | 471 | 26.4% |
| `broker_phone` | 435 | 24.4% |
| `broker_email` | 435 | 24.4% |
| `property_type!=land` | 310 | 17.4% |
| `is_beachfront` | 161 | 9.0% |
| `is_repriced` | 99 | 5.6% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 161 | 9.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 233 | 13.1% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 235 | 13.2% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 289 | 16.2% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 166 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 158 | 8.9% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 116 | 6.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 222 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 170 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 126 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 14 | 0.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 144 | 8.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 456 | 25.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 162 | 9.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 137 | 7.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 74 | 4.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 703 | 39.5% |
| 200-500 | 203 | 11.4% |
| >=500 | 801 | 45.0% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 435 | 917 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 166 | 138 | 0.0% |
| `csbr` | 279 | 100 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 27 | 635 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 26 | 1467 | 0.0% |
| `realestate_au_sv` | 313 | 178 | 0.0% |
| `remax` | 278 | 1065 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 491 | 27.6% |
| ALL 3 of 3 utility signals (PRD spec) | 67 | 3.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.