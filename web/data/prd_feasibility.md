# PRD WS2 — Feasibility Probe

_Generated: 2026-05-05T21:18:42.454057+00:00_  
_Catalog size: **819 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 819 | 100.0% |
| `title` | 819 | 100.0% |
| `description>20` | 819 | 100.0% |
| `first_seen_at` | 819 | 100.0% |
| `scraped_at` | 819 | 100.0% |
| `days_listed` | 819 | 100.0% |
| `area_m2` | 808 | 98.7% |
| `department` | 803 | 98.0% |
| `price_usd` | 799 | 97.6% |
| `price_per_m2` | 788 | 96.2% |
| `zone` | 775 | 94.6% |
| `photo_urls>0` | 752 | 91.8% |
| `photos_count>0` | 752 | 91.8% |
| `zone_specific` | 505 | 61.7% |
| `broker_name` | 460 | 56.2% |
| `broker_phone` | 460 | 56.2% |
| `broker_email` | 460 | 56.2% |
| `is_in_development` | 318 | 38.8% |
| `is_beachfront` | 79 | 9.6% |
| `property_type!=land` | 4 | 0.5% |
| `lat` | 0 | 0.0% |
| `lng` | 0 | 0.0% |
| `is_repriced` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 8 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 80 | 9.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 187 | 22.8% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 169 | 20.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 241 | 29.4% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 102 | 12.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 74 | 9.0% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_flat` | 219 | 26.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_sewage` | 34 | 4.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 303 | 37.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 36 | 4.4% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 112 | 13.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 128 | 15.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `land_recreational` | 59 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 22 | 2.7% |
| 200-500 | 149 | 18.2% |
| >=500 | 648 | 79.1% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 445 | 932 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `goodlife` | 31 | 597 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 13 | 1422 | 0.0% |
| `remax` | 306 | 951 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 356 | 43.5% |
| ALL 3 of 3 utility signals (PRD spec) | 55 | 6.7% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.