# PRD WS2 — Feasibility Probe

_Generated: 2026-10-06T09:29:26.980837+00:00_  
_Catalog size: **1686 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1686 | 100.0% |
| `title` | 1686 | 100.0% |
| `first_seen_at` | 1686 | 100.0% |
| `scraped_at` | 1686 | 100.0% |
| `days_listed` | 1686 | 100.0% |
| `lat` | 1684 | 99.9% |
| `lng` | 1684 | 99.9% |
| `price_usd` | 1658 | 98.3% |
| `description>20` | 1647 | 97.7% |
| `department` | 1597 | 94.7% |
| `zone` | 1553 | 92.1% |
| `photo_urls>0` | 1126 | 66.8% |
| `photos_count>0` | 1126 | 66.8% |
| `zone_specific` | 1068 | 63.3% |
| `area_m2` | 953 | 56.5% |
| `price_per_m2` | 925 | 54.9% |
| `is_in_development` | 576 | 34.2% |
| `broker_name` | 463 | 27.5% |
| `broker_phone` | 427 | 25.3% |
| `broker_email` | 427 | 25.3% |
| `property_type!=land` | 289 | 17.1% |
| `is_beachfront` | 147 | 8.7% |
| `is_repriced` | 94 | 5.6% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 12 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 158 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 225 | 13.3% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 231 | 13.7% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 287 | 17.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 149 | 8.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 144 | 8.5% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 98 | 5.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 219 | 13.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 170 | 10.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 122 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 11 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 145 | 8.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 68 | 4.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 445 | 26.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 161 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 138 | 8.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 39 | 2.3% |
| <50 chars | 0 | 0.0% |
| 50-200 | 672 | 39.9% |
| 200-500 | 193 | 11.4% |
| >=500 | 782 | 46.4% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 427 | 925 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 164 | 137 | 0.0% |
| `csbr` | 272 | 99 | 0.0% |
| `goodlife` | 26 | 624 | 0.0% |
| `nexo` | 9 | 348 | 0.0% |
| `oceanside` | 27 | 1468 | 0.0% |
| `realestate_au_sv` | 288 | 179 | 0.0% |
| `remax` | 260 | 1044 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 483 | 28.6% |
| ALL 3 of 3 utility signals (PRD spec) | 65 | 3.9% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.