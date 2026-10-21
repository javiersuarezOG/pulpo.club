# PRD WS2 — Feasibility Probe

_Generated: 2026-10-05T09:19:28.356861+00:00_  
_Catalog size: **1678 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1678 | 100.0% |
| `title` | 1678 | 100.0% |
| `first_seen_at` | 1678 | 100.0% |
| `scraped_at` | 1678 | 100.0% |
| `days_listed` | 1678 | 100.0% |
| `lat` | 1676 | 99.9% |
| `lng` | 1676 | 99.9% |
| `price_usd` | 1651 | 98.4% |
| `description>20` | 1639 | 97.7% |
| `department` | 1589 | 94.7% |
| `zone` | 1546 | 92.1% |
| `photo_urls>0` | 1127 | 67.2% |
| `photos_count>0` | 1127 | 67.2% |
| `zone_specific` | 1059 | 63.1% |
| `area_m2` | 952 | 56.7% |
| `price_per_m2` | 925 | 55.1% |
| `is_in_development` | 576 | 34.3% |
| `broker_name` | 460 | 27.4% |
| `broker_phone` | 424 | 25.3% |
| `broker_email` | 424 | 25.3% |
| `property_type!=land` | 281 | 16.7% |
| `is_beachfront` | 146 | 8.7% |
| `is_repriced` | 93 | 5.5% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 12 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 158 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 225 | 13.4% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 231 | 13.8% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 288 | 17.2% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 148 | 8.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 143 | 8.5% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 98 | 5.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 220 | 13.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 169 | 10.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 121 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 11 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 144 | 8.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 68 | 4.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 447 | 26.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 160 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 137 | 8.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 39 | 2.3% |
| <50 chars | 0 | 0.0% |
| 50-200 | 665 | 39.6% |
| 200-500 | 192 | 11.4% |
| >=500 | 782 | 46.6% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 424 | 924 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 166 | 138 | 0.0% |
| `csbr` | 272 | 99 | 0.0% |
| `goodlife` | 26 | 624 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 28 | 1469 | 0.0% |
| `realestate_au_sv` | 279 | 180 | 0.0% |
| `remax` | 261 | 1049 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 484 | 28.8% |
| ALL 3 of 3 utility signals (PRD spec) | 64 | 3.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.