# PRD WS2 — Feasibility Probe

_Generated: 2026-11-02T10:07:15.436194+00:00_  
_Catalog size: **1813 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1813 | 100.0% |
| `title` | 1813 | 100.0% |
| `first_seen_at` | 1813 | 100.0% |
| `scraped_at` | 1813 | 100.0% |
| `days_listed` | 1813 | 100.0% |
| `lat` | 1810 | 99.8% |
| `lng` | 1810 | 99.8% |
| `price_usd` | 1785 | 98.5% |
| `description>20` | 1738 | 95.9% |
| `department` | 1724 | 95.1% |
| `zone` | 1671 | 92.2% |
| `photo_urls>0` | 1232 | 68.0% |
| `photos_count>0` | 1232 | 68.0% |
| `zone_specific` | 1131 | 62.4% |
| `area_m2` | 1038 | 57.3% |
| `price_per_m2` | 1010 | 55.7% |
| `is_in_development` | 626 | 34.5% |
| `broker_name` | 486 | 26.8% |
| `broker_phone` | 449 | 24.8% |
| `broker_email` | 449 | 24.8% |
| `property_type!=land` | 300 | 16.5% |
| `is_beachfront` | 164 | 9.0% |
| `is_repriced` | 103 | 5.7% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 156 | 8.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 239 | 13.2% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 262 | 14.5% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 313 | 17.3% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 169 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 161 | 8.9% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 121 | 6.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 222 | 12.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 170 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 128 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 149 | 8.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 70 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 454 | 25.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 32 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 171 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 140 | 7.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 75 | 4.1% |
| <50 chars | 0 | 0.0% |
| 50-200 | 691 | 38.1% |
| 200-500 | 224 | 12.4% |
| >=500 | 823 | 45.4% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 449 | 938 | 0.0% |
| `citymax` | 37 | 0 | 100.0% |
| `citymax_sc` | 167 | 138 | 0.0% |
| `csbr` | 231 | 101 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 26 | 1467 | 0.0% |
| `realestate_au_sv` | 350 | 179 | 0.0% |
| `remax` | 312 | 996 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 524 | 28.9% |
| ALL 3 of 3 utility signals (PRD spec) | 73 | 4.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.