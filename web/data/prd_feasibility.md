# PRD WS2 — Feasibility Probe

_Generated: 2026-06-27T07:28:30.890755+00:00_  
_Catalog size: **21 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 21 | 100.0% |
| `title` | 21 | 100.0% |
| `description>20` | 21 | 100.0% |
| `price_usd` | 21 | 100.0% |
| `first_seen_at` | 21 | 100.0% |
| `scraped_at` | 21 | 100.0% |
| `photo_urls>0` | 21 | 100.0% |
| `photos_count>0` | 21 | 100.0% |
| `broker_name` | 21 | 100.0% |
| `property_type!=land` | 21 | 100.0% |
| `days_listed` | 21 | 100.0% |
| `lat` | 14 | 66.7% |
| `lng` | 14 | 66.7% |
| `is_beachfront` | 6 | 28.6% |
| `is_in_development` | 6 | 28.6% |
| `zone` | 4 | 19.0% |
| `department` | 4 | 19.0% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |
| `is_repriced` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 4 | 19.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 2 | 9.5% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 2 | 9.5% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 3 | 14.3% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water_body` | 9 | 42.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 2 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 6 | 28.6% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 1 | 4.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_flat` | 5 | 23.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 3 | 14.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 6 | 28.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 1 | 4.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 5 | 23.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 1 | 4.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 4.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 4 | 19.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 1 | 4.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_recreational` | 1 | 4.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 3 | 14.3% |
| >=500 | 18 | 85.7% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 21 | 1109 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 5 | 23.8% |
| ALL 3 of 3 utility signals (PRD spec) | 0 | 0.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.