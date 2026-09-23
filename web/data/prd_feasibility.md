# PRD WS2 — Feasibility Probe

_Generated: 2026-09-23T08:03:15.624786+00:00_  
_Catalog size: **1699 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1699 | 100.0% |
| `title` | 1699 | 100.0% |
| `first_seen_at` | 1699 | 100.0% |
| `scraped_at` | 1699 | 100.0% |
| `days_listed` | 1699 | 100.0% |
| `lat` | 1697 | 99.9% |
| `lng` | 1697 | 99.9% |
| `price_usd` | 1672 | 98.4% |
| `description>20` | 1627 | 95.8% |
| `department` | 1595 | 93.9% |
| `zone` | 1553 | 91.4% |
| `photo_urls>0` | 1156 | 68.0% |
| `photos_count>0` | 1156 | 68.0% |
| `zone_specific` | 1038 | 61.1% |
| `area_m2` | 975 | 57.4% |
| `price_per_m2` | 948 | 55.8% |
| `is_in_development` | 571 | 33.6% |
| `broker_name` | 457 | 26.9% |
| `broker_phone` | 422 | 24.8% |
| `broker_email` | 422 | 24.8% |
| `property_type!=land` | 290 | 17.1% |
| `is_beachfront` | 157 | 9.2% |
| `is_repriced` | 87 | 5.1% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 5 | 0.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 12 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 156 | 9.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 207 | 12.2% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 202 | 11.9% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 267 | 15.7% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 145 | 8.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 154 | 9.1% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 85 | 5.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 207 | 12.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 154 | 9.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 124 | 7.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 11 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 136 | 8.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 54 | 3.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 430 | 25.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 152 | 8.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 120 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 72 | 4.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 654 | 38.5% |
| 200-500 | 343 | 20.2% |
| >=500 | 630 | 37.1% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 422 | 919 | 0.0% |
| `citymax` | 35 | 0 | 100.0% |
| `citymax_sc` | 163 | 138 | 0.0% |
| `csbr` | 270 | 99 | 0.0% |
| `essurf` | 34 | 0 | 100.0% |
| `goodlife` | 28 | 632 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 28 | 1469 | 0.0% |
| `realestate_au_sv` | 273 | 181 | 0.0% |
| `remax` | 256 | 1030 | 0.0% |
| `vivolatam` | 153 | 486 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 446 | 26.3% |
| ALL 3 of 3 utility signals (PRD spec) | 59 | 3.5% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.