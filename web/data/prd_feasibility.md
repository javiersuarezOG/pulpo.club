# PRD WS2 — Feasibility Probe

_Generated: 2026-07-01T08:14:48.380928+00:00_  
_Catalog size: **37 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 37 | 100.0% |
| `title` | 37 | 100.0% |
| `description>20` | 37 | 100.0% |
| `price_usd` | 37 | 100.0% |
| `first_seen_at` | 37 | 100.0% |
| `scraped_at` | 37 | 100.0% |
| `photo_urls>0` | 37 | 100.0% |
| `photos_count>0` | 37 | 100.0% |
| `broker_name` | 37 | 100.0% |
| `property_type!=land` | 37 | 100.0% |
| `days_listed` | 37 | 100.0% |
| `lat` | 24 | 64.9% |
| `lng` | 24 | 64.9% |
| `is_in_development` | 10 | 27.0% |
| `is_beachfront` | 9 | 24.3% |
| `zone` | 7 | 18.9% |
| `department` | 7 | 18.9% |
| `is_repriced` | 1 | 2.7% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 6 | 16.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 6 | 16.2% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 7 | 18.9% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 9 | 24.3% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 14 | 37.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 2 | 5.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 9 | 24.3% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 2 | 5.4% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 6 | 16.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 6 | 16.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 9 | 24.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 4 | 10.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 8 | 21.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 1 | 2.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 1 | 2.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 2.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 7 | 18.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 1 | 2.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 3 | 8.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 1 | 2.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 5 | 13.5% |
| >=500 | 32 | 86.5% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 37 | 1155 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 14 | 37.8% |
| ALL 3 of 3 utility signals (PRD spec) | 2 | 5.4% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.