# PRD WS2 — Feasibility Probe

_Generated: 2026-11-15T09:56:45.560672+00:00_  
_Catalog size: **1828 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 1828 | 100.0% |
| `title` | 1828 | 100.0% |
| `first_seen_at` | 1828 | 100.0% |
| `scraped_at` | 1828 | 100.0% |
| `days_listed` | 1828 | 100.0% |
| `price_usd` | 1800 | 98.5% |
| `lat` | 1789 | 97.9% |
| `lng` | 1789 | 97.9% |
| `description>20` | 1754 | 96.0% |
| `department` | 1736 | 95.0% |
| `zone` | 1681 | 92.0% |
| `photo_urls>0` | 1243 | 68.0% |
| `photos_count>0` | 1243 | 68.0% |
| `area_m2` | 1178 | 64.4% |
| `price_per_m2` | 1150 | 62.9% |
| `zone_specific` | 1131 | 61.9% |
| `is_in_development` | 639 | 35.0% |
| `broker_name` | 490 | 26.8% |
| `broker_phone` | 454 | 24.8% |
| `broker_email` | 454 | 24.8% |
| `property_type!=land` | 304 | 16.6% |
| `is_beachfront` | 160 | 8.8% |
| `is_repriced` | 102 | 5.6% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `is_agricultural` | 4 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_mountain_view` | 9 | 0.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 156 | 8.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 247 | 13.5% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 264 | 14.4% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 321 | 17.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 170 | 9.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 157 | 8.6% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 127 | 6.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 228 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 173 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 127 | 6.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 18 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 143 | 7.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 16 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 70 | 3.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 465 | 25.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 34 | 1.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 182 | 10.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 138 | 7.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 74 | 4.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 697 | 38.1% |
| 200-500 | 221 | 12.1% |
| >=500 | 836 | 45.7% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 454 | 943 | 0.0% |
| `citymax` | 36 | 0 | 100.0% |
| `citymax_sc` | 166 | 138 | 0.0% |
| `csbr` | 236 | 100 | 0.0% |
| `essurf` | 35 | 0 | 100.0% |
| `goodlife` | 28 | 634 | 0.0% |
| `oceanside` | 25 | 1465 | 0.0% |
| `realestate_au_sv` | 349 | 178 | 0.0% |
| `remax` | 321 | 1006 | 0.0% |
| `vivolatam` | 149 | 1256 | 2.0% |
| `xitios` | 29 | 2256 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 538 | 29.4% |
| ALL 3 of 3 utility signals (PRD spec) | 72 | 3.9% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.