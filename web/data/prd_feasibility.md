# PRD WS2 — Feasibility Probe

_Generated: 2026-05-05T13:46:51.425152+00:00_  
_Catalog size: **817 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 817 | 100.0% |
| `title` | 817 | 100.0% |
| `description>20` | 817 | 100.0% |
| `first_seen_at` | 817 | 100.0% |
| `scraped_at` | 817 | 100.0% |
| `days_listed` | 817 | 100.0% |
| `area_m2` | 806 | 98.7% |
| `department` | 801 | 98.0% |
| `price_usd` | 798 | 97.7% |
| `price_per_m2` | 787 | 96.3% |
| `zone` | 773 | 94.6% |
| `zone_specific` | 503 | 61.6% |
| `broker_name` | 460 | 56.3% |
| `broker_phone` | 460 | 56.3% |
| `broker_email` | 460 | 56.3% |
| `photo_urls>0` | 357 | 43.7% |
| `photos_count>0` | 357 | 43.7% |
| `is_in_development` | 316 | 38.7% |
| `is_beachfront` | 79 | 9.7% |
| `lat` | 0 | 0.0% |
| `lng` | 0 | 0.0% |
| `is_repriced` | 0 | 0.0% |
| `property_type!=land` | 0 | 0.0% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_water` | 241 | 29.5% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 263 | 32.2% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_paved_access` | 30 | 3.7% | ≥ 40% | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 73 | 8.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_mountain_view` | 7 | 0.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_water_body` | 84 | 10.3% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 251 | 30.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront_text` | 74 | 9.1% | ≥ 15% | 🟡 computed only, below UI gate |
| `has_sewage` | 34 | 4.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 1 | 0.1% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 303 | 37.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 36 | 4.4% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 112 | 13.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 128 | 15.7% | ≥ 15% (gate) | 🟢 surface-eligible |
| `land_recreational` | 58 | 7.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 22 | 2.7% |
| 200-500 | 149 | 18.2% |
| >=500 | 646 | 79.1% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 445 | 932 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `goodlife` | 31 | 597 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 11 | 1423 | 0.0% |
| `remax` | 306 | 951 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 341 | 41.7% |
| ALL 3 of 3 utility signals (PRD spec) | 8 | 1.0% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.