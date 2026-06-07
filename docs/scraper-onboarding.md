# Adding a new scraper to Pulpo — runbook

> **Audience:** an engineer about to drop a new scraper module into `pulpo/scrapers/`. This runbook captures the patterns that worked through the Phase C wave (xitios, agentiz, santizo, citymax_sc, vivolatam, csbr, realestate_au_sv, jamesedition) and the 2026-06 audit follow-ups.
>
> The goal is **5 minutes of iteration per attempt**, not 7 hours waiting for a nightly. Use `python3 -m pulpo.cli scraper-lab --source <slug>` (PR-FB-1, [#748](https://github.com/javiersuarezOG/pulpo.club/pull/748)) for every change you make below.

***

## Decision tree before you start

1. **Does the site expose a JSON / sitemap / OG-meta surface?** Use that. JSON-LD `RealEstateListing` is the cheapest discovery; sitemap.xml is a close second. Per-source examples:
   - JSON-LD detail page: santizo, citymax_sc, csbr, realestate_au_sv
   - Sitemap XML: vivolatam (catalog client-rendered; sitemap is the only reliable URL source)
   - JSON API: nexo (`/api/v1/public/listings`), bienesraices (sitemap API), elagente (Houzez REST)
   - SPA + Playwright: encuentra24 (Next.js RSC; static HTML returns empty shell)
2. **Does plain `httpx` get through?** Try a dry curl from your machine. If 200, ship with `transport="httpx"`. If 403 from a GitHub Actions runner but 200 from your machine, the WAF is doing IP-geo + JA3 fingerprinting → use `curl_cffi` (precedent: nexo, elagente, realtyelsalvador, jamesedition, agentiz). See `reference_scraper_curl_cffi_when_runner_ip_empty` memory.
3. **Cloudflare JS challenge ("Just a moment...")?** Browser-realistic headers ([#758](https://github.com/javiersuarezOG/pulpo.club/pull/758)) handle most fingerprint gates. If still blocked, Playwright is the only escape — coordinate with the runtime's `_skeleton_helper.py` Playwright transport (lands as part of R7 / events-discovery Port C work).
4. **Per-source volume estimate <10 listings?** Document the floor in `automation/source_watchdog_floors.py` so the brownout detector doesn't false-page on a low-volume source.

***

## Step 1 — Skeleton

Drop a new file at `pulpo/scrapers/<slug>.py`. Use `_skeleton_helper.py` (lands in [#728](https://github.com/javiersuarezOG/pulpo.club/pull/728), Phase C scaffold) when applicable:

```python
from pulpo.scrapers._skeleton_helper import build_scraper

SLUG = "mysource"

CONFIG = {
    "base_url":          "https://www.mysource.com/sv/listings",
    "transport":         "httpx",  # or "curl_cffi"
    "extraction":        "detail_jsonld",  # or "detail_og_meta", "sitemap", "static_urls"
    "catalog_walker":    "page_param",  # or "url_pattern", "sitemap"
    "max_pages":         20,
    "rate_limit_rps":    0.5,
}

crawl = build_scraper(SLUG, CONFIG)
```

Register in `pulpo/scrapers/__init__.py`'s `_SOURCES` dict (autodiscovery picks it up from there).

***

## Step 2 — `_policy.py` entry

Add an entry to `pulpo/scrapers/_policy.py::POLICIES`:

```python
"mysource": Policy(
    transport="httpx",         # or "curl_cffi"
    rate_limit_rps=0.5,        # 0.5 = polite default; raise only if the site advertises a higher rate
    jitter_ms=(200, 800),
    retry_max=3,
    retry_backoff_base_s=1.5,
    user_agent_pool="default", # "safari_macos" for Cloudflare-Ifff JA3 gates
    curl_cffi_impersonate="chrome131",  # if transport="curl_cffi"
    auto_repair=False,
),
```

Browser-realistic headers ([#758](https://github.com/javiersuarezOG/pulpo.club/pull/758)) are applied automatically — no per-scraper wiring.

***

## Step 3 — Offline fixture + parser tests (PR-FB-2 once it lands)

1. Capture a real catalog page + 2–3 representative detail pages:
   ```bash
   python3 -m pulpo.cli scraper-lab --source mysource --limit 10 --write /tmp/lab
   cp /tmp/lab/raw/*.html tests/fixtures/scrapers/mysource/
   ```
2. Add `tests/scrapers/test_mysource.py`:
   ```python
   def test_catalog_extracts_at_least_n_urls(fixture_dir):
       html = (fixture_dir / "catalog.html").read_text()
       urls = scraper._extract_detail_urls_from_catalog_page(html, page_num=1)
       assert len(urls) >= 10

   def test_detail_extracts_title_and_price(fixture_dir):
       html = (fixture_dir / "detail-001.html").read_text()
       rec = scraper._extract_detail(html, "https://mysource.com/...")
       assert rec["title"]
       assert rec["price_usd"] > 0
       assert rec["url"]
   ```
3. Run: `pytest -q tests/scrapers/test_mysource.py` — must complete in <2 seconds and exercise the parser without network access.

***

## Step 4 — PRD hard-gate audit

Run `python3 automation/field_audit.py --acceptance-test` ([#760](https://github.com/javiersuarezOG/pulpo.club/pull/760)) against a fresh dry-run output. **The first 50 listings per source must clear 85% on each of:**

- `property_type` — non-empty string
- `location` — ANY of `location_text`, `zone`, `municipality`, `department`
- `price_usd` — numeric, non-null

Below 85% on any gate? Fix the parser before opening the PR. Patterns:

- **`location` below threshold:** check if your scraper emits `location_text` raw and lets normalize derive `zone` / `municipality`. The disjunction makes that fine — but if NONE of the four are populated, your address-extraction selector is wrong.
- **`price_usd` below threshold:** common cause is "consultar" / "a convenir" listings emitting a `null` price. PRD says these are not visible; reject at the scraper layer if you can identify them.
- **`property_type` below threshold:** your `_extract_detail` isn't setting it. Default to `"land"` (the normalize layer's `detect_property_type` will refine it if the title has keywords).

***

## Step 5 — Pipeline dry-run

After PR-FB-3 lands:

```bash
python3 automation/run.py \
  --sources mysource \
  --limit-per-source 50 \
  --skip-llm --skip-photos --skip-hires --skip-deploy \
  --write-candidate /tmp/mysource-candidate
```

The candidate at `/tmp/mysource-candidate/ranked.json` should:
1. Contain 20–50 records (depending on the source's inventory).
2. Survive validation (no `validation_status="DROP"` cascade).
3. Get assigned to shelf cohorts (`master_category` + `subcategory` populated).
4. Have non-zero dedup hashes — check the cross-source overlap matrix in `automation/dedup_audit.py` to confirm no silent collision with an existing source.

***

## Step 6 — Brownout floor

Add a floor entry to `automation/source_watchdog_floors.py`:

```python
SOURCE_FLOORS = {
    ...
    "mysource": 5,   # baseline kept count; pages when daily kept < this
}
```

Low-volume sources (agentiz, oceanside, jamesedition) ship with single-digit floors. High-volume sources (encuentra24, bienesraices, remax) ship with higher floors.

***

## Step 7 — PR

Title format: `feat(scrapers): <slug> — <one-line summary>`.

Body MUST include:

- [ ] Sample listing counts from the dry-run (raw / kept / dropped).
- [ ] Field-audit acceptance output (`python3 automation/field_audit.py --acceptance-test` → PASS for the new source).
- [ ] Dedup-audit overlap matrix excerpt — confirm no silent collision with existing sources.
- [ ] Either: a Vercel-preview screenshot showing the new source's listings on a homepage shelf, OR a note that the new source needs the next nightly to ship before it's user-visible.
- [ ] The `tests/fixtures/scrapers/<slug>/` directory committed (≤ 200 KB total).

***

## Anti-patterns to avoid

1. **Don't hardcode the country slug.** `scripts/check_country_hardcodes.py` fails CI on `"SV"` / `"El Salvador"` literals — use the per-country manifest. Mark inevitable URL hardcodes with `# multi-country-exempt: <reason>`.
2. **Don't emit `area_varas` or `area_m2_built` as substitutes for `area_m2`.** `pulpo/units.py` already converts varas, manzanas, acres, vrs² via `parse_area`. Emit `raw_size_text="<N> v²"` and let normalize do its job (precedent: nexo, [#756](https://github.com/javiersuarezOG/pulpo.club/pull/756)).
3. **Don't mix URL into a dedup hash.** `pulpo/scrapers/lib/dedup_hasher.py` deliberately excludes URL from `property_fingerprint` so cross-domain duplicates collide (precedent: [#753](https://github.com/javiersuarezOG/pulpo.club/pull/753)). If you need within-source identity, use `identity_fingerprint`.
4. **Don't emit `condo`-typed listings into the `house` cohort.** As of [#752](https://github.com/javiersuarezOG/pulpo.club/pull/752), `detect_property_type` correctly distinguishes apartment / condo / studio from detached-house vocabulary. Trust the normalizer; don't pre-classify in the scraper unless you have signal the normalizer doesn't (e.g. an explicit broker category field).
5. **Don't ship a new source without a brownout floor.** A new source's first red day looks like total failure to the watchdog otherwise.

***

## Reference precedents

| Pattern | Reference scraper | PR |
|---------|-------------------|-----|
| JSON-LD detail extraction | santizo | (Phase C bundle) |
| Sitemap walker | vivolatam | (Phase C bundle) |
| OG-meta + varas conversion | xitios | [#729](https://github.com/javiersuarezOG/pulpo.club/pull/729) |
| Static URL list | agentiz | [#747](https://github.com/javiersuarezOG/pulpo.club/pull/747) |
| Per-category Playwright + pagination | encuentra24 | [#755](https://github.com/javiersuarezOG/pulpo.club/pull/755) |
| JSON API + curl_cffi | nexo | (Phase A) |
| WordPress AgentFire | essurf | (Phase A) |
| WordPress Houzez | elagente, csbr | (Phase A / Phase C) |
| Cloudflare-blocked + Playwright fallback | jamesedition | DRAFT (transport TBD) |

***

## When you get stuck

1. Run `python3 -m pulpo.cli scraper-lab --source <slug> --limit 5` and inspect `/tmp/lab/{raw,normalized,failures}.jsonl` — the failure shape almost always names the broken assumption.
2. Check `automation/scraper_failures/` for a `<slug>_<ts>_<failure_id>.json` snapshot the pipeline already captured.
3. Re-read the canonical contracts in `pulpo/scrapers/lib/` (`dedup_hasher`, `coverage_logger`, `paginate`, `find_jsonld`) — most "hard" problems are solved by a primitive you didn't know existed.
4. Open a draft PR early. The acceptance gate ([#760](https://github.com/javiersuarezOG/pulpo.club/pull/760)) gives a fast, actionable signal on what's still wrong.
