# PRD WS2 — Feasibility Probe

_Generated: 2026-10-14T08:06:34.688463+00:00_  
_Catalog size: **1723 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1723 | 100.0% |
| `title` | 1723 | 100.0% |
| `first_seen_at` | 1723 | 100.0% |
| `scraped_at` | 1723 | 100.0% |
| `days_listed` | 1723 | 100.0% |
| `lat` | 1721 | 99.9% |
| `lng` | 1721 | 99.9% |
| `price_usd` | 1695 | 98.4% |
| `description>20` | 1684 | 97.7% |
| `department` | 1618 | 93.9% |
| `zone` | 1571 | 91.2% |
| `photo_urls>0` | 1148 | 66.6% |
| `photos_count>0` | 1148 | 66.6% |
| `zone_specific` | 1082 | 62.8% |
| `area_m2` | 982 | 57.0% |
| `price_per_m2` | 954 | 55.4% |
| `is_in_development` | 581 | 33.7% |
| `broker_name` | 470 | 27.3% |
| `broker_phone` | 434 | 25.2% |
| `broker_email` | 434 | 25.2% |
| `property_type!=land` | 298 | 17.3% |
| `is_beachfront` | 149 | 8.6% |
| `is_repriced` | 96 | 5.6% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 159 | 9.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 229 | 13.3% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 231 | 13.4% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 287 | 16.7% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 166 | 9.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 146 | 8.5% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 110 | 6.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 219 | 12.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 172 | 10.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 124 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 14 | 0.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 145 | 8.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 70 | 4.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 455 | 26.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 162 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 135 | 7.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 39 | 2.3% |
| <50 chars | 0 | 0.0% |
| 50-200 | 688 | 39.9% |
| 200-500 | 202 | 11.7% |
| >=500 | 794 | 46.1% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 434 | 921 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 167 | 138 | 0.0% |
| `csbr` | 281 | 100 | 0.0% |
| `goodlife` | 26 | 624 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 27 | 1468 | 0.0% |
| `realestate_au_sv` | 294 | 178 | 0.0% |
| `remax` | 272 | 1060 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 487 | 28.3% |
| ALL 3 of 3 utility signals (PRD spec) | 65 | 3.8% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.