# PRD WS2 — Feasibility Probe

_Generated: 2026-05-04T15:57:51.297753+00:00_  
_Catalog size: **811 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 811 | 100.0% |
| `title` | 811 | 100.0% |
| `first_seen_at` | 811 | 100.0% |
| `scraped_at` | 811 | 100.0% |
| `area_m2` | 800 | 98.6% |
| `price_usd` | 791 | 97.5% |
| `price_per_m2` | 780 | 96.2% |
| `department` | 777 | 95.8% |
| `zone` | 749 | 92.4% |
| `description>20` | 569 | 70.2% |
| `zone_specific` | 483 | 59.6% |
| `broker_name` | 460 | 56.7% |
| `broker_phone` | 460 | 56.7% |
| `broker_email` | 460 | 56.7% |
| `is_in_development` | 259 | 31.9% |
| `photos_count>0` | 13 | 1.6% |
| `days_listed` | 13 | 1.6% |
| `is_beachfront` | 4 | 0.5% |
| `lat` | 0 | 0.0% |
| `lng` | 0 | 0.0% |
| `photo_urls>0` | 0 | 0.0% |
| `is_repriced` | 0 | 0.0% |
| `property_type!=land` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_water` | 176 | 21.7% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 162 | 20.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_paved_access` | 14 | 1.7% | ≥ 40% | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 69 | 8.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_mountain_view` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_water_body` | 63 | 7.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 157 | 19.4% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront_text` | 59 | 7.3% | ≥ 15% | 🟡 computed only, below UI gate |
| `has_sewage` | 22 | 2.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 187 | 23.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 33 | 4.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 94 | 11.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 106 | 13.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 31 | 3.8% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 242 | 29.8% |
| <50 chars | 0 | 0.0% |
| 50-200 | 13 | 1.6% |
| 200-500 | 117 | 14.4% |
| >=500 | 439 | 54.1% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 445 | 932 | 0.0% |
| `century21` | 15 | 0 | 100.0% |
| `goodlife` | 31 | 597 | 0.0% |
| `oceanside` | 13 | 1422 | 0.0% |
| `remax` | 307 | 194 | 73.9% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 219 | 27.0% |
| ALL 3 of 3 utility signals (PRD spec) | 4 | 0.5% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.