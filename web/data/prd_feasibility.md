# PRD WS2 — Feasibility Probe

_Generated: 2026-09-25T08:01:35.699614+00:00_  
_Catalog size: **1700 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1700 | 100.0% |
| `title` | 1700 | 100.0% |
| `first_seen_at` | 1700 | 100.0% |
| `scraped_at` | 1700 | 100.0% |
| `days_listed` | 1700 | 100.0% |
| `lat` | 1698 | 99.9% |
| `lng` | 1698 | 99.9% |
| `price_usd` | 1673 | 98.4% |
| `description>20` | 1628 | 95.8% |
| `department` | 1605 | 94.4% |
| `zone` | 1563 | 91.9% |
| `photo_urls>0` | 1155 | 67.9% |
| `photos_count>0` | 1155 | 67.9% |
| `zone_specific` | 1057 | 62.2% |
| `area_m2` | 978 | 57.5% |
| `price_per_m2` | 951 | 55.9% |
| `is_in_development` | 577 | 33.9% |
| `broker_name` | 459 | 27.0% |
| `broker_phone` | 424 | 24.9% |
| `broker_email` | 424 | 24.9% |
| `property_type!=land` | 289 | 17.0% |
| `is_beachfront` | 160 | 9.4% |
| `is_repriced` | 88 | 5.2% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 5 | 0.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 12 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 160 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 221 | 13.0% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 231 | 13.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 287 | 16.9% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 149 | 8.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 157 | 9.2% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 98 | 5.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 212 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 164 | 9.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 125 | 7.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 11 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 143 | 8.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 4.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 439 | 25.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 159 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 129 | 7.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 72 | 4.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 655 | 38.5% |
| 200-500 | 197 | 11.6% |
| >=500 | 776 | 45.6% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 424 | 921 | 0.0% |
| `citymax` | 35 | 0 | 100.0% |
| `citymax_sc` | 163 | 138 | 0.0% |
| `csbr` | 270 | 99 | 0.0% |
| `essurf` | 34 | 0 | 100.0% |
| `goodlife` | 27 | 632 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 28 | 1469 | 0.0% |
| `realestate_au_sv` | 275 | 181 | 0.0% |
| `remax` | 258 | 1027 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 478 | 28.1% |
| ALL 3 of 3 utility signals (PRD spec) | 64 | 3.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.