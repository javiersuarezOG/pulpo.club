# PRD WS2 — Feasibility Probe

_Generated: 2026-06-13T17:26:46.810060+00:00_  
_Catalog size: **33 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 33 | 100.0% |
| `title` | 33 | 100.0% |
| `description>20` | 33 | 100.0% |
| `price_usd` | 33 | 100.0% |
| `first_seen_at` | 33 | 100.0% |
| `scraped_at` | 33 | 100.0% |
| `photo_urls>0` | 33 | 100.0% |
| `photos_count>0` | 33 | 100.0% |
| `broker_name` | 33 | 100.0% |
| `property_type!=land` | 33 | 100.0% |
| `days_listed` | 33 | 100.0% |
| `is_in_development` | 16 | 48.5% |
| `is_beachfront` | 9 | 27.3% |
| `lat` | 6 | 18.2% |
| `lng` | 6 | 18.2% |
| `zone` | 5 | 15.2% |
| `department` | 5 | 15.2% |
| `area_m2` | 0 | 0.0% |
| `price_per_m2` | 0 | 0.0% |
| `zone_specific` | 0 | 0.0% |
| `broker_phone` | 0 | 0.0% |
| `broker_email` | 0 | 0.0% |
| `is_repriced` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 1 | 3.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 8 | 24.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_paved_access` | 3 | 9.1% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_power` | 4 | 12.1% | ≥ 40% | 🟡 computed only, below UI gate |
| `has_water` | 10 | 30.3% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 12 | 36.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 6 | 18.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront` | 9 | 27.3% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 3 | 9.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 8 | 24.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 7 | 21.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 9 | 27.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_lake` | 1 | 3.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 9 | 27.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_walk_to_beach` | 2 | 6.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_sewage` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 3.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 9 | 27.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 1 | 3.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 3 | 9.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 2 | 6.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 0 | 0.0% |
| 200-500 | 4 | 12.1% |
| >=500 | 29 | 87.9% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `encuentra24` | 33 | 1193 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 14 | 42.4% |
| ALL 3 of 3 utility signals (PRD spec) | 0 | 0.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.