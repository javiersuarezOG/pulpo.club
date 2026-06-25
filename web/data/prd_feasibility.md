# PRD WS2 — Feasibility Probe

_Generated: 2026-06-25T07:48:54.233572+00:00_  
_Catalog size: **23 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 23 | 100.0% |
| `title` | 23 | 100.0% |
| `description>20` | 23 | 100.0% |
| `price_usd` | 23 | 100.0% |
| `first_seen_at` | 23 | 100.0% |
| `scraped_at` | 23 | 100.0% |
| `photo_urls>0` | 23 | 100.0% |
| `photos_count>0` | 23 | 100.0% |
| `broker_name` | 23 | 100.0% |
| `property_type!=land` | 23 | 100.0% |
| `days_listed` | 23 | 100.0% |
| `lat` | 12 | 52.2% |
| `lng` | 12 | 52.2% |
| `is_in_development` | 8 | 34.8% |
| `is_beachfront` | 7 | 30.4% |
| `zone` | 4 | 17.4% |
| `department` | 4 | 17.4% |
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
| `has_ocean_view` | 6 | 26.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 3 | 13.0% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 1 | 4.3% | ≥ 40% | 🔴 below 5% — needs scraper depth |
| `has_water` | 6 | 26.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 8 | 34.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 4 | 17.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront` | 7 | 30.4% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 2 | 8.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 6 | 26.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 3 | 13.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_beach` | 7 | 30.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 2 | 8.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 6 | 26.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 1 | 4.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 1 | 4.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 4.3% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 3 | 13.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `zoning_tourist` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 3 | 13.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 2 | 8.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 1 | 4.3% |
| >=500 | 22 | 95.7% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 23 | 1184 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 8 | 34.8% |
| ALL 3 of 3 utility signals (PRD spec) | 0 | 0.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.