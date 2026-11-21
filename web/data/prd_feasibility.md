# PRD WS2 — Feasibility Probe

_Generated: 2026-11-14T09:49:09.639026+00:00_  
_Catalog size: **1822 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1822 | 100.0% |
| `title` | 1822 | 100.0% |
| `first_seen_at` | 1822 | 100.0% |
| `scraped_at` | 1822 | 100.0% |
| `days_listed` | 1822 | 100.0% |
| `price_usd` | 1794 | 98.5% |
| `lat` | 1782 | 97.8% |
| `lng` | 1782 | 97.8% |
| `description>20` | 1749 | 96.0% |
| `department` | 1730 | 95.0% |
| `zone` | 1675 | 91.9% |
| `photo_urls>0` | 1243 | 68.2% |
| `photos_count>0` | 1243 | 68.2% |
| `area_m2` | 1179 | 64.7% |
| `price_per_m2` | 1151 | 63.2% |
| `zone_specific` | 1130 | 62.0% |
| `is_in_development` | 638 | 35.0% |
| `broker_name` | 489 | 26.8% |
| `broker_phone` | 454 | 24.9% |
| `broker_email` | 454 | 24.9% |
| `property_type!=land` | 303 | 16.6% |
| `is_beachfront` | 160 | 8.8% |
| `is_repriced` | 101 | 5.5% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 9 | 0.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 155 | 8.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 247 | 13.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 265 | 14.5% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 320 | 17.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 170 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 157 | 8.6% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 127 | 7.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 228 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 174 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 127 | 7.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 18 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 143 | 7.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 71 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 465 | 25.5% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 34 | 1.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 182 | 10.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 138 | 7.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 73 | 4.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 692 | 38.0% |
| 200-500 | 220 | 12.1% |
| >=500 | 837 | 45.9% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 454 | 943 | 0.0% |
| `citymax` | 35 | 0 | 100.0% |
| `citymax_sc` | 166 | 138 | 0.0% |
| `csbr` | 236 | 100 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 25 | 1465 | 0.0% |
| `realestate_au_sv` | 343 | 178 | 0.0% |
| `remax` | 322 | 1006 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 538 | 29.5% |
| ALL 3 of 3 utility signals (PRD spec) | 72 | 4.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.