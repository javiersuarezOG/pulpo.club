# Coverage audit — are we pulling all available supply?

You are adding a small audit step to pulpo.club so we can see, per
source: (a) how many land listings the broker actually publishes, (b)
how many we pulled, (c) whether we ran into our own pagination cap.

The output is a printed table and one new field in
`web/data/last_updated.json`. We are NOT building a new dashboard or
new widgets yet — the goal is to learn the gaps first, then decide
what's worth visualizing.

Read `README.md` and every file under `pulpo/scrapers/` before changing
anything.

## What to build

**1. A `report_total(client)` method on each scraper** that fetches the
listings index once and returns either an `int` (the supplier's
advertised total count) or `None` (unknown). Don't fail if you can't
find the count — just return None.

Per-source hints:

- **goodlife**: the `/land/` index page typically renders a
  "Showing X of Y" string in the Mikado/Kastell theme header, and most
  WordPress real-estate plugins emit a `.result-count` or
  `<header class="woocommerce-result-count">` block. Look there first.
- **oceanside**: Avada/Fusion themes emit a count in the page header
  (`.fusion-page-title` block) or a paginator that names the last
  page. If neither exists, count cards on every page until pagination
  ends and report that.
- **century21**: the OmniMLS embedded JSON blob already has a
  `totalRows` or `total` field at the top level of
  `window.REP_LOG_APP_PROPS.data` — pull it directly. This is the
  cleanest case.
- **remax**: the listings result page typically renders the total in
  a `.result-count` or `[data-total]` element; if not, count cards.
- **kazu**: API is denylisted, return None without erroring.

Do not over-engineer this. If a regex over the index HTML gets the
number, ship that — it's a coverage hint, not load-bearing.

**2. A `MAX_PAGES_HIT` flag on the crawl result.** Modify
`HtmlIndexCrawler.walk` (and the corresponding inline crawl in
`pulpo/scrapers/century21.py`) so that the crawl returns, alongside
the records, a small dict like `{"records": [...], "max_pages_hit":
True/False, "limit_hit": True/False}`. `max_pages_hit` is True when
the loop exhausted `MAX_PAGES` before the index returned an empty
page. `limit_hit` is True when we stopped because we reached the
caller's `limit` argument before the index ran out.

Do this in a way that is **backwards-compatible** — `crawl(limit)`
should still return a `list[dict]` for any existing caller. The
flags can be exposed via a new `crawl_with_meta(limit)` method, or
attached as attributes on the scraper instance after `crawl()`
runs. Pick whichever is cleaner. Document the choice in the agent
docstring.

**3. An audit script `automation/coverage_audit.py`** that:

- Runs every scraper in `SOURCES` with a generous `limit` (default
  500) and high `MAX_PAGES` (override class-level cap to 50 for the
  audit run only).
- For each scraper, calls `report_total()` and the metadata-returning
  crawl, then prints a single table to stdout. Format:

  ```
  source       supplier   pulled   coverage   max_pages_hit   limit_hit
  goodlife     80         80       100%       no              no
  oceanside    42         42       100%       no              no
  century21    12         12       100%       no              no
  remax        156        156      100%       no              no
  kazu         ?          5        ?          no              no       (offline-only)
  ```

- Exits 0 if every source with a known supplier total has coverage ≥
  95% AND no `max_pages_hit=yes`. Exits 1 (with a clear failure line)
  otherwise — that signals to the human "we're under-pulling, fix the
  scraper before trusting the rankings."
- Runs offline-safe: if `PULPO_OFFLINE=1`, the script prints "skipped
  — fixture mode" and exits 0 without making any network calls.

**4. Append to `web/data/last_updated.json`** a `coverage` block:

```json
"coverage": {
  "goodlife":  {"supplier": 80, "pulled": 80, "max_pages_hit": false},
  "oceanside": {"supplier": 42, "pulled": 42, "max_pages_hit": false},
  "century21": {"supplier": 12, "pulled": 12, "max_pages_hit": false},
  "remax":     {"supplier": 156, "pulled": 156, "max_pages_hit": false},
  "kazu":      {"supplier": null, "pulled": 5,  "max_pages_hit": false}
}
```

Wire this in `automation/run.py` so the production cron writes it on
every refresh.

**5. One sentence in `README.md`** under the existing "Scraping
reliability" section: "Run `python3 automation/coverage_audit.py` to
check that every source is pulling at or near 100% of advertised
supply."

## Hard constraints

- Do not break the existing offline pipeline. `python3 -m pulpo.cli
  --offline` and `python3 automation/run.py` (with `PULPO_OFFLINE=1`)
  must still work and still produce the existing files unchanged
  except for the new `coverage` key in `last_updated.json`.
- Do not change ranking, normalization, or fixture data.
- Do not add a new dashboard widget. The audit is a CLI script for
  now; if we want the numbers visible on the website later, we'll
  add it as a small panel in a follow-up — but only after we see
  what the numbers actually look like.
- No new dependencies.

## Verification

```bash
python3 -m pulpo.cli --offline               # still works
python3 automation/run.py                    # PULPO_OFFLINE=1, still works
python3 automation/coverage_audit.py         # in offline mode prints "skipped"
```

Then describe in the final summary, in plain English, what the audit
script will tell us when we run it for the first time against live
sites — i.e. "if remax shows pulled=24 with max_pages_hit=yes, that
means we have a pagination cap problem; bump MAX_PAGES or the
pageSize URL param."

Final summary: ≤150 words. Include exactly what new files exist, what
changed in existing files, and one concrete example of the table the
human should expect to see on first live run.
