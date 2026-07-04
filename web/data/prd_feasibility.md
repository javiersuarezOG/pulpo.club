# PRD WS2 — Feasibility Probe

_Generated: 2026-07-04T07:27:59.365352+00:00_  
_Catalog size: **40 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 40 | 100.0% |
| `title` | 40 | 100.0% |
| `description>20` | 40 | 100.0% |
| `price_usd` | 40 | 100.0% |
| `first_seen_at` | 40 | 100.0% |
| `scraped_at` | 40 | 100.0% |
| `photo_urls>0` | 40 | 100.0% |
| `photos_count>0` | 40 | 100.0% |
| `broker_name` | 40 | 100.0% |
| `property_type!=land` | 40 | 100.0% |
| `days_listed` | 40 | 100.0% |
| `lat` | 27 | 67.5% |
| `lng` | 27 | 67.5% |
| `is_in_development` | 14 | 35.0% |
| `is_beachfront` | 10 | 25.0% |
| `zone` | 7 | 17.5% |
| `department` | 7 | 17.5% |
| `is_repriced` | 1 | 2.5% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 1 | 2.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 8 | 20.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 6 | 15.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 6 | 15.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 11 | 27.5% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 12 | 30.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 3 | 7.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 10 | 25.0% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 4 | 10.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 8 | 20.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 4 | 10.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 10 | 25.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 4 | 10.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 9 | 22.5% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 2 | 5.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_sewage` | 1 | 2.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 7 | 17.5% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 1 | 2.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 5 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 1 | 2.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 2 | 5.0% |
| >=500 | 38 | 95.0% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 40 | 1268 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 16 | 40.0% |
| ALL 3 of 3 utility signals (PRD spec) | 2 | 5.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.