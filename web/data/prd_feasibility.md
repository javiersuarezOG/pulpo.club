# PRD WS2 — Feasibility Probe

_Generated: 2026-05-08T15:00:13.974327+00:00_  
_Catalog size: **895 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 895 | 100.0% |
| `title` | 895 | 100.0% |
| `description>20` | 895 | 100.0% |
| `first_seen_at` | 895 | 100.0% |
| `scraped_at` | 895 | 100.0% |
| `days_listed` | 895 | 100.0% |
| `lat` | 893 | 99.8% |
| `lng` | 893 | 99.8% |
| `department` | 875 | 97.8% |
| `price_usd` | 872 | 97.4% |
| `area_m2` | 872 | 97.4% |
| `price_per_m2` | 849 | 94.9% |
| `zone` | 845 | 94.4% |
| `photo_urls>0` | 817 | 91.3% |
| `photos_count>0` | 817 | 91.3% |
| `zone_specific` | 566 | 63.2% |
| `broker_name` | 507 | 56.6% |
| `broker_phone` | 507 | 56.6% |
| `broker_email` | 507 | 56.6% |
| `is_in_development` | 361 | 40.3% |
| `is_beachfront` | 117 | 13.1% |
| `property_type!=land` | 83 | 9.3% |
| `is_repriced` | 2 | 0.2% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 15 | 1.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 96 | 10.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 205 | 22.9% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 270 | 30.2% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 295 | 33.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 140 | 15.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 194 | 21.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront` | 115 | 12.8% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 86 | 9.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 233 | 26.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 181 | 20.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 105 | 11.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 108 | 12.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 18 | 2.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 32 | 3.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 330 | 36.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 41 | 4.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 114 | 12.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 135 | 15.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `land_recreational` | 71 | 7.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 24 | 2.7% |
| 200-500 | 156 | 17.4% |
| >=500 | 715 | 79.9% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 492 | 940 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `goodlife` | 39 | 642 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 22 | 1461 | 0.0% |
| `remax` | 318 | 945 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 459 | 51.3% |
| ALL 3 of 3 utility signals (PRD spec) | 77 | 8.6% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.