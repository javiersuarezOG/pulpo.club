# PRD WS2 — Feasibility Probe

_Generated: 2026-05-11T15:51:53.807455+00:00_  
_Catalog size: **910 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 910 | 100.0% |
| `title` | 910 | 100.0% |
| `description>20` | 910 | 100.0% |
| `first_seen_at` | 910 | 100.0% |
| `scraped_at` | 910 | 100.0% |
| `days_listed` | 910 | 100.0% |
| `lat` | 908 | 99.8% |
| `lng` | 908 | 99.8% |
| `department` | 888 | 97.6% |
| `price_usd` | 887 | 97.5% |
| `area_m2` | 884 | 97.1% |
| `price_per_m2` | 861 | 94.6% |
| `zone` | 858 | 94.3% |
| `photo_urls>0` | 832 | 91.4% |
| `photos_count>0` | 832 | 91.4% |
| `zone_specific` | 587 | 64.5% |
| `broker_name` | 513 | 56.4% |
| `broker_phone` | 510 | 56.0% |
| `broker_email` | 510 | 56.0% |
| `is_in_development` | 372 | 40.9% |
| `is_beachfront` | 120 | 13.2% |
| `property_type!=land` | 87 | 9.6% |
| `is_repriced` | 3 | 0.3% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 15 | 1.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 102 | 11.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 206 | 22.6% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 275 | 30.2% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 301 | 33.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 142 | 15.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 197 | 21.6% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront` | 118 | 13.0% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 88 | 9.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 236 | 25.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 184 | 20.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 107 | 11.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 110 | 12.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 18 | 2.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 34 | 3.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 2 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 338 | 37.1% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 41 | 4.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 115 | 12.6% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 135 | 14.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 72 | 7.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 24 | 2.6% |
| 200-500 | 157 | 17.3% |
| >=500 | 729 | 80.1% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 495 | 944 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `encuentra24` | 3 | 1020 | 0.0% |
| `goodlife` | 39 | 642 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 23 | 1463 | 0.0% |
| `remax` | 326 | 956 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 466 | 51.2% |
| ALL 3 of 3 utility signals (PRD spec) | 77 | 8.5% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.