# PRD WS2 — Feasibility Probe

_Generated: 2026-10-28T08:56:45.091475+00:00_  
_Catalog size: **1786 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1786 | 100.0% |
| `title` | 1786 | 100.0% |
| `first_seen_at` | 1786 | 100.0% |
| `scraped_at` | 1786 | 100.0% |
| `days_listed` | 1786 | 100.0% |
| `lat` | 1783 | 99.8% |
| `lng` | 1783 | 99.8% |
| `price_usd` | 1758 | 98.4% |
| `description>20` | 1711 | 95.8% |
| `department` | 1679 | 94.0% |
| `zone` | 1627 | 91.1% |
| `photo_urls>0` | 1194 | 66.9% |
| `photos_count>0` | 1194 | 66.9% |
| `zone_specific` | 1130 | 63.3% |
| `area_m2` | 1022 | 57.2% |
| `price_per_m2` | 994 | 55.7% |
| `is_in_development` | 590 | 33.0% |
| `broker_name` | 483 | 27.0% |
| `broker_phone` | 446 | 25.0% |
| `broker_email` | 446 | 25.0% |
| `property_type!=land` | 303 | 17.0% |
| `is_beachfront` | 162 | 9.1% |
| `is_repriced` | 101 | 5.7% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 10 | 0.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 160 | 9.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 242 | 13.5% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 240 | 13.4% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 292 | 16.3% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 167 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 159 | 8.9% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 120 | 6.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 223 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 172 | 9.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 126 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 145 | 8.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 69 | 3.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 450 | 25.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 32 | 1.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 168 | 9.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 139 | 7.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 75 | 4.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 706 | 39.5% |
| 200-500 | 191 | 10.7% |
| >=500 | 814 | 45.6% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 446 | 934 | 0.0% |
| `citymax` | 37 | 0 | 100.0% |
| `citymax_sc` | 167 | 138 | 0.0% |
| `csbr` | 278 | 100 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 26 | 1467 | 0.0% |
| `realestate_au_sv` | 314 | 177 | 0.0% |
| `remax` | 277 | 1060 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 498 | 27.9% |
| ALL 3 of 3 utility signals (PRD spec) | 73 | 4.1% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.