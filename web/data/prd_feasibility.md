# PRD WS2 — Feasibility Probe

_Generated: 2026-10-12T09:43:39.653530+00:00_  
_Catalog size: **1707 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1707 | 100.0% |
| `title` | 1707 | 100.0% |
| `first_seen_at` | 1707 | 100.0% |
| `scraped_at` | 1707 | 100.0% |
| `days_listed` | 1707 | 100.0% |
| `lat` | 1705 | 99.9% |
| `lng` | 1705 | 99.9% |
| `price_usd` | 1679 | 98.4% |
| `description>20` | 1668 | 97.7% |
| `department` | 1617 | 94.7% |
| `zone` | 1571 | 92.0% |
| `photo_urls>0` | 1135 | 66.5% |
| `photos_count>0` | 1135 | 66.5% |
| `zone_specific` | 1081 | 63.3% |
| `area_m2` | 967 | 56.6% |
| `price_per_m2` | 939 | 55.0% |
| `is_in_development` | 583 | 34.2% |
| `broker_name` | 467 | 27.4% |
| `broker_phone` | 431 | 25.2% |
| `broker_email` | 431 | 25.2% |
| `property_type!=land` | 295 | 17.3% |
| `is_beachfront` | 148 | 8.7% |
| `is_repriced` | 97 | 5.7% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 158 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 229 | 13.4% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 233 | 13.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 290 | 17.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 152 | 8.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 145 | 8.5% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 98 | 5.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 223 | 13.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 172 | 10.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 123 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 14 | 0.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 145 | 8.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 4.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 445 | 26.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 164 | 9.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 136 | 8.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 39 | 2.3% |
| <50 chars | 0 | 0.0% |
| 50-200 | 685 | 40.1% |
| 200-500 | 200 | 11.7% |
| >=500 | 783 | 45.9% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 431 | 925 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 168 | 138 | 0.0% |
| `csbr` | 280 | 100 | 0.0% |
| `goodlife` | 26 | 624 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 27 | 1468 | 0.0% |
| `realestate_au_sv` | 292 | 178 | 0.0% |
| `remax` | 261 | 1037 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 488 | 28.6% |
| ALL 3 of 3 utility signals (PRD spec) | 66 | 3.9% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.