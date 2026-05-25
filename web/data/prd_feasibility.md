# PRD WS2 — Feasibility Probe

_Generated: 2026-05-25T01:47:31.592911+00:00_  
_Catalog size: **875 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 875 | 100.0% |
| `title` | 875 | 100.0% |
| `first_seen_at` | 875 | 100.0% |
| `scraped_at` | 875 | 100.0% |
| `days_listed` | 875 | 100.0% |
| `lat` | 873 | 99.8% |
| `lng` | 873 | 99.8% |
| `department` | 858 | 98.1% |
| `price_usd` | 851 | 97.3% |
| `zone` | 838 | 95.8% |
| `area_m2` | 820 | 93.7% |
| `photo_urls>0` | 810 | 92.6% |
| `photos_count>0` | 810 | 92.6% |
| `description>20` | 804 | 91.9% |
| `price_per_m2` | 796 | 91.0% |
| `zone_specific` | 618 | 70.6% |
| `broker_name` | 487 | 55.7% |
| `broker_phone` | 428 | 48.9% |
| `broker_email` | 428 | 48.9% |
| `is_in_development` | 374 | 42.7% |
| `is_beachfront` | 138 | 15.8% |
| `property_type!=land` | 133 | 15.2% |
| `is_repriced` | 10 | 1.1% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 14 | 1.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 118 | 13.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 161 | 18.4% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 208 | 23.8% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 237 | 27.1% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 111 | 12.7% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_agricultural` | 0 | 0.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_beachfront` | 136 | 15.5% | ≥ 15% | 🟢 meets PRD target |
| `is_commercial` | 83 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 195 | 22.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 142 | 16.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 114 | 13.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_on_lake` | 9 | 1.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_tourist` | 106 | 12.1% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 17 | 1.9% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 31 | 3.5% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 2 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 305 | 34.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 30 | 3.4% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_commercial` | 121 | 13.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_recreational` | 63 | 7.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 71 | 8.1% |
| <50 chars | 0 | 0.0% |
| 50-200 | 23 | 2.6% |
| 200-500 | 142 | 16.2% |
| >=500 | 639 | 73.0% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 414 | 908 | 0.0% |
| `century21` | 14 | 601 | 0.0% |
| `citymax` | 32 | 0 | 100.0% |
| `encuentra24` | 27 | 1087 | 0.0% |
| `essurf` | 39 | 0 | 100.0% |
| `goodlife` | 37 | 636 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 23 | 1463 | 0.0% |
| `remax` | 280 | 958 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 368 | 42.1% |
| ALL 3 of 3 utility signals (PRD spec) | 54 | 6.2% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.