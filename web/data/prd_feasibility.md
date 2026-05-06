# PRD WS2 — Feasibility Probe

_Generated: 2026-05-06T12:21:55.482737+00:00_  
_Catalog size: **873 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 873 | 100.0% |
| `title` | 873 | 100.0% |
| `description>20` | 873 | 100.0% |
| `first_seen_at` | 873 | 100.0% |
| `scraped_at` | 873 | 100.0% |
| `days_listed` | 873 | 100.0% |
| `area_m2` | 856 | 98.1% |
| `department` | 855 | 97.9% |
| `price_usd` | 854 | 97.8% |
| `price_per_m2` | 837 | 95.9% |
| `zone` | 825 | 94.5% |
| `photo_urls>0` | 795 | 91.1% |
| `photos_count>0` | 795 | 91.1% |
| `zone_specific` | 546 | 62.5% |
| `broker_name` | 506 | 58.0% |
| `broker_phone` | 506 | 58.0% |
| `broker_email` | 506 | 58.0% |
| `is_in_development` | 350 | 40.1% |
| `is_beachfront` | 100 | 11.5% |
| `property_type!=land` | 58 | 6.6% |
| `is_repriced` | 1 | 0.1% |
| `lat` | 0 | 0.0% |
| `lng` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 8 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 92 | 10.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 192 | 22.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 178 | 20.4% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 263 | 30.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 110 | 12.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_beachfront` | 94 | 10.8% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_flat` | 234 | 26.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `has_sewage` | 36 | 4.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 322 | 36.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 39 | 4.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 112 | 12.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 133 | 15.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `land_recreational` | 59 | 6.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 24 | 2.7% |
| 200-500 | 154 | 17.6% |
| >=500 | 695 | 79.6% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 491 | 939 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `goodlife` | 31 | 597 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 11 | 1423 | 0.0% |
| `remax` | 316 | 953 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 382 | 43.8% |
| ALL 3 of 3 utility signals (PRD spec) | 57 | 6.5% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.