# PRD WS2 — Feasibility Probe

_Generated: 2026-05-19T07:22:01.384445+00:00_  
_Catalog size: **917 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 917 | 100.0% |
| `title` | 917 | 100.0% |
| `description>20` | 917 | 100.0% |
| `first_seen_at` | 917 | 100.0% |
| `scraped_at` | 917 | 100.0% |
| `days_listed` | 917 | 100.0% |
| `lat` | 915 | 99.8% |
| `lng` | 915 | 99.8% |
| `department` | 895 | 97.6% |
| `price_usd` | 893 | 97.4% |
| `area_m2` | 892 | 97.3% |
| `price_per_m2` | 868 | 94.7% |
| `zone` | 866 | 94.4% |
| `photo_urls>0` | 839 | 91.5% |
| `photos_count>0` | 839 | 91.5% |
| `zone_specific` | 586 | 63.9% |
| `broker_name` | 515 | 56.2% |
| `broker_phone` | 512 | 55.8% |
| `broker_email` | 512 | 55.8% |
| `is_in_development` | 375 | 40.9% |
| `is_beachfront` | 119 | 13.0% |
| `property_type!=land` | 86 | 9.4% |
| `is_repriced` | 7 | 0.8% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 15 | 1.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 103 | 11.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 203 | 22.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 276 | 30.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 305 | 33.3% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 144 | 15.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 197 | 21.5% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront` | 117 | 12.8% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 89 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 239 | 26.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 181 | 19.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 106 | 11.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 111 | 12.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 18 | 2.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 34 | 3.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 339 | 37.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 41 | 4.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 120 | 13.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 135 | 14.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 69 | 7.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 24 | 2.6% |
| 200-500 | 157 | 17.1% |
| >=500 | 736 | 80.3% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 497 | 946 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `encuentra24` | 3 | 1135 | 0.0% |
| `goodlife` | 40 | 645 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 21 | 1459 | 0.0% |
| `remax` | 332 | 964 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 466 | 50.8% |
| ALL 3 of 3 utility signals (PRD spec) | 75 | 8.2% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.