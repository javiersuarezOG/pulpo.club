# PRD WS2 — Feasibility Probe

_Generated: 2026-10-30T09:21:06.678799+00:00_  
_Catalog size: **1762 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1762 | 100.0% |
| `title` | 1762 | 100.0% |
| `first_seen_at` | 1762 | 100.0% |
| `scraped_at` | 1762 | 100.0% |
| `days_listed` | 1762 | 100.0% |
| `lat` | 1759 | 99.8% |
| `lng` | 1759 | 99.8% |
| `price_usd` | 1734 | 98.4% |
| `description>20` | 1720 | 97.6% |
| `department` | 1656 | 94.0% |
| `zone` | 1605 | 91.1% |
| `photo_urls>0` | 1167 | 66.2% |
| `photos_count>0` | 1167 | 66.2% |
| `zone_specific` | 1109 | 62.9% |
| `area_m2` | 1000 | 56.8% |
| `price_per_m2` | 972 | 55.2% |
| `is_in_development` | 590 | 33.5% |
| `broker_name` | 486 | 27.6% |
| `broker_phone` | 449 | 25.5% |
| `broker_email` | 449 | 25.5% |
| `property_type!=land` | 291 | 16.5% |
| `is_beachfront` | 153 | 8.7% |
| `is_repriced` | 104 | 5.9% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 157 | 8.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 243 | 13.8% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 240 | 13.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 291 | 16.5% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 168 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 150 | 8.5% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 120 | 6.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 223 | 12.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 171 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 128 | 7.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 147 | 8.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 453 | 25.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 32 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 171 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 139 | 7.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 42 | 2.4% |
| <50 chars | 0 | 0.0% |
| 50-200 | 709 | 40.2% |
| 200-500 | 192 | 10.9% |
| >=500 | 819 | 46.5% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 449 | 938 | 0.0% |
| `citymax` | 37 | 0 | 100.0% |
| `citymax_sc` | 167 | 138 | 0.0% |
| `csbr` | 278 | 101 | 0.0% |
| `essurf` | 2 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 25 | 1465 | 0.0% |
| `realestate_au_sv` | 317 | 177 | 0.0% |
| `remax` | 281 | 1052 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 499 | 28.3% |
| ALL 3 of 3 utility signals (PRD spec) | 73 | 4.1% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.