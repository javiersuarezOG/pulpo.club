# PRD WS2 — Feasibility Probe

_Generated: 2026-10-24T08:06:28.583011+00:00_  
_Catalog size: **1779 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1779 | 100.0% |
| `title` | 1779 | 100.0% |
| `first_seen_at` | 1779 | 100.0% |
| `scraped_at` | 1779 | 100.0% |
| `days_listed` | 1779 | 100.0% |
| `lat` | 1777 | 99.9% |
| `lng` | 1777 | 99.9% |
| `price_usd` | 1751 | 98.4% |
| `description>20` | 1704 | 95.8% |
| `department` | 1672 | 94.0% |
| `zone` | 1623 | 91.2% |
| `photo_urls>0` | 1187 | 66.7% |
| `photos_count>0` | 1187 | 66.7% |
| `zone_specific` | 1127 | 63.4% |
| `area_m2` | 1017 | 57.2% |
| `price_per_m2` | 989 | 55.6% |
| `is_in_development` | 587 | 33.0% |
| `broker_name` | 481 | 27.0% |
| `broker_phone` | 444 | 25.0% |
| `broker_email` | 444 | 25.0% |
| `property_type!=land` | 302 | 17.0% |
| `is_beachfront` | 161 | 9.1% |
| `is_repriced` | 106 | 6.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 160 | 9.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 239 | 13.4% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 237 | 13.3% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 288 | 16.2% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 165 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 158 | 8.9% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 117 | 6.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 222 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 170 | 9.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 126 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 144 | 8.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 18 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 450 | 25.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 31 | 1.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 164 | 9.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 136 | 7.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 75 | 4.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 701 | 39.4% |
| 200-500 | 194 | 10.9% |
| >=500 | 809 | 45.5% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 444 | 929 | 0.0% |
| `citymax` | 37 | 0 | 100.0% |
| `citymax_sc` | 165 | 138 | 0.0% |
| `csbr` | 278 | 100 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 27 | 1468 | 0.0% |
| `realestate_au_sv` | 314 | 178 | 0.0% |
| `remax` | 274 | 1063 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 28 | 2211 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 490 | 27.5% |
| ALL 3 of 3 utility signals (PRD spec) | 71 | 4.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.