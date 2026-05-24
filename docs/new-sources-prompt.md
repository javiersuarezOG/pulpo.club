# Claude Code prompt — add 4 new sources to Pulpo

> Paste everything below the line into Claude Code (running inside the `pulpo.club` repo). It is self-contained.

---

You're adding **four new listing sources** to Pulpo. Pulpo is an El Salvador real-estate aggregator with a specific niche: **terrenos (residential / tourist / commercial), condos, and homes that are at the beach, Lake Coatepeque, or Lake Ilopango.** Build the four scrapers below, in this priority order, one feature branch + PR per source.

## Ground rules (read `CLAUDE.md` first, it governs)
- NEVER commit to `main`. For each source: `git checkout -b feat/source-<slug>`, build, push, open a PR with `gh pr create`, then `gh pr merge <NUM> --auto --squash --delete-branch`.
- One source = one PR. Don't bundle all four.
- Tests must pass offline: `PULPO_OFFLINE=1 pytest -q`. Lint clean: `ruff check .`.
- Honor the null-safety rules in `CLAUDE.md` — every nullable field a scraper emits must be safe downstream.

## How a source is wired (mirror existing code, don't invent patterns)
- Module: `pulpo/scrapers/<slug>.py`. Define `class <Name>Scraper` with `__init__(self, offline=None)`, `crawl(self, limit=30, offline=None) -> list[dict]`, and `crawl_with_meta(...)`. End the module with `_scraper = <Name>Scraper(offline=None)` and `register(SOURCES, "<slug>", _scraper)`, plus a module-level `def crawl(limit=30, offline=None)` (the CLI calls `mod.crawl(...)`).
- Register the import in `pulpo/scrapers/__init__.py`.
- Reuse helpers from `pulpo.agents.html_crawler`: `make_client`, `with_retries`, `is_offline`, `load_fixtures`, `DEFAULT_REQUEST_DELAY`, `HTTPX_OK`.
- Run records through `classify_property_type` (`pulpo/scrapers/_type_classifier.py`) and `upgrade_photo_urls` (`pulpo/scrapers/_photo_url_upgrade.py`), same as `bienesraices.py`.
- Emit the same record dict shape as `bienesraices.py` (`source`, `source_id`, `url`, `title`, `price`, `property_type`, photos, `bedrooms`, area/size, location, lat/lng). Copy its mapping.
- **Filter to the niche**: keep only listings at the Pacific coast / La Libertad surf zone, Lake Coatepeque, or Lake Ilopango. Reuse `WATERFRONT_KEYWORDS` / `VACATION_ZONES` from `automation/property_types.py` (already imported in `bienesraices.py`) rather than hard-coding.
- Add a test at `tests/scrapers/test_<slug>.py` mirroring `tests/scrapers/test_bienesraices.py`: an offline fixture crawl asserting `source`, `source_id`, `url`, `title`, `property_type`. Add a few representative fixture records for the source to `fixtures/sample_listings.json`.
- Verify a live run before opening the PR: `python3 -m pulpo.cli --source <slug> --limit 20`.

## The four sources (data surfaces already probed — confirm, then build)

### 1. CityMax — slug `citymax`  ← build first, highest impact
- Site: `https://www.citymax-sv.com/` . Listings are served by a **JSON API: `https://api.obriencrm.com/v1/Website2/…`** (O'Brien / Optima CRM). The site is a JS SPA — do NOT scrape HTML; hit the API.
- Discover the list endpoint and its pagination/filter params (open the site's terrenos/casas pages in a browser and watch the `api.obriencrm.com` XHR calls, or inspect the SPA bundle). Confirm how to page through all results and how the agency/site is identified to the API.
- **Mirror the API approach in `bienesraices.py`** (sitemap/API fetch → filter → map to schema), not the HTML scrapers.
- Confirmed it carries both beach (La Libertad / Atami / Shalpa) and Ilopango ("Apulo, Ilopango") inventory — both in-niche.

### 2. El Salvador Surf Real Estate — slug `essurf`
- Site: `https://elsalvadorsurfrealestate.com/our-listings/` . **WordPress AgentFire IDX.** A single POST to `https://elsalvadorsurfrealestate.com/wp-json/agentfire/v2/listing3/markers` returns all map markers (the full listing set) in one call.
- Confirm the request body/headers that endpoint expects, parse the marker payload, then fetch detail per listing if the marker payload is thin. Reference the WP-API pattern in `oceanside.py`.
- Boutique coastal agency (El Tunco / El Sunzal / El Zonte / Atami / San Blas) — nearly 100% in-niche; little filtering needed.

### 3. El Agente Inmobiliario — slug `elagente`
- Site: `https://www.elagenteinmobiliario.com/` . **Server-rendered WordPress (Houzez theme)**, listing URLs are `/propiedad/<slug>/`. Plain HTML parse — easiest of the four.
- Find the property archive/listing index (Houzez default is `/propiedades/` or the "Comprar & Alquilar" menu), page through it, parse each `/propiedad/` page. Mirror the HTML pattern in `remax.py` / `century21.py`.
- Small agency with Lake Coatepeque inventory; apply the niche filter.

### 4. KW El Salvador — slug `kw`  ← most effort, do last
- Site: `https://kwelsalvador.kw.com/` runs on the **kw.com global platform (Command/Place API, a JS SPA)**; ES listings are indexed under `kw.com/area/el-salvador-*`. The API is likely key-gated and US-centric.
- First spike whether listings are reachable without auth (watch network calls on the area pages). If they need an API key or the payload is impractical, STOP and report back with what you found instead of forcing it — don't ship a flaky scraper. If reachable, mirror the `bienesraices` API pattern.

## After all mergeable sources land
- Run `python3 -m pulpo.cli --offline` and confirm the new sources appear with sane counts.
- Report a short summary: per source — listings pulled, in-niche kept, data surface used, and any source you deferred (e.g. KW) with the reason.

Skipped on purpose (don't add): Cari Casas (a meta-aggregator that re-lists Encuentra24/Casas24 — pure duplicates), Sophia Business (bespoke CMS, tiny), RE/MAX Central (overlaps the existing `remax` source and was erroring). Separately, the existing `encuentra24` scraper returns only ~2 listings despite ~900 on the portal, and `realtyelsalvador` returns 0 — both look broken and are worth a look, but that's outside this task.
