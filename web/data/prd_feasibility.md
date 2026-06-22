# PRD WS2 — Feasibility Probe

_Generated: 2026-06-22T09:01:41.813874+00:00_  
_Catalog size: **26 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 26 | 100.0% |
| `title` | 26 | 100.0% |
| `description>20` | 26 | 100.0% |
| `price_usd` | 26 | 100.0% |
| `first_seen_at` | 26 | 100.0% |
| `scraped_at` | 26 | 100.0% |
| `photo_urls>0` | 26 | 100.0% |
| `photos_count>0` | 26 | 100.0% |
| `broker_name` | 26 | 100.0% |
| `property_type!=land` | 26 | 100.0% |
| `days_listed` | 26 | 100.0% |
| `lat` | 14 | 53.8% |
| `lng` | 14 | 53.8% |
| `is_in_development` | 8 | 30.8% |
| `is_beachfront` | 7 | 26.9% |
| `zone` | 4 | 15.4% |
| `department` | 4 | 15.4% |
| `is_repriced` | 1 | 3.8% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 1 | 3.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 7 | 26.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 3 | 11.5% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 2 | 7.7% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 6 | 23.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 8 | 30.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 3 | 11.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 7 | 26.9% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 3 | 11.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 3 | 11.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 5 | 19.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 7 | 26.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 2 | 7.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 5 | 19.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 2 | 7.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_sewage` | 1 | 3.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 3.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 3 | 11.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `zoning_tourist` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 4 | 15.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `land_recreational` | 2 | 7.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 4 | 15.4% |
| >=500 | 22 | 84.6% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 26 | 1116 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 10 | 38.5% |
| ALL 3 of 3 utility signals (PRD spec) | 0 | 0.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.