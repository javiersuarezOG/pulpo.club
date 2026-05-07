# PRD WS2 — Feasibility Probe

_Generated: 2026-05-07T15:10:33.918688+00:00_  
_Catalog size: **896 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 896 | 100.0% |
| `title` | 896 | 100.0% |
| `description>20` | 896 | 100.0% |
| `first_seen_at` | 896 | 100.0% |
| `scraped_at` | 896 | 100.0% |
| `days_listed` | 896 | 100.0% |
| `lat` | 894 | 99.8% |
| `lng` | 894 | 99.8% |
| `department` | 877 | 97.9% |
| `price_usd` | 873 | 97.4% |
| `area_m2` | 873 | 97.4% |
| `price_per_m2` | 850 | 94.9% |
| `zone` | 847 | 94.5% |
| `photo_urls>0` | 818 | 91.3% |
| `photos_count>0` | 818 | 91.3% |
| `zone_specific` | 569 | 63.5% |
| `broker_name` | 506 | 56.5% |
| `broker_phone` | 506 | 56.5% |
| `broker_email` | 506 | 56.5% |
| `is_in_development` | 366 | 40.8% |
| `is_beachfront` | 109 | 12.2% |
| `property_type!=land` | 83 | 9.3% |
| `is_repriced` | 1 | 0.1% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 9 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 100 | 11.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 192 | 21.4% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 179 | 20.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 265 | 29.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 112 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 99 | 11.0% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_flat` | 234 | 26.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_sewage` | 36 | 4.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 329 | 36.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 40 | 4.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 112 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 135 | 15.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `land_recreational` | 71 | 7.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 24 | 2.7% |
| 200-500 | 155 | 17.3% |
| >=500 | 717 | 80.0% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 491 | 939 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `goodlife` | 39 | 642 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 22 | 1461 | 0.0% |
| `remax` | 320 | 956 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 385 | 43.0% |
| ALL 3 of 3 utility signals (PRD spec) | 57 | 6.4% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.