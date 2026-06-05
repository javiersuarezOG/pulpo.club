# Phase C scraper calibration — dev pickup instructions

**Status:** DRAFT skeletons live in 2 open PRs:
- **#703** — `xitios` (reference pattern)
- **#701** — bundle of 7 scrapers sharing `_skeleton_helper.py`: `agentiz`, `santizo`, `citymax_sc`, `vivolatam`, `csbr`, `realtor_intl_sv`, `jamesedition`

Each is a runnable skeleton that satisfies the offline contract test but uses **placeholder selectors** for the online crawl. This doc tells a dev how to graduate any one of them from DRAFT to production-ready in ~15 minutes per source.

---

## Prerequisites

You need:
- A laptop with the repo checked out at `/Users/sehonores/Desktop/CodeExperiments/snoop-latam/pulpo.club`
- A modern browser with DevTools (Chrome/Safari/Firefox)
- Network access to the source site (some sites geofence or IP-block; use a residential connection, not a VPN/datacenter IP, especially for `realtor_intl_sv`)
- ~15 minutes per source

You do **not** need:
- Headless Playwright (only needed if HTML extraction fails — most modern real-estate sites expose JSON-LD which works over plain HTTP)
- A scraping proxy (start without one; add `transport="curl_cffi"` in `_policy.py` only if you hit a Cloudflare/Akamai challenge)

---

## URL reference (from Sebas's research, deduplicated)

| Slug | Live URL to inspect | Notes |
|---|---|---|
| `xitios` | https://www.xitios.com.sv/propiedades/buscar?categoria%5B%5D=VEN&tipo%5B%5D=RAN | Search-results page with VEN (venta = for-sale) + RAN (range — all categories) filters |
| `santizo` | https://santizorealestate.com/s/terreno/ventas?id_property_type=32 | Santizo splits inventory by property-type filter. Other types: 11=casa-campestre, 17=lote-de-playa, 32=terreno. **Skip `id_property_type=8` (bodega/warehouse) — out of Pulpo's scope.** First-pass: walk just terreno (32) + lote-de-playa (17) + casa-campestre (11) URLs separately and merge results. Second-pass: figure out if a no-filter base URL like `/s/ventas` exists. |
| `citymax_sc` | https://www.citymax-sc.com/inmuebles/venta/el-salvador?in=terrenos%2cfincas | "venta" = for-sale; `?in=terrenos,fincas` filter. The skeleton's `LIST_URL` placeholder needs replacement with this. |
| `vivolatam` | https://www.vivolatam.com/es/el-salvador/bienes-raices/m?price=sale | The skeleton's `LIST_URL` placeholder needs replacement. **Multi-country site — make sure the URL path scopes to `/es/el-salvador/`** before pagination kicks in. |
| `csbr` | https://www.camarabienesraices.com.sv/resultado-busqueda/?keyword=&type%5B%5D=fincas&type%5B%5D=playa&type%5B%5D=terrenos | Search-results page with the three relevant property type filters. Skeleton placeholder needs replacement. |
| `realtor_intl_sv` (formerly `realestate_au_sv`?) | https://www.realestate.com.au/international/sv?searchtypes=rural+land | **🚨 CORRECTION** — Sebas's actual research points at `realestate.com.au` (Australian portal with international inventory), NOT `realtor.com` as the PRD originally said. They're different sites. The skeleton at `pulpo/scrapers/realtor_intl_sv.py` needs either a slug-rename to `realestate_au_sv` OR a `BASE_URL`/`LIST_URL` swap to realestate.com.au. Decide first; the rest follows. **ToS clearance still required** before going live. |
| `jamesedition` | https://www.jamesedition.com/es/real_estate/house-lago-de-coatepeque-el-salvador | Luxury Coatepeque-only. Low volume (~50 listings). |

---

## Per-source calibration steps

### Step 1 — Inspect the catalog page in DevTools (3 min)

For each source you want to ship:

1. Open the URL above in a fresh browser tab.
2. Open DevTools → **Network** tab. Filter to "Doc" or "XHR".
3. Reload the page. Look for:
   - **JSON API call?** A request to `/api/...` or `/wp-json/...` returning JSON. If yes, copy the URL — this is your scraper's actual endpoint (skip HTML parsing entirely).
   - **JSON-LD in the HTML?** Right-click the page → "View Source" → Cmd+F for `application/ld+json`. If present and contains `"@type": "Residence"` or similar, your scraper can use `lib.find_jsonld(html, schema_type="Residence")` as-is.
   - **Pagination shape?** Click the pagination "next" button (page 2). What's the URL?
     - `?page=2` → set `page_param="page"` in the scraper's `SkeletonConfig`
     - `/page/2/` → set `url_pattern="https://.../page/{page}/"`
     - `?p=2` → set `page_param="p"`
     - "Load more" button (infinite scroll, no URL change) → flag for follow-up; may need Playwright
   - **The "X listings" text** — somewhere on the page. Example: "Mostrando 942 propiedades", "1,247 listings found", "47 inmuebles en venta". **Copy the exact text** — needed for the `target_discovery_patterns` regex.
4. Save the rendered HTML: in DevTools → **Sources** tab → right-click the URL → "Save All As". Place under `samples/<slug>/catalog.html`. (Optional but speeds up offline testing.)

### Step 2 — Inspect a single listing detail page (3 min)

1. Click any listing card to open its detail page.
2. View Source / DevTools → confirm JSON-LD presence (`@type: "Residence"` or `"Product"` or `"RealEstateListing"`).
3. If JSON-LD is absent or thin, identify the CSS selectors for:
   - title (often `<h1>`)
   - price (look for `data-price`, class names like `property-price`, etc.)
   - area_m2 / m² (often near the price)
   - photo URLs (carousel `<img>` srcs)
4. Save: `samples/<slug>/listing-detail.html`. (Optional.)

### Step 3 — Edit the scraper file (5 min)

For each scraper at `pulpo/scrapers/<slug>.py`, replace the placeholder values in `SkeletonConfig` with the real ones from steps 1+2.

**Example diff** (this is what the calibrated `xitios.py` would look like — values are illustrative; verify against the live site):

```python
class XitiosScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="xitios",
        base_url="https://www.xitios.com.sv",
        # CHANGED — real catalog URL with VEN+RAN filters:
        list_url="https://www.xitios.com.sv/propiedades/buscar?categoria%5B%5D=VEN&tipo%5B%5D=RAN",
        page_param="pagina",  # CHANGED — Xitios uses "pagina" not "page"
        url_pattern=None,
        target_discovery_patterns=(
            # CHANGED — exact text from the live UI:
            r"(\d[\d,.]*)\s+propiedades?\s+encontradas?",
            r"Resultados:\s+(\d[\d,.]*)",
        ),
        max_pages=40,
    )
```

For `santizo` specifically — the simplest first-pass is to crawl each property-type filter URL separately and merge results inside the scraper. Override `_crawl_online` in the SantizoScraper class to loop over `[11, 17, 32]` (casa-campestre, lote-de-playa, terreno) before calling `super()._crawl_online`. (Bodega `8` is commercial, out of scope.)

### Step 4 — Run the live smoke test (2 min)

The repo ships a single-source diagnostic that hits the live site and reports what came back. Use it before pushing:

```bash
cd pulpo.club  # main checkout
python3 scripts/smoke_scraper.py xitios --limit 20
```

Read the output:
- `kept_count / target_discovered ≥ 0.8` → calibration is good; ship.
- `kept_count == 0` → selectors are wrong OR the site blocked us. Look at `scraper_failures/` for the saved response.
- `target_discovered == None` → your regex didn't match the count text. Inspect the live HTML directly: `curl https://<url> | grep -o '...your-text...'`.

### Step 5 — Replace the synthetic fixtures (1 min)

The skeleton's offline test uses 3 synthetic fixtures in `fixtures/sample_listings.json` (filter for `source: "<slug>"` records). Replace them with 5 real records you captured from step 2.

Minimum fields per fixture record:
```json
{
  "source": "xitios",
  "source_id": "12345",
  "url": "https://www.xitios.com.sv/propiedad/...",
  "title": "Casa en El Tunco",
  "description": "...",
  "price_usd": 350000,
  "area_m2": 600,
  "photo_urls": ["https://...", "..."],
  "raw_size_text": "600 m²",
  "property_type": "house",
  "zone": "el-tunco"
}
```

The `zone` slug must be from `pulpo/normalize.py::ZONE_PATTERNS` (e.g. `el-tunco`, `el-zonte`, `lago-coatepeque`, `lago-ilopango`, `atami`, etc.). If the listing's location doesn't match any existing zone slug, that's a sign the normalize layer needs a new zone added — flag in the PR description.

### Step 6 — Run the test suite (1 min)

```bash
PULPO_OFFLINE=1 python3 -m pytest tests/scrapers/test_<slug>.py tests/test_source_integration.py -q
```

Expected: all green.

### Step 7 — Update the metadata (30 seconds)

In `pulpo/scrapers/_metadata.py`, find your scraper's entry under `SCRAPER_METADATA[...]`. Update:
- `target_prd`: the PRD-stated count (or your best estimate after seeing the live catalog)
- `failure_modes`: **remove** the `"DRAFT skeleton — calibration pass required"` line. Add any real failure modes you encountered (e.g. `"requires curl_cffi transport"`, `"pagination caps at 50"`).

### Step 8 — Push the calibration commit (1 min)

Each scraper goes in its own commit:

```bash
git add pulpo/scrapers/<slug>.py pulpo/scrapers/_metadata.py fixtures/sample_listings.json
git commit -m "feat(scrapers): calibrate <slug> — real selectors + fixtures"
git push
```

If the PR was DRAFT, click "Ready for review" on GitHub after the calibration commit lands.

---

## Source-specific gotchas

### `xitios` (PR #703)
- URL has `%5B%5D` (URL-encoded `[]`) — must be preserved when paginating. Test that `?pagina=2&categoria[]=VEN&tipo[]=RAN` resolves correctly; if Xitios is strict, you may need `requests.utils.requote_uri` or to pre-format the URL template via `url_pattern` instead of `page_param`.

### `santizo` (PR #701)
- Multi-filter setup. Walk `id_property_type=11`, `=17`, `=32` separately. Open question: does `https://santizorealestate.com/s/ventas` (no type filter) return EVERYTHING? If yes, switch to that single URL. Verify in step 1.

### `citymax_sc` (PR #701)
- Confirm distinct inventory from existing `citymax` scraper. After step 4's smoke test, run:
  ```bash
  python3 -c "
  import json
  data = json.load(open('web/data/dedup_audit.json'))
  print(data['overlap_matrix'].get('citymax', {}).get('citymax_sc', 0))
  "
  ```
  If overlap > 80% of either source's unique count, the sites mirror each other → collapse `citymax_sc` into a `citymax` config flag and drop the separate scraper.

### `vivolatam` (PR #701)
- Multi-country site. Make sure your `list_url` path includes `/es/el-salvador/` so the SV scope is enforced AT THE URL LEVEL, not at the validation layer downstream. **Country-hardcode guardrail:** if you find yourself writing `if "SV" in something`, read the active country code from `pulpo.countries.active()` instead (see `automation/validation.py` for the canonical idiom). The guardrail check at `scripts/check_country_hardcodes.py` will fail CI otherwise.

### `csbr` (PR #701)
- Industry-association portal. Lower volume but higher quality. The skeleton already marks the source as institutional in `pulpo/quality_score.INSTITUTIONAL_SOURCES` (sources in that set get a +1 ranking nudge).

### `realtor_intl_sv` / `realestate_au_sv` (PR #701) — **DECISION REQUIRED FIRST**
1. **ToS clearance.** realtor.com / realestate.com.au are US/AU-based portals. Confirm Pulpo has legal authorization to scrape SV inventory from these sources.
2. **Slug rename.** The skeleton is named `realtor_intl_sv` because the PRD said `realtor.com/international/sv`. Sebas's actual research link points at **`realestate.com.au/international/sv`** — a different site. Either:
   - **Option A:** keep the slug `realtor_intl_sv`, swap `BASE_URL` + `LIST_URL` to point at realestate.com.au, update the docstring to note the rename rationale.
   - **Option B:** rename the file + slug to `realestate_au_sv`. Slightly more work (touches `_metadata.py` key, the test file, the registration line). Cleaner long-term.
3. **Anti-bot expected.** Modern major portals all sit behind Cloudflare/Akamai. If the smoke test gets 403 or a Cloudflare challenge, escalate the transport in `pulpo/scrapers/_policy.py`:
   ```python
   POLICIES["realtor_intl_sv"] = Policy(transport="curl_cffi", rate_per_sec=0.3, ...)
   ```
   Add `curl_cffi` to `requirements.txt` if not already present.

### `jamesedition` (PR #701)
- Luxury inventory. Some listings exceed `automation/validation_bounds.PRICE_FLAG_MAX` ($20M). That's correct behavior — they'll be FLAGGED (kept + warned), not dropped. Don't widen the price ceiling.
- JSON-LD likely present (modern luxury portals all expose it for SEO).

---

## Verification per source

Once a scraper is graduated, the next nightly will:

1. Run the live crawl (autodiscovery picks it up; no workflow edit needed).
2. Write a row to `web/data/scraper_coverage_history.jsonl` with `kept_count`, `target_discovered`, `coverage_ratio_vs_discovered`. Watch for `"status": "warn"` (coverage ratio < 0.8) — that's an iteration signal.
3. Add the source to `web/data/dedup_audit.json`'s `per_source` block + overlap matrix.
4. Add the source to `web/data/kpi_dashboard.json`'s `per_source_coverage` block.

The watchdog at `scripts/check_source_health.py` will alert on `status="warn"` via the existing Slack hook.

Per the PRD's acceptance criteria, **≥3 new sources must be live in prod** before D3 acceptance can ship. Pick the highest-confidence 3 (probably `xitios`, `santizo`, `jamesedition` since they're lowest-risk + non-anti-bot) and calibrate those first.

---

## After calibration: dedup against existing sources

After ≥1 new scraper lands and the next nightly runs:

```bash
jq '.overlap_matrix' web/data/dedup_audit.json | jq 'to_entries | map(select(.value | to_entries | any(.value > 20)))'
```

Any pair where the overlap count is meaningfully high (>20% of the smaller source's unique fingerprints) deserves a look. If the new scraper is mostly re-publishing inventory from an existing source, consider:
- Dropping the new scraper (zero net inventory gain)
- Keeping both for cross-validation (richer data per listing — broker info from both sides)
- Marking the smaller source for retirement after a sunset period

The `[dedup_audit] WARN high overlap (>= 50%)` line in the nightly log surfaces this automatically.

---

## Roll-back path

Each scraper is independently revertable:
- File: `pulpo/scrapers/<slug>.py`
- Test: `tests/scrapers/test_<slug>.py`
- Metadata: `pulpo/scrapers/_metadata.py` (the slug's entry)
- Fixture: `fixtures/sample_listings.json` (records with `source: "<slug>"`)
- Policy: `pulpo/scrapers/_policy.py` (the slug's row, if added)

Delete those five surfaces and the source is gone. The autodiscovery picks up the absence on the next nightly; the watchdog notices the missing `source_health_history.jsonl` row and surfaces it within 30h. No data corruption — the source just stops showing up in `ranked.json`.
