# PRD WS2 — Feasibility Probe

_Generated: 2026-10-19T08:30:03.200122+00:00_  
_Catalog size: **1745 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1745 | 100.0% |
| `title` | 1745 | 100.0% |
| `first_seen_at` | 1745 | 100.0% |
| `scraped_at` | 1745 | 100.0% |
| `days_listed` | 1745 | 100.0% |
| `lat` | 1743 | 99.9% |
| `lng` | 1743 | 99.9% |
| `price_usd` | 1717 | 98.4% |
| `description>20` | 1706 | 97.8% |
| `department` | 1638 | 93.9% |
| `zone` | 1590 | 91.1% |
| `photo_urls>0` | 1152 | 66.0% |
| `photos_count>0` | 1152 | 66.0% |
| `zone_specific` | 1098 | 62.9% |
| `area_m2` | 985 | 56.4% |
| `price_per_m2` | 957 | 54.8% |
| `is_in_development` | 585 | 33.5% |
| `broker_name` | 471 | 27.0% |
| `broker_phone` | 435 | 24.9% |
| `broker_email` | 435 | 24.9% |
| `property_type!=land` | 297 | 17.0% |
| `is_beachfront` | 149 | 8.5% |
| `is_repriced` | 100 | 5.7% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 159 | 9.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 232 | 13.3% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 234 | 13.4% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 288 | 16.5% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 166 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 146 | 8.4% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 116 | 6.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 221 | 12.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 171 | 9.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 124 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 14 | 0.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 144 | 8.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 4.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 456 | 26.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 162 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 136 | 7.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 39 | 2.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 703 | 40.3% |
| 200-500 | 203 | 11.6% |
| >=500 | 800 | 45.8% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 435 | 920 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 166 | 138 | 0.0% |
| `csbr` | 280 | 100 | 0.0% |
| `goodlife` | 27 | 635 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 26 | 1467 | 0.0% |
| `realestate_au_sv` | 313 | 178 | 0.0% |
| `remax` | 276 | 1065 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 490 | 28.1% |
| ALL 3 of 3 utility signals (PRD spec) | 66 | 3.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.