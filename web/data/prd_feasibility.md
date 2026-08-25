# PRD WS2 — Feasibility Probe

_Generated: 2026-08-25T04:46:47.130149+00:00_  
_Catalog size: **38 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 38 | 100.0% |
| `title` | 38 | 100.0% |
| `description>20` | 38 | 100.0% |
| `price_usd` | 38 | 100.0% |
| `first_seen_at` | 38 | 100.0% |
| `scraped_at` | 38 | 100.0% |
| `photo_urls>0` | 38 | 100.0% |
| `photos_count>0` | 38 | 100.0% |
| `broker_name` | 38 | 100.0% |
| `property_type!=land` | 38 | 100.0% |
| `days_listed` | 38 | 100.0% |
| `lat` | 30 | 78.9% |
| `lng` | 30 | 78.9% |
| `is_in_development` | 19 | 50.0% |
| `is_beachfront` | 11 | 28.9% |
| `zone` | 7 | 18.4% |
| `department` | 7 | 18.4% |
| `is_repriced` | 1 | 2.6% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 7 | 18.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 1 | 2.6% | ≥ 40% | 🔴 below 5% — needs scraper depth |
| `has_power` | 2 | 5.3% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 9 | 23.7% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 14 | 36.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 3 | 7.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 11 | 28.9% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 2 | 5.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 11 | 28.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 3 | 7.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 11 | 28.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 2 | 5.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 4 | 10.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 2 | 5.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_sewage` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 9 | 23.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 1 | 2.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 2 | 5.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 7 | 18.4% |
| >=500 | 31 | 81.6% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 38 | 1123 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 10 | 26.3% |
| ALL 3 of 3 utility signals (PRD spec) | 0 | 0.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.