# PRD WS2 — Feasibility Probe

_Generated: 2026-05-09T14:14:49.718782+00:00_  
_Catalog size: **899 listings**_  
_UI filter gate: ≥ 15% population (per PRD §OQ-1)_

This report measures whether the PRD's proposed fields can actually be populated given today's scraper output. Green = ready to surface or meets PRD target. Amber = computed but below gate or PRD target. Red = needs deeper scraper extraction.

## 1. Already populated today (no PRD work needed)

| Field | Count | % |
|---|---:|---:|
| `url` | 899 | 100.0% |
| `title` | 899 | 100.0% |
| `description>20` | 899 | 100.0% |
| `first_seen_at` | 899 | 100.0% |
| `scraped_at` | 899 | 100.0% |
| `days_listed` | 899 | 100.0% |
| `lat` | 897 | 99.8% |
| `lng` | 897 | 99.8% |
| `department` | 877 | 97.6% |
| `price_usd` | 876 | 97.4% |
| `area_m2` | 874 | 97.2% |
| `price_per_m2` | 851 | 94.7% |
| `zone` | 847 | 94.2% |
| `photo_urls>0` | 821 | 91.3% |
| `photos_count>0` | 821 | 91.3% |
| `zone_specific` | 576 | 64.1% |
| `broker_name` | 512 | 57.0% |
| `broker_phone` | 510 | 56.7% |
| `broker_email` | 510 | 56.7% |
| `is_in_development` | 362 | 40.3% |
| `is_beachfront` | 117 | 13.0% |
| `property_type!=land` | 86 | 9.6% |
| `is_repriced` | 2 | 0.2% |

## 2. NLP keyword feasibility (§FR-2.5 dictionary against current text)

| Field | Hits | % | PRD Target | Verdict |
|---|---:|---:|---:|---|
| `has_mountain_view` | 15 | 1.7% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_ocean_view` | 94 | 10.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `has_paved_access` | 205 | 22.8% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_power` | 270 | 30.0% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water` | 296 | 32.9% | ≥ 40% | 🟡 above 15% gate, below PRD target |
| `has_water_body` | 142 | 15.8% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_agricultural` | 197 | 21.9% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_beachfront` | 115 | 12.8% | ≥ 15% | 🟡 computed only, below UI gate |
| `is_commercial` | 85 | 9.5% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_flat` | 236 | 26.3% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_motivated` | 182 | 20.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `is_on_beach` | 107 | 11.9% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_tourist` | 110 | 12.2% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `is_walk_to_beach` | 18 | 2.0% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `has_sewage` | 29 | 3.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `is_repriced_text` | 2 | 0.2% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `zoning_residential` | 334 | 37.2% | ≥ 15% (gate) | 🟢 surface-eligible |
| `zoning_tourist` | 41 | 4.6% | ≥ 15% (gate) | 🔴 below 5% — needs scraper depth |
| `land_agricultural` | 115 | 12.8% | ≥ 15% (gate) | 🟡 computed only, below UI gate |
| `land_commercial` | 135 | 15.0% | ≥ 15% (gate) | 🟢 surface-eligible |
| `land_recreational` | 72 | 8.0% | ≥ 15% (gate) | 🟡 computed only, below UI gate |

## 3. Description quality (gates NLP + AI feasibility downstream)

**Length distribution:**

| Bucket | Count | % |
|---|---:|---:|
| empty | 0 | 0.0% |
| <50 chars | 0 | 0.0% |
| 50-200 | 24 | 2.7% |
| 200-500 | 157 | 17.5% |
| >=500 | 718 | 79.9% |

**Per-source quality (lower `pct_short_lt50` = better NLP/AI inputs):**

| Source | n | Avg chars | % short (<50) |
|---|---:|---:|---:|
| `bienesraices` | 495 | 944 | 0.0% |
| `century21` | 15 | 654 | 0.0% |
| `encuentra24` | 2 | 780 | 0.0% |
| `goodlife` | 39 | 642 | 0.0% |
| `nexo` | 9 | 160 | 0.0% |
| `oceanside` | 22 | 1461 | 0.0% |
| `remax` | 317 | 942 | 0.0% |

## 4. US-01 flagship filter — "water + power + paved road"

This is the PRD's most-load-bearing user story. The cohort size determines whether the filter is useful (returns enough results) or empty.

| Definition | Hits | % |
|---|---:|---:|
| ANY 1 of 3 utility signals (relaxed) | 460 | 51.2% |
| ALL 3 of 3 utility signals (PRD spec) | 77 | 8.6% |

---

Re-run with `python3 automation/prd_feasibility.py`. Wire into `automation/run.py` to refresh nightly. Extend `KEYWORDS` in this script to lift hit rates as PRD §FR-2.5 keyword YAML files are introduced.