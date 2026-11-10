# PRD WS2 — Feasibility Probe

_Generated: 2026-11-10T10:42:12.843789+00:00_  
_Catalog size: **1805 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1805 | 100.0% |
| `title` | 1805 | 100.0% |
| `first_seen_at` | 1805 | 100.0% |
| `scraped_at` | 1805 | 100.0% |
| `days_listed` | 1805 | 100.0% |
| `lat` | 1802 | 99.8% |
| `lng` | 1802 | 99.8% |
| `price_usd` | 1777 | 98.4% |
| `description>20` | 1732 | 96.0% |
| `department` | 1716 | 95.1% |
| `zone` | 1664 | 92.2% |
| `photo_urls>0` | 1232 | 68.3% |
| `photos_count>0` | 1232 | 68.3% |
| `area_m2` | 1164 | 64.5% |
| `price_per_m2` | 1136 | 62.9% |
| `zone_specific` | 1133 | 62.8% |
| `is_in_development` | 635 | 35.2% |
| `broker_name` | 486 | 26.9% |
| `broker_phone` | 451 | 25.0% |
| `broker_email` | 451 | 25.0% |
| `property_type!=land` | 302 | 16.7% |
| `is_beachfront` | 162 | 9.0% |
| `is_repriced` | 107 | 5.9% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 157 | 8.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 240 | 13.3% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 263 | 14.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 317 | 17.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 168 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 159 | 8.8% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 121 | 6.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 225 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 172 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 127 | 7.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 17 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 145 | 8.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 71 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 458 | 25.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 32 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 172 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 140 | 7.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 73 | 4.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 687 | 38.1% |
| 200-500 | 221 | 12.2% |
| >=500 | 824 | 45.7% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 451 | 937 | 0.0% |
| `citymax` | 35 | 0 | 100.0% |
| `citymax_sc` | 167 | 138 | 0.0% |
| `csbr` | 235 | 100 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 25 | 1465 | 0.0% |
| `realestate_au_sv` | 338 | 179 | 0.0% |
| `remax` | 313 | 1000 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 529 | 29.3% |
| ALL 3 of 3 utility signals (PRD spec) | 72 | 4.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.