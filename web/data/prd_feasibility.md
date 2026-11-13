# PRD WS2 — Feasibility Probe

_Generated: 2026-11-13T10:26:25.365997+00:00_  
_Catalog size: **1800 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1800 | 100.0% |
| `title` | 1800 | 100.0% |
| `first_seen_at` | 1800 | 100.0% |
| `scraped_at` | 1800 | 100.0% |
| `days_listed` | 1800 | 100.0% |
| `price_usd` | 1772 | 98.4% |
| `lat` | 1761 | 97.8% |
| `lng` | 1761 | 97.8% |
| `description>20` | 1743 | 96.8% |
| `department` | 1710 | 95.0% |
| `zone` | 1656 | 92.0% |
| `photo_urls>0` | 1223 | 67.9% |
| `photos_count>0` | 1223 | 67.9% |
| `area_m2` | 1159 | 64.4% |
| `price_per_m2` | 1131 | 62.8% |
| `zone_specific` | 1118 | 62.1% |
| `is_in_development` | 633 | 35.2% |
| `broker_name` | 489 | 27.2% |
| `broker_phone` | 453 | 25.2% |
| `broker_email` | 453 | 25.2% |
| `property_type!=land` | 298 | 16.6% |
| `is_beachfront` | 155 | 8.6% |
| `is_repriced` | 102 | 5.7% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 9 | 0.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 157 | 8.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 246 | 13.7% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 262 | 14.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 320 | 17.8% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 170 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 152 | 8.4% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 126 | 7.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 227 | 12.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 174 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 128 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 18 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 145 | 8.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 71 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 462 | 25.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 34 | 1.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 181 | 10.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 139 | 7.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 57 | 3.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 691 | 38.4% |
| 200-500 | 219 | 12.2% |
| >=500 | 833 | 46.3% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 453 | 942 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 166 | 138 | 0.0% |
| `csbr` | 235 | 100 | 0.0% |
| `essurf` | 18 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 25 | 1465 | 0.0% |
| `realestate_au_sv` | 342 | 178 | 0.0% |
| `remax` | 319 | 1006 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 534 | 29.7% |
| ALL 3 of 3 utility signals (PRD spec) | 72 | 4.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.