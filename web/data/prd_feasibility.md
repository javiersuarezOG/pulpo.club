# PRD WS2 — Feasibility Probe

_Generated: 2026-06-17T08:47:38.324879+00:00_  
_Catalog size: **28 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 28 | 100.0% |
| `title` | 28 | 100.0% |
| `description>20` | 28 | 100.0% |
| `price_usd` | 28 | 100.0% |
| `first_seen_at` | 28 | 100.0% |
| `scraped_at` | 28 | 100.0% |
| `photo_urls>0` | 28 | 100.0% |
| `photos_count>0` | 28 | 100.0% |
| `broker_name` | 28 | 100.0% |
| `property_type!=land` | 28 | 100.0% |
| `days_listed` | 28 | 100.0% |
| `lat` | 11 | 39.3% |
| `lng` | 11 | 39.3% |
| `is_in_development` | 10 | 35.7% |
| `is_beachfront` | 7 | 25.0% |
| `zone` | 3 | 10.7% |
| `department` | 3 | 10.7% |
| `is_repriced` | 1 | 3.6% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 1 | 3.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 7 | 25.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 2 | 7.1% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 5 | 17.9% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 6 | 21.4% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 8 | 28.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 3 | 10.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 7 | 25.0% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 3 | 10.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 2 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_motivated` | 6 | 21.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 7 | 25.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 1 | 3.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 7 | 25.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 2 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_sewage` | 1 | 3.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 3.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 6 | 21.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 1 | 3.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 4 | 14.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 2 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 4 | 14.3% |
| >=500 | 24 | 85.7% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 28 | 1166 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 10 | 35.7% |
| ALL 3 of 3 utility signals (PRD spec) | 0 | 0.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.