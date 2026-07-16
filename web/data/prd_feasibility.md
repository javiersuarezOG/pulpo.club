# PRD WS2 — Feasibility Probe

_Generated: 2026-07-16T06:54:50.142388+00:00_  
_Catalog size: **31 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 31 | 100.0% |
| `title` | 31 | 100.0% |
| `description>20` | 31 | 100.0% |
| `price_usd` | 31 | 100.0% |
| `first_seen_at` | 31 | 100.0% |
| `scraped_at` | 31 | 100.0% |
| `photo_urls>0` | 31 | 100.0% |
| `photos_count>0` | 31 | 100.0% |
| `broker_name` | 31 | 100.0% |
| `property_type!=land` | 31 | 100.0% |
| `days_listed` | 31 | 100.0% |
| `lat` | 25 | 80.6% |
| `lng` | 25 | 80.6% |
| `is_in_development` | 9 | 29.0% |
| `zone` | 4 | 12.9% |
| `department` | 4 | 12.9% |
| `is_beachfront` | 4 | 12.9% |
| `is_repriced` | 3 | 9.7% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 5 | 16.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 2 | 6.5% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 3 | 9.7% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 11 | 35.5% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 13 | 41.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 4 | 12.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 4 | 12.9% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_flat` | 5 | 16.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 4 | 12.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 4 | 12.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 3 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 6 | 19.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 1 | 3.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 5 | 16.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 1 | 3.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_recreational` | 1 | 3.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 3 | 9.7% |
| >=500 | 28 | 90.3% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 31 | 1186 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 12 | 38.7% |
| ALL 3 of 3 utility signals (PRD spec) | 1 | 3.2% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.