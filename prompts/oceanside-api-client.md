# Replace the Oceanside scraper with a WP REST API client

You are replacing `pulpo/scrapers/oceanside.py`'s HTML-scraping
implementation with a direct WP REST API client. The site exposes
listings as a public REST endpoint and we just confirmed it works:

```
GET https://oceansideelsalvador.com/wp-json/wp/v2/home-details?per_page=100
```

Returns clean JSON: id, link, title.rendered, content.rendered, slug,
modified, listing-status, location (taxonomy term IDs), property-type
(taxonomy term IDs), class_list, featured_media, acf, meta. No auth.

The win is durability: no more Avada selector regressions, no more
year+area concatenation hack, faster crawl (paginated single endpoint
vs N detail-page fetches). The risk is small: if the API ever breaks
we re-add a scraper, but their CMS is server-rendered WP — this
endpoint is unlikely to disappear.

Read the current `pulpo/scrapers/oceanside.py` and
`pulpo/agents/html_crawler.py` first. Read `pulpo/normalize.py` to
remember the canonical raw-dict shape every source must produce.

## What to build

**1. Rewrite `pulpo/scrapers/oceanside.py`.** The class stays
`OceansideScraper`, slug stays `"oceanside"`, registration with
`SOURCES` stays. Replace the HTML walking with a `_call_api(client,
path, params)` helper plus a paginated crawler.

**2. Resolve the "land" property-type term ID once.** Call
`/wp-json/wp/v2/property-type?per_page=100` and find the term whose
`slug` matches one of: `land`, `lots`, `lots-and-land`, `terrenos`,
`lotes`, `terreno`, `lote`. Cache the ID for the run. If no
land-shaped term exists, log a warning and fall back to fetching all
home-details (the existing pipeline already drops non-land via title
heuristics, but flag this in the report).

**3. Paginate `home-details` filtered by that term.** Call
`/wp-json/wp/v2/home-details?property-type=<id>&per_page=100&page=N`.
WP REST returns `X-WP-Total` and `X-WP-TotalPages` headers — use
those to decide when to stop. Respect the existing `REQUEST_DELAY`
(1.5s).

**4. Map each API record to the existing raw-dict schema.** The
shape downstream `normalize.py` expects:

| Raw key | Source in API response |
|---|---|
| `source_id` | `str(record["id"])` |
| `url` | `record["link"]` |
| `title` | HTML-decode `record["title"]["rendered"]` |
| `description` | strip-tags `record["content"]["rendered"]`, truncate 1500 |
| `raw_price_text` | regex over `content.rendered` (see below) |
| `raw_size_text` | regex over `content.rendered` (see below) |
| `location_text` | from `class_list` strings starting with `location-` (e.g. `location-sonsonate`), joined |
| `property_type` | `"land"` (you've already filtered) |
| `photos_count` | 1 if `featured_media` is non-zero, else 0 (sufficient for now; full count would need a second call) |
| `days_listed` | days between `record["modified"]` and now |
| `is_repriced` | `False` (not derivable from API) |
| `is_beachfront`, `has_paved_access`, `has_water`, `has_power` | regex over `content.rendered` for keywords (`frente al mar`, `pavimentad`, `agua`, `eléctric`/`energ`) |

**5. Reuse the existing area/price extraction regex.** The current
oceanside.py has `_AREA_AFTER_YEAR_RE` and `_AREA_PLAIN_RE`. Keep
both — they already handle the "Listed on YYYY<num>m2" concatenation
quirk. Run them over `content.rendered` (which is essentially the
same `.post-content` blob the HTML scraper used). For price, look
for `$<num>` or `US$<num>` in the same blob.

**6. Implement `report_total(client)`** — should be a one-line API
call now: `GET .../home-details?property-type=<id>&per_page=1`, read
`X-WP-Total` header, return as int.

**7. Implement `crawl_with_meta`** to return
`{records, max_pages_hit, limit_hit}` — `max_pages_hit` is now
basically irrelevant since pagination is bounded by the supplier's
own total, but set it to `True` if you stopped because of a
hard-coded safety cap (e.g., 50 pages × 100 = 5000 records is plenty
of headroom; set the cap there).

**8. Keep the offline/fixture path.** When `offline=True`, return
`load_fixtures("oceanside", "sample_listings.json", limit)` — same
as today. The fixture data already maps to the new schema since
both scraper and API target the same downstream raw dict.

**9. Don't delete the calibration samples.** Leave
`samples/calibration/oceanside/` alone. They're useful documentation
even though the API client doesn't use them.

## Hard constraints

- `python3 -m pulpo.cli --offline` must keep working.
- `tests/test_units.py` and any pytest in `tests/` must keep
  passing.
- Run `python3 automation/coverage_audit.py` after the rewrite —
  oceanside coverage should still be ≥ 95% against the supplier
  total.
- Run `python3 automation/field_audit.py` and report the
  before/after for oceanside on these fields:
  `price_usd`, `area_m2`, `is_beachfront`, `has_paved_access`,
  `has_water`, `has_power`, `photos_count`, `days_listed`. Expected
  improvement: most should be higher because we're parsing every
  listing's content blob instead of an HTML page that may be
  truncated by anti-bot measures.
- Don't add new dependencies. The standard `httpx` client we already
  use handles JSON natively.
- Polite pacing: 1.5s between API calls, same as scraper today.

## Verification

```bash
python3 -m pulpo.cli --offline                 # offline still works
python3 automation/coverage_audit.py           # oceanside ≥ 95%
python3 automation/run.py                      # live run finishes
python3 automation/field_audit.py              # oceanside fields improve
PULPO_OFFLINE=1 python3 -m pytest -q tests/    # tests pass
```

## Final summary in chat

≤180 words. Cover:
1. The land property-type term ID you found (and slug).
2. Total listings pulled from the API vs. previous live scraper run
   (45+ from last audit? compare).
3. Field-completeness before/after for oceanside on the 8 fields
   listed above. Show the diff plainly.
4. One concrete observation about the API data quality — e.g. "the
   `acf` block is always empty so we can't get structured price/area
   that way; we still parse content.rendered" or "the `class_list`
   gives us cleaner location slugs than the regex on the post body
   — could replace the zone-detection logic eventually."
5. Anything that would block making the same move on goodlife
   (which we already know doesn't expose its property CPT, so
   probably "no API path available, scraper stays").

If something surprising comes up — auth required, rate-limit
detected, the home-details endpoint includes non-sale records — stop
and report rather than guessing.
