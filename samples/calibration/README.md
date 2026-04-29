# Calibration samples

Drop saved HTML pages here, one subfolder per source:

```
samples/calibration/
├── goodlife/
│   ├── detail-cuco-5mz.html       (a property detail page)
│   ├── detail-tunco-2mz.html
│   ├── detail-zonte-1mz.html
│   └── index-search.html          (an index/search page; "index" in the name flips mode)
├── oceanside/
│   └── …
└── kazu/
    └── …
```

How to capture a page:

1. Open the page in a normal browser.
2. Wait for the listing data to render (ignore lazy-loaded photos).
3. `File → Save Page As → Webpage, HTML Only` (NOT "Webpage, complete" — that pulls the whole asset directory).
4. Drop the .html into the matching subfolder.

Then iterate:

```bash
pip install -r requirements.txt   # selectolax (preferred, fast)
python3 automation/calibrate.py --all
```

The harness also accepts `beautifulsoup4 + lxml` as a fallback if selectolax
isn't installable in your environment — it auto-detects whichever backend is
present and prints the backend name in the header line.

Per-source target before flipping `PULPO_OFFLINE=0` in production cron:
≥95% field coverage across at least 3 saved detail pages and 1 index page.

If the saved HTML looks empty (just a `<div id="root">` shell, no listing content),
the site is client-rendered. Fix path: switch the scraper's `_fetch()` to a
Playwright headless browser. The `BaseScraper` interface is structured so this
is a single-module change in `pulpo/scrapers/base.py`.

These samples are gitignored by default — the live HTML can have personal
data (cookie banners, user-id-tagged URLs) and shouldn't be committed.
