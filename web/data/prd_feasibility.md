# PRD WS2 — Feasibility Probe

_Generated: 2026-05-20T07:35:27.252423+00:00_  
_Catalog size: **923 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 923 | 100.0% |
| `title` | 923 | 100.0% |
| `description>20` | 923 | 100.0% |
| `first_seen_at` | 923 | 100.0% |
| `scraped_at` | 923 | 100.0% |
| `days_listed` | 923 | 100.0% |
| `lat` | 921 | 99.8% |
| `lng` | 921 | 99.8% |
| `department` | 900 | 97.5% |
| `price_usd` | 898 | 97.3% |
| `area_m2` | 898 | 97.3% |
| `price_per_m2` | 873 | 94.6% |
| `zone` | 871 | 94.4% |
| `photo_urls>0` | 845 | 91.5% |
| `photos_count>0` | 845 | 91.5% |
| `zone_specific` | 591 | 64.0% |
| `broker_name` | 515 | 55.8% |
| `broker_phone` | 512 | 55.5% |
| `broker_email` | 512 | 55.5% |
| `is_in_development` | 377 | 40.8% |
| `is_beachfront` | 121 | 13.1% |
| `property_type!=land` | 86 | 9.3% |
| `is_repriced` | 8 | 0.9% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 16 | 1.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 103 | 11.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 207 | 22.4% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 276 | 29.9% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 308 | 33.4% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 144 | 15.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 199 | 21.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront` | 119 | 12.9% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 88 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 243 | 26.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 183 | 19.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 108 | 11.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 6 | 0.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 115 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 18 | 2.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 34 | 3.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 2 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 341 | 36.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 41 | 4.4% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 120 | 13.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 135 | 14.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 71 | 7.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 24 | 2.6% |
| 200-500 | 158 | 17.1% |
| >=500 | 741 | 80.3% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 497 | 946 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `encuentra24` | 3 | 1020 | 0.0% |
| `goodlife` | 40 | 645 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 23 | 1463 | 0.0% |
| `remax` | 336 | 965 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 469 | 50.8% |
| ALL 3 of 3 utility signals (PRD spec) | 76 | 8.2% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.