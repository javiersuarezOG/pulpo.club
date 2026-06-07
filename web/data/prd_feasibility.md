# PRD WS2 — Feasibility Probe

_Generated: 2026-06-07T09:41:32.864971+00:00_  
_Catalog size: **18 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 18 | 100.0% |
| `title` | 18 | 100.0% |
| `description>20` | 18 | 100.0% |
| `price_usd` | 18 | 100.0% |
| `first_seen_at` | 18 | 100.0% |
| `scraped_at` | 18 | 100.0% |
| `photo_urls>0` | 18 | 100.0% |
| `photos_count>0` | 18 | 100.0% |
| `broker_name` | 18 | 100.0% |
| `property_type!=land` | 18 | 100.0% |
| `days_listed` | 18 | 100.0% |
| `is_beachfront` | 11 | 61.1% |
| `is_in_development` | 6 | 33.3% |
| `zone` | 1 | 5.6% |
| `department` | 1 | 5.6% |
| `lat` | 1 | 5.6% |
| `lng` | 1 | 5.6% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |
| `is_repriced` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 1 | 5.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_ocean_view` | 8 | 44.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 2 | 11.1% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 2 | 11.1% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 2 | 11.1% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water_body` | 2 | 11.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_agricultural` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_beachfront` | 11 | 61.1% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 1 | 5.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 2 | 11.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 3 | 16.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 11 | 61.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 2 | 11.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 3 | 16.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_sewage` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 3 | 16.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 1 | 5.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 3 | 16.7% |
| >=500 | 15 | 83.3% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 18 | 1085 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 6 | 33.3% |
| ALL 3 of 3 utility signals (PRD spec) | 0 | 0.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.