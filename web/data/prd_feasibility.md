# PRD WS2 — Feasibility Probe

_Generated: 2026-10-08T09:21:20.319622+00:00_  
_Catalog size: **1693 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1693 | 100.0% |
| `title` | 1693 | 100.0% |
| `first_seen_at` | 1693 | 100.0% |
| `scraped_at` | 1693 | 100.0% |
| `days_listed` | 1693 | 100.0% |
| `lat` | 1691 | 99.9% |
| `lng` | 1691 | 99.9% |
| `price_usd` | 1665 | 98.3% |
| `description>20` | 1654 | 97.7% |
| `department` | 1604 | 94.7% |
| `zone` | 1560 | 92.1% |
| `photo_urls>0` | 1131 | 66.8% |
| `photos_count>0` | 1131 | 66.8% |
| `zone_specific` | 1077 | 63.6% |
| `area_m2` | 953 | 56.3% |
| `price_per_m2` | 925 | 54.6% |
| `is_in_development` | 577 | 34.1% |
| `broker_name` | 465 | 27.5% |
| `broker_phone` | 429 | 25.3% |
| `broker_email` | 429 | 25.3% |
| `property_type!=land` | 291 | 17.2% |
| `is_beachfront` | 147 | 8.7% |
| `is_repriced` | 95 | 5.6% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 158 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 225 | 13.3% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 231 | 13.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 289 | 17.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 150 | 8.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 144 | 8.5% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 97 | 5.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 221 | 13.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 171 | 10.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 122 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 12 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 144 | 8.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 4.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 446 | 26.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 161 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 136 | 8.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 39 | 2.3% |
| <50 chars | 0 | 0.0% |
| 50-200 | 678 | 40.0% |
| 200-500 | 196 | 11.6% |
| >=500 | 780 | 46.1% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 429 | 923 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 169 | 137 | 0.0% |
| `csbr` | 273 | 99 | 0.0% |
| `goodlife` | 26 | 624 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 27 | 1468 | 0.0% |
| `realestate_au_sv` | 289 | 179 | 0.0% |
| `remax` | 258 | 1039 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 483 | 28.5% |
| ALL 3 of 3 utility signals (PRD spec) | 65 | 3.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.