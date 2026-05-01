# RE/MAX El Salvador calibration samples

Drop saved detail pages here as `*.html`. RE/MAX SV uses the RE/MAX LATAM
listings template — typically server-rendered enough for selectolax,
though confirm against a live capture (some franchises hydrate pricing
client-side).

Suggested captures before flipping `PULPO_OFFLINE=0`:

- `index-buy-land.html` — saved from the listings index used as
  `LIST_URL` (filter: type=land, operation=sale). The "index" in the
  filename flips calibrate.py to index-card mode.
- 3+ detail pages spanning at least one beachfront and one interior lot
  to make sure the area selector survives different feature-list
  orderings.

Then run:

```bash
python3 automation/calibrate.py --source remax
```

If the saved HTML looks empty (just a `<div id="root">` shell with no
listing content), the page is client-rendered and we'll need to swap the
scraper's `_fetch()` to a Playwright headless browser — same fix path as
the kazu Nuxt SPA. Coverage target: ≥95% across the saved pages.
