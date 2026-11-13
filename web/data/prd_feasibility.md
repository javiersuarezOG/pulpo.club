# PRD WS2 — Feasibility Probe

_Generated: 2026-11-01T09:52:46.195305+00:00_  
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
| `lat` | 1778 | 99.8% |
| `lng` | 1778 | 99.8% |
| `price_usd` | 1753 | 98.4% |
| `description>20` | 1706 | 95.8% |
| `department` | 1692 | 95.0% |
| `zone` | 1639 | 92.0% |
| `photo_urls>0` | 1231 | 69.1% |
| `photos_count>0` | 1231 | 69.1% |
| `zone_specific` | 1128 | 63.3% |
| `area_m2` | 1037 | 58.2% |
| `price_per_m2` | 1009 | 56.7% |
| `is_in_development` | 598 | 33.6% |
| `broker_name` | 486 | 27.3% |
| `broker_phone` | 449 | 25.2% |
| `broker_email` | 449 | 25.2% |
| `property_type!=land` | 300 | 16.8% |
| `is_beachfront` | 164 | 9.2% |
| `is_repriced` | 103 | 5.8% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 155 | 8.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 239 | 13.4% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 262 | 14.7% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 313 | 17.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 167 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 161 | 9.0% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 121 | 6.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 222 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 170 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 128 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 148 | 8.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 70 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 454 | 25.5% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 32 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 171 | 9.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 140 | 7.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 75 | 4.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 662 | 37.2% |
| 200-500 | 222 | 12.5% |
| >=500 | 822 | 46.2% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 449 | 938 | 0.0% |
| `citymax` | 37 | 0 | 100.0% |
| `citymax_sc` | 167 | 138 | 0.0% |
| `csbr` | 231 | 101 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 25 | 1465 | 0.0% |
| `realestate_au_sv` | 319 | 177 | 0.0% |
| `remax` | 312 | 996 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 524 | 29.4% |
| ALL 3 of 3 utility signals (PRD spec) | 73 | 4.1% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.