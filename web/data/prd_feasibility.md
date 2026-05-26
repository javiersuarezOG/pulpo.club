# PRD WS2 — Feasibility Probe

_Generated: 2026-05-26T07:30:15.119964+00:00_  
_Catalog size: **863 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 863 | 100.0% |
| `title` | 863 | 100.0% |
| `first_seen_at` | 863 | 100.0% |
| `scraped_at` | 863 | 100.0% |
| `days_listed` | 863 | 100.0% |
| `lat` | 861 | 99.8% |
| `lng` | 861 | 99.8% |
| `department` | 848 | 98.3% |
| `price_usd` | 839 | 97.2% |
| `zone` | 830 | 96.2% |
| `area_m2` | 807 | 93.5% |
| `photo_urls>0` | 798 | 92.5% |
| `photos_count>0` | 798 | 92.5% |
| `description>20` | 792 | 91.8% |
| `price_per_m2` | 783 | 90.7% |
| `zone_specific` | 610 | 70.7% |
| `broker_name` | 486 | 56.3% |
| `broker_phone` | 427 | 49.5% |
| `broker_email` | 427 | 49.5% |
| `is_in_development` | 367 | 42.5% |
| `is_beachfront` | 139 | 16.1% |
| `property_type!=land` | 135 | 15.6% |
| `is_repriced` | 11 | 1.3% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 12 | 1.4% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 120 | 13.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 158 | 18.3% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 210 | 24.3% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 237 | 27.5% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 110 | 12.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_agricultural` | 4 | 0.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_beachfront` | 137 | 15.9% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 82 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 192 | 22.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 141 | 16.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 114 | 13.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 8 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 106 | 12.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 18 | 2.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 31 | 3.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 2 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 296 | 34.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 29 | 3.4% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 121 | 14.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 62 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 71 | 8.2% |
| <50 chars | 0 | 0.0% |
| 50-200 | 15 | 1.7% |
| 200-500 | 139 | 16.1% |
| >=500 | 638 | 73.9% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 413 | 907 | 0.0% |
| `century21` | 14 | 601 | 0.0% |
| `citymax` | 31 | 0 | 100.0% |
| `encuentra24` | 28 | 1083 | 0.0% |
| `essurf` | 40 | 0 | 100.0% |
| `goodlife` | 38 | 639 | 0.0% |
| `oceanside` | 23 | 1463 | 0.0% |
| `remax` | 276 | 965 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 365 | 42.3% |
| ALL 3 of 3 utility signals (PRD spec) | 54 | 6.3% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.