# Live Field Audit — Run 1
Timestamp: 2026-05-01T23:22:56Z
Command: `python3 automation/run.py && python3 automation/field_audit.py`
Dataset: 69 live listings (bienesraices 30 · century21 15 · oceanside 14 · goodlife 10)

```
=== bienesraices (30 listings) ===
  field               pop%   count
  price_usd             0%       0   ← CRITICAL gap
  area_m2             100%      30
  zone                 43%      13
  municipality         43%      13
  department           43%      13
  location_text       100%      30
  lat                   0%       0   (feature gap — no geocoding)
  lng                   0%       0
  is_beachfront         0%       0
  has_paved_access      0%       0
  has_water             0%       0
  has_power             0%       0
  is_repriced           0%       0
  days_listed           0%       0
  photos_count        100%      30
  broker_name         100%      30
  broker_phone        100%      30
  broker_email        100%      30
  title               100%      30
  description         100%      30

=== century21 (15 listings) ===
  field               pop%   count
  price_usd             0%       0   ← CRITICAL gap
  area_m2             100%      15
  zone                 26%       4
  location_text       100%      15
  lat                   0%       0
  broker_name         100%      15
  broker_phone        100%      15
  broker_email        100%      15
  title               100%      15
  description           0%       0   ← scraper leaves description blank by design

=== goodlife (10 listings) ===
  field               pop%   count
  price_usd           100%      10
  area_m2               0%       0   ← HIGH gap
  zone                 70%       7
  location_text       100%      10
  broker_name           0%       0   ← no broker extraction
  broker_phone          0%       0
  broker_email          0%       0
  title               100%      10
  description         100%      10

=== oceanside (14 listings) ===
  field               pop%   count
  price_usd            85%      12
  area_m2              64%       9
  zone                 92%      13
  location_text       100%      14
  broker_name           0%       0   ← no broker extraction
  broker_phone          0%       0
  broker_email          0%       0
  title               100%      14
  description         100%      14

=== ALL SOURCES (69 listings) ===
  cross-source weakest 5:
    lat               0%   (0/69)
    lng               0%   (0/69)
    is_beachfront     0%   (0/69)
    has_paved_access  0%   (0/69)
    has_water         0%   (0/69)
```

## Feature gaps vs calibration gaps

**Feature gaps** (need new code, not just selector calibration):
- `lat` / `lng` — 0% across all sources. No geocoding is implemented anywhere.
  This requires either scraper-side coordinate extraction or a post-normalize
  geocoding step. Defer to Phase 2.
- `is_repriced` — 0% everywhere. Requires diff-against-previous-run logic (Phase 2).
- `days_listed` — 0% on live sources. Needs scrape-date tracking across runs.
- `is_beachfront`, `has_paved_access`, `has_water`, `has_power` — 0% on live scrapers.
  The fixture data carried these pre-populated; no live scraper extracts them yet.

**Calibration gaps** (fixable by improving existing scraper selectors/output):
See "Calibration targets" section below.

## Calibration targets

### 1 · price_usd — bienesraices (0%) and century21 (0%) — CRITICAL
**Gap**: Both scrapers output `raw_price_text` as `"140000 USD"` (number-first),
but `parse_price_usd` in `units.py` expects a `$` or `USD` prefix before the number
(e.g. `"$140,000"` or `"USD 140,000"`). The regex never matches, so `price_usd`
stays `None` after normalization.

**Impact**: 45 of 69 live listings (65%) have no price → no `price_per_m2` →
no value-leg score. These listings rank purely on quality + liquidity + upside.

**Fix**: In `bienesraices._parse()` and `century21._map()`, add `"price_usd": float(price)`
directly to the raw output dict. `normalize.py` checks `raw.get("price_usd")` first,
before attempting to parse `raw_price_text`, so it will short-circuit correctly.
This is a one-line addition per scraper, not a selector change.

### 2 · area_m2 — goodlife (0%) — HIGH
**Gap**: 10 live goodlife listings all have `area_m2=None`. The vc_toggle area
selector matches keys `{"area", "área", "lot size", "land size", ...}` but none
of those keys appear in the live goodlife pages (either the theme changed or the
toggles use a different label on current pages, e.g. "Terrain", "Terreno", "Size").

**Impact**: goodlife listings can't be ranked on the value leg (no $/m²), and they
get dropped from comparison with oceanside listings that DO have area.

**Fix**: Pull a fresh goodlife detail page, inspect the actual vc_toggle `<h4>`
labels, and add the live key to `_TOGGLE_AREA_KEYS`. Calibration sample already
exists at `samples/calibration/goodlife/detail.html` — but it's an old SOLD
listing; save a current live detail page to confirm the selector gap.

### 3 · broker_name/phone/email — goodlife (0%) and oceanside (0%) — MEDIUM
**Gap**: Both HTML scrapers return empty broker fields. goodlife's vc_toggle
schema doesn't have an agent section; contact info (if any) is in a widget
outside the toggle structure. Oceanside's broker info is buried inside the
large `.post-content` blob alongside price and size — it can be extracted
with a regex targeting agent name / phone patterns.

**Impact**: Members who unlock the full feed see no contact info for these
sources, which defeats a core value of the member tier.

**Fix**: Add a broker regex pass over `.post-content` in `oceanside.parse_detail_page`.
For goodlife, check whether the current live theme renders broker info in a
sidebar widget or a `<div class="agent-contact">` block and add the selector.
