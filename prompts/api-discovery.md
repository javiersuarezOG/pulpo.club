# API discovery pass for pulpo.club sources

You are running a 30-minute reconnaissance pass to find out which of
our broker sources expose a usable API we could call instead of
scraping HTML. Output is a single markdown report — do NOT implement
any API clients yet. The human will read the report and decide what to
replace.

## Sources to probe

1. **GoodLife** — `https://goodlifeelsalvador.com` (WordPress)
2. **Oceanside** — `https://oceansideelsalvador.com` (WordPress)
3. **Kazu** — `https://kazurealestate.com` (Nuxt SPA, API at
   `panel.kazurealestate.com` known to be denylisted)
4. **Century 21** — `https://www.century21elsalvador.com` (already
   pulling OmniMLS JSON embedded in the page; document and skip
   further probes unless you find something better at
   `mx.omnimls.com`)
5. **RE/MAX** — `https://www.remax.com.sv` (unknown stack; currently
   "blocked" per the dashboard)
6. **Bienes Raíces El Salvador** — find the host (probably
   `bienesraicesonline.com.sv` or `bienesraices.com.sv` — confirm
   from existing scraper if registered, else web-search the name).

## What to probe per source

For each source, run the following checks (the order is "stop early
if you've already found a clean API"):

1. **WordPress REST**: `curl -sS https://<host>/wp-json/`. If it
   responds with JSON and includes a `routes` object, list which
   namespaces are exposed (e.g. `wp/v2`, `estatik/v1`, `houzez/v1`).
2. **WordPress post types**: if `/wp-json/wp/v2/types` is reachable,
   list every post type that looks property-related: `property`,
   `properties`, `propiedad`, `propiedades`, `listing`, `listings`,
   `inmueble`, `inmuebles`, `lote`, `terreno`, `land`. Probe each at
   `/wp-json/wp/v2/<type>?per_page=1` to confirm it returns listing
   data and note the field shape.
3. **Hidden/plugin APIs**: check `/wp-json/estatik/v1/`,
   `/wp-json/houzez/v1/`, `/wp-json/realhomes/v1/`,
   `/wp-json/impress-listings/v1/` — common real-estate plugins.
4. **Network XHRs**: for SPA-shaped sites (Kazu, possibly RE/MAX),
   inspect the listings page with `curl -sS` or browser DevTools
   (describe the steps in the report — you can't run a browser, so
   report what to look for: typical hosts like `panel.<broker>.com`,
   `api.<broker>.com`, or third-party CRM hosts like
   `omnimls.com`, `tokko.com.ar`, `easybroker.com`).
5. **Sitemap as a shortcut**: `/sitemap.xml` and
   `/sitemap_index.xml` — if listings are individually URL-mapped,
   we can enumerate them without paginating the search UI. Useful
   even when no JSON API exists.
6. **`robots.txt`** — note any disallowed paths and any
   sitemap references.

## Output

A single new file `docs/api-discovery.md` with:

1. **One-line summary at the top**: e.g. "3 of 6 sources expose a
   usable API (GoodLife WP REST, Oceanside WP REST, Bienes Raíces WP
   REST). Century 21 already API-fed. Kazu blocked. RE/MAX no
   public API found."

2. **One section per source** with these fields filled in:
   - **Stack**: WordPress / Nuxt SPA / OmniMLS-embedded / unknown
   - **API found**: yes / no / yes-but-blocked
   - **Endpoint**: the URL we'd call (or "n/a")
   - **Auth**: none / API key / OAuth / unknown
   - **Sample response**: the first 3–5 keys returned, for shape
     awareness (truncate to a few lines — don't dump the whole
     response).
   - **Coverage**: does the API return all listings, or does it
     respect the same filters as the public search?
   - **Recommendation**: replace scraper / keep scraper / needs
     more work / blocked, what would unblock it.

3. **A final priority table** ordering sources by replacement
   value:

   | Priority | Source | Why |
   |---|---|---|
   | 1 | … | cleanest API + most listings |
   | 2 | … | … |

4. **A "next steps" paragraph** suggesting the order in which to
   replace scrapers with API clients, framed as one-liners I can turn
   into follow-up prompts. Example: "Replace goodlife scraper with
   `goodlife_api.py` calling `/wp-json/wp/v2/property?per_page=100` —
   should be ~50 lines."

## Hard constraints

- **Do not implement any API client.** This is reconnaissance only.
- **Do not change any scraper.** Read-only pass on the codebase.
- **Do not add dependencies.** Use `curl` (via the bash tool) or
  Python's `urllib`/`httpx` if already installed.
- **Be polite**: 1 request per second per host, max. Don't enumerate
  beyond what's needed to confirm "API exists / API doesn't exist."
- **Honor robots.txt.** If a host disallows a path, note it and skip.
- **Don't authenticate to anything.** If an endpoint requires an API
  key, note "auth required, can't probe further" and move on.

## Verification

```bash
ls docs/api-discovery.md           # exists
cat docs/api-discovery.md | head   # human-readable, has the summary line
```

## Final summary in chat

≤120 words, just: how many sources have a usable API, top-2
candidates for scraper replacement and why, anything blocked that
needs my decision (e.g. "RE/MAX hydrates from `api.remaxglobal.com`
which requires partner credentials — do you want to reach out?").
