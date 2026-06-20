# PRD WS2 — Feasibility Probe

_Generated: 2026-06-20T08:02:00.118967+00:00_  
_Catalog size: **35 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 35 | 100.0% |
| `title` | 35 | 100.0% |
| `description>20` | 35 | 100.0% |
| `price_usd` | 35 | 100.0% |
| `first_seen_at` | 35 | 100.0% |
| `scraped_at` | 35 | 100.0% |
| `photo_urls>0` | 35 | 100.0% |
| `photos_count>0` | 35 | 100.0% |
| `broker_name` | 35 | 100.0% |
| `property_type!=land` | 35 | 100.0% |
| `days_listed` | 35 | 100.0% |
| `lat` | 15 | 42.9% |
| `lng` | 15 | 42.9% |
| `is_in_development` | 14 | 40.0% |
| `is_beachfront` | 7 | 20.0% |
| `zone` | 5 | 14.3% |
| `department` | 5 | 14.3% |
| `is_repriced` | 1 | 2.9% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 1 | 2.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 9 | 25.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 1 | 2.9% | ≥ 40% | 🔴 below 5% — needs scraper depth |
| `has_power` | 3 | 8.6% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 10 | 28.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 13 | 37.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 4 | 11.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 7 | 20.0% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 3 | 8.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 7 | 20.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 5 | 14.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 7 | 20.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 3 | 8.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 8 | 22.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 2 | 5.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_sewage` | 1 | 2.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 2.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 7 | 20.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 1 | 2.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 4 | 11.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 2 | 5.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 3 | 8.6% |
| >=500 | 32 | 91.4% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 35 | 1208 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 12 | 34.3% |
| ALL 3 of 3 utility signals (PRD spec) | 0 | 0.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.