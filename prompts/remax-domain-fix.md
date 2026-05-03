# Fix the RE/MAX scraper — wrong domain, real fix

The current `pulpo/scrapers/remax.py` points at `www.remax.com.sv`,
which doesn't resolve (the cron has been logging DNS errors every
week). The actual RE/MAX SV site is at
`www.remax-elsalvador.com` — confirmed reachable. Web search reports
~556 land+sale listings on the SV portal, so this is a meaningful
supply addition once it works.

This prompt does the discovery and the fix in one pass. Stop and
report if discovery uncovers anything that would block the fix
(JS-rendered SPA, hard auth wall, anti-bot block).

## Step 1 — Probe the live site (5 min)

```bash
mkdir -p samples/calibration/remax/

# Confirm reachability and get an HTTP status
curl -sI "https://www.remax-elsalvador.com/showing-properties-in/el-salvador/for-sale/newest-listings" | head -5

# Save the index page
curl -sL "https://www.remax-elsalvador.com/showing-properties-in/el-salvador/for-sale/newest-listings" \
  -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0)" \
  -o samples/calibration/remax/index-live-1.html

# Probe for sitemap and any structured feeds
curl -sL "https://www.remax-elsalvador.com/sitemap.xml" -o /tmp/remax-sitemap.xml
curl -sI "https://www.remax-elsalvador.com/wp-json/" | head -3
curl -sL "https://www.remax-elsalvador.com/robots.txt"
```

Look at `samples/calibration/remax/index-live-1.html`. Three things to
check:

1. **Is it real HTML or a JS shell?** If the body is essentially empty
   except for a `<div id="root">` or similar — the site is client-
   rendered and selectolax can't extract listings from it. STOP and
   report. We'd need a different fetch strategy (Playwright headless
   or finding the JSON API the SPA hydrates from).
2. **What CSS class are listing cards using?** Grep for the listing
   anchor. Common LATAM RE/MAX shapes: `.proploudListing`,
   `.property-card`, `.listing-summary`, `.proploudPropertyHolder`.
3. **What's the URL pattern for an individual listing?** From
   index-live-1.html, find one detail-page link (e.g.
   `/listing-detail/<id>` or `/property/<slug>`). Grab one and save
   it:
   ```bash
   curl -sL "<DETAIL_URL>" -A "Mozilla/5.0..." -o samples/calibration/remax/detail-live-1.html
   ```

If the index page contains a "land for sale" filter URL that's
different from the "for-sale/newest-listings" one above, prefer that —
it'll be more efficient than pulling all listings and filtering by
title. Common slugs: `/for-sale/lots-and-land`,
`/for-sale/land-and-lots`. Probe a couple to find the working one.

## Step 2 — Update the scraper (15 min)

Edit `pulpo/scrapers/remax.py`:

1. **`BASE_URL`** → `"https://www.remax-elsalvador.com/"`
2. **`LIST_URL`** → the working land+sale URL with `{page}` slot.
   The site likely uses `/page-N/` in the path or `?page=N` in the
   query string — confirm from the saved index page (look for
   pagination links).
3. **Selectors** — calibrate against the saved samples. Update
   `INDEX_CARD_SEL`, `INDEX_LINK_SEL`, `DETAIL_TITLE_SEL`,
   `DETAIL_PRICE_SEL`, `DETAIL_AREA_SEL`, `DETAIL_LOC_SEL`,
   `DETAIL_DESC_SEL` until `python3 automation/calibrate.py
   --source remax` reports ≥ 80% coverage on detail pages.
4. **`report_total(client)`** — implement properly now that the host
   resolves. Look for the listing count on the index page (web
   search showed RE/MAX renders "Total properties: N" near the top).
   Regex over the index HTML to extract that number; return it as an
   int, or `None` if not found.

If the site exposes a clean JSON API (e.g., a search endpoint that
returns listings as JSON), prefer that path — same call shape as
century21.py's `_extract_results`. Document where the API lives.

## Step 3 — Verify (5 min)

```bash
# Calibration coverage on saved samples
python3 automation/calibrate.py --source remax

# Live coverage audit
unset PULPO_OFFLINE
PULPO_LIMIT=1000 python3 automation/coverage_audit.py 2>&1 | grep -A1 remax

# Full pipeline run
python3 automation/run.py 2>&1 | tail -5

# Confirm listings are now flowing
python3 -c "
import json
d = json.load(open('web/data/ranked.json'))
remax = [r for r in d if r['source'] == 'remax']
print(f'remax listings: {len(remax)}')
if remax:
    print(f'sample title: {remax[0].get(\"title\")}')
    print(f'sample price_usd: {remax[0].get(\"price_usd\")}')
"

# Tests still pass
PULPO_OFFLINE=1 python3 -m pytest -q tests/
```

Expected outcome: remax goes from 0 listings to dozens or hundreds,
with `price_usd` populated on most. If you can only get title+url and
not price/area on detail pages, that's still progress — commit the
URL fix and we'll iterate on selectors.

## Hard constraints

- Don't break the offline pipeline. `python3 -m pulpo.cli --offline`
  must still work (fixtures continue to back the offline path).
- Don't change other scrapers.
- Don't add dependencies.
- Polite pacing: keep `REQUEST_DELAY = 1.5`. If pulling 500+ listings
  in one run, that's a 12+ minute crawl — fine for cron, fine for
  manual audits. Don't try to parallelize.
- If the site requires auth, returns 403, or hides listings behind a
  login wall: STOP, document, don't try to bypass.

## Commit

One commit when verified:

```
fix(scrapers/remax): point at remax-elsalvador.com (real domain)
- BASE_URL: www.remax.com.sv (dead) → www.remax-elsalvador.com
- LIST_URL: <new path>
- Selectors calibrated against samples/calibration/remax/
- report_total: extracts "Total properties: N" from index header
- Coverage: <before=0> → <after=N>
```

## Final summary in chat

≤150 words. Cover:
1. Whether the site is HTML or JS-rendered (the gating question).
2. The new `LIST_URL` you settled on and pagination shape.
3. Final remax coverage — listings pulled, supplier total if you
   could extract it.
4. Any selectors that still need calibration follow-up (don't fix
   in this PR — flag for a follow-up).
5. One sentence on whether the supply looks duplicative with what
   we already have (skim 5 random listings — do their locations
   overlap heavily with goodlife/oceanside/century21/bienesraices,
   or is RE/MAX adding new SV territory?).

If discovery reveals JS-rendering or any blocker, stop after Step 1
and report — don't try to ship a half-fixed scraper.
