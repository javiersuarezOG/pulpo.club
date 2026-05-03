# Field-completeness audit — which fields are missing per source?

You are adding a small audit step that measures, per source, how often
each tracked field is populated across our pulled listings. Output is
a printed table plus one block in `web/data/last_updated.json`. We are
NOT building a dashboard widget yet — the goal is to see which fields
each source under-reports so we know where calibration effort pays off.

Read `pulpo/models.py` and `pulpo/normalize.py` first to remember which
fields the `Listing` dataclass tracks. Then read
`automation/coverage_audit.py` (just merged in commit `ff8e766`) so
your script follows the same shape and conventions.

## Tracked fields

These are the fields whose presence matters for ranking and member
display. Don't add or remove from this list without flagging it:

- **Hard fields** (we drop the listing if both are missing): `price_usd`,
  `area_m2`. Track populated counts anyway — they're the floor.
- **Location**: `zone`, `municipality`, `department`, `lat`, `lng`,
  `location_text`.
- **Quality flags**: `is_beachfront`, `has_paved_access`, `has_water`,
  `has_power`.
- **Lifecycle**: `is_repriced`, `days_listed`, `photos_count`.
- **Broker**: `broker_name`, `broker_phone`, `broker_email`.
- **Content**: `title`, `description`.

Treat a field as "populated" when it's non-null AND non-empty-string.
For boolean flags (`is_beachfront`, `has_paved_access`, `has_water`,
`has_power`, `is_repriced`): only count `True` as populated — `False`
is indistinguishable from "broker didn't say" with our current
normalize logic, so it would inflate the numbers misleadingly. Note
this caveat in the script's docstring.

## What to build

**1. A new CLI script `automation/field_audit.py`** that:

- Loads `web/data/ranked.json` (the full member feed).
- Groups listings by `source`.
- For each source, computes the populated % for every tracked field.
- Prints a single per-source table to stdout. Format:

  ```
  === goodlife (12 listings) ===
  field                pop%   count
  price_usd            100%   12
  area_m2              100%   12
  zone                  92%   11
  has_water             58%    7
  has_power             67%    8
  is_beachfront         33%    4
  broker_phone         100%   12
  description           75%    9
  …
  weakest 3: lat (0%), lng (0%), is_repriced (8%)
  ```

- After all sources, prints a "cross-source weakest fields" summary —
  the 5 fields with the lowest aggregate populated % across all
  sources combined. These are the calibration targets to tackle
  first because they're systemic, not source-specific.
- Exits 0 always (this is informational, not a gate). No threshold,
  no failure.

**2. Append a `field_completeness` block to `web/data/last_updated.json`**
in `automation/run.py` so every weekly cron run captures the snapshot:

```json
"field_completeness": {
  "goodlife": {
    "n_listings": 12,
    "fields": {
      "price_usd": 1.0, "area_m2": 1.0, "zone": 0.92,
      "has_water": 0.58, "has_power": 0.67, "is_beachfront": 0.33,
      "broker_phone": 1.0, "description": 0.75, ...
    }
  },
  "oceanside": { ... },
  ...
}
```

Float 0..1, two decimals. Wire it into `automation/run.py` so it
writes alongside the existing `coverage` block.

**3. One sentence in `README.md`** under the existing "Scraping
reliability" section: "Run `python3 automation/field_audit.py` to see
which fields each source is under-reporting — calibration targets."

## Hard constraints

- Don't change normalize, ranker, or any scraper. Pure measurement.
- Don't add a dashboard widget. Stdout + one JSON block, that's it.
- Don't add dependencies.
- Don't filter or transform the data — read `ranked.json` as-is.
- The script must work even when `ranked.json` is empty or has no
  records for a given source — print "no listings" for that source
  and continue.

## Verification

```bash
python3 -m pulpo.cli --offline      # regenerates ranked.json
python3 automation/field_audit.py   # prints the per-source tables
python3 automation/run.py            # confirms field_completeness lands in last_updated.json
```

The first run prints stats for the fixture data — which is partial by
design. The numbers become meaningful AFTER the live coverage audit
run (which is why phase 1 had to come first).

## Final summary in chat

≤150 words. Cover:
- What the script tells us today (off fixtures) vs. what it'll tell us
  on the first live run.
- The 3 weakest fields you saw in the offline run, and your guess at
  why they're weak (e.g. "`lat`/`lng` are 0% across all sources because
  none of our scrapers extract coordinates yet — that's a feature gap,
  not a calibration gap").
- One concrete recommendation for which calibration target to tackle
  first when we move into phase 3 (selector/calibration improvements
  on the worst per-source field).
