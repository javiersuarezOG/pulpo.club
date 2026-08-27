# Pulpo v1 API — contract

Status: **live — `/ping`, `/meta`, `/listings`, `/listings/:id`.**

## Why this exists

Pulpo's capabilities — search ranked lots, filter, fetch listing detail — lived
only inside the website: `web/app/pages.jsx` filters a client-side array loaded
from a static JSON blob. That is fine with one consumer and a structural problem
with three. The Telegram bot, the MCP server, and the website all need the same
ranking rules, the same filter semantics, and the same listing shape; without a
shared contract each one reimplements them and they drift.

The fix is two layers, not one:

- **`shared/`** — the capability core, as plain TypeScript. Platform-neutral: no
  `fs`, no `process`, no `window`, no React. The website imports it *in-process*
  (it keeps its fast static-CDN data fetch and its client-side filtering; only
  the *logic* moves). The API imports the exact same files.
- **`/api/v1/*`** — a thin HTTP skin over that core, for consumers that cannot
  import JavaScript from our repo.

So "one source of truth" is enforced at the **module** level. The website is not
required to make an HTTP round trip to its own backend to prove the point — that
would add latency and serverless cost to a working site for no user benefit.

```
                    shared/  (filters · sort · search · adapt · catalog)
                   /    |    \
        website ──/     |     \── /api/v1/*  ──  Telegram bot  (HTTP)
     (in-process)       |
                   MCP server (in-process)
```

## The api/ boundary rule — read before touching a handler

Endpoints under `api/v1` and `api/mcp` are **CommonJS `.js`, not
TypeScript**. That is a hard constraint, not a preference.

Vercel compiles TypeScript functions only for files inside `api/`, and
the restriction is **transitive**: nothing in a `.ts` function's
dependency graph may reach outside `api/` at any depth. These handlers
need the shared core, so they cannot be TypeScript. Established on
2026-08-27 by deploying probe functions to a preview and bisecting:

| probe | result |
|---|---|
| CommonJS entrypoint → outside `api/` | 200 |
| TS → self-contained `.js` inside `api/` | 200 |
| TS → `.ts` inside `api/` | 200 |
| TS → `shared/*.ts` (outside) | **500** |
| TS → plain `.js` (outside) | **500** |
| TS → `.js` inside `api/` → outside | **500** (transitive) |

Two theories were tested and disproven — don't retry them. It is **not**
a module-format problem: a no-import `.ts` function works with either
`export default` or `module.exports`. And `includeFiles: shared/**`
does not help: the files were never missing, they were uncompiled.

**How shared code is reached:**

```
api/v1/*.js  --require-->  api/_core.js  --require-->  shared/dist/api-core.cjs
```

`shared/dist/api-core.cjs` is an esbuild bundle of `shared/api-core.ts`,
self-contained (zero external imports) and **committed** — generating it
only at build time left it absent from a fresh checkout and every
endpoint 500'd. `shared/` stays TypeScript and holds every rule worth
type-checking; the handlers are HTTP plumbing.

**Guardrails.** `tests/api/api_import_boundary.test.js` fails on any
`.ts` under those directories, on a handler requiring `shared/`
directly, or on an entrypoint missing the bundle from `includeFiles`.
`tests/api/shared_bundle_fresh.test.js` rebuilds the bundle and compares
byte-for-byte so source and deployed logic cannot drift.

**Alarm.** `scripts/check_api_health.py` runs every 6 hours from
`pulpo-webhook-health.yml` and Slacks on failure. No build-time check
can see this failure class — the fault lived only in the emitted bundle
while CI was green — so it hits the real endpoints and checks response
*shape*: listing floors, canonical ids, absolute URLs, a detail
round-trip, and a live PII assertion.

## Versioning

`v1` is **path-frozen and additive-only**. Safe: new endpoints, new response
fields, new optional query params. Not safe, and therefore `/api/v2` material:
renaming or removing a field, changing the meaning or type of an existing field,
changing a default, or tightening validation on something previously accepted.

## Auth, cost, and exposure

v1 read endpoints are **public and unauthenticated**, rate-limited per IP.

This adds no exposure: the identical data is already publicly downloadable at
`/data/ranked.list.json` — the API is a nicer interface to bytes anyone can
already fetch. A shared secret would add key distribution to every present and
future channel while protecting nothing. `PULPO_INTERNAL_API_KEY` stays where it
belongs, on `/api/social/listings` (a different, internal contract).

Responses set long CDN cache lifetimes, so the origin function runs rarely and
serverless cost stays near zero regardless of channel traffic.

### Data source and the PII boundary

v1 reads **`web/data/ranked.list.json` only** — the 73-field, PII-stripped
projection the pipeline writes (see `_RANKED_LIST_FIELDS` in
`automation/pipeline_steps.py`).

`web/data/ranked.json` carries `broker_name` / `broker_phone` / `broker_email`
and **must never be served by a public endpoint**. The website's data loader
falls back to `ranked.json` when the slim file 404s; **v1 deliberately does not
copy that fallback** — a missing catalog returns `503 data_unavailable`. Every
v1 function additionally excludes `ranked.json` from its deployment bundle in
`vercel.json`, so the guarantee is structural rather than a code-review promise.

## Canonical listing ID

`<source>__<source_id>` — e.g. `remax__001461165132`.

This is already the format the website synthesizes, `/api/social/listings`
exposes, and the newsletter links with. Two other formats exist in the codebase
(`featured.json` uses `source|source_id`, `automation/sitemap.py` emits
`source-source_id`); they are pre-existing drift tracked separately, and
`shared/listing-id.ts` is the canonical implementation.

## Conventions

| Aspect | Contract |
|---|---|
| Methods | `GET` only. Anything else → `405` + `Allow` header |
| Success | `200` with the endpoint's documented body |
| Errors | `{ "error": "snake_case_code" }` — never an exception message |
| List envelope | `{ data, total, limit, offset, generated_at, country }` |
| `generated_at` | The catalog's pipeline timestamp, not request time. `null` if unstamped — never faked |
| Locale | **No `locale` param.** Bilingual fields are returned as `{ en, es }` and the channel picks. One representation = one cache entry |
| Country | `?country=SV` (default `SV`). Unknown → `400 unknown_country` |
| Rate limit | Per IP. Over → `429 rate_limited` + `Retry-After` |

Error codes: `method_not_allowed`, `invalid_param`, `unknown_country`,
`not_found`, `rate_limited`, `data_unavailable`.

**Pagination is `limit`/`offset`.** Note for implementers: the listing `rank`
field is *not* a usable cursor — it is non-contiguous (post-rank purges leave
gaps) and `null` on sold listings.

## Endpoints

### `GET /api/v1/ping` — live

Liveness probe, and the deploy-risk spike for the whole layer: it imports both
ESM TypeScript from `shared/` and a CommonJS helper from `api/`, so one curl
proves the module chain survives Vercel's bundler.

```json
{ "ok": true, "version": "v1", "runtime": "node", "now": "2026-08-21T17:42:07.001Z" }
```

`Cache-Control: no-store`.

### `GET /api/v1/meta`

Vocabulary for building queries: zones (slug, display name, count), categories,
price bounds, `total`, `generated_at`, `country`. Channels build their menus
from this so no zone list is ever hardcoded in an adapter.

### `GET /api/v1/listings`

Ranked, filtered, paginated listings. Query params are parsed with the
website's own share-link codec (`shared/engine/params.ts`), so these two mean
exactly the same thing:

```
/browse?sub=land&pmax=250000&features=ocean_view
/api/v1/listings?sub=land&pmax=250000&features=ocean_view
```

| key | meaning |
|---|---|
| `zones` | comma-separated zone **display names** (`El Tunco`), as returned in `meta.zones[].name` — this matches the website's own share links. The MCP tools additionally accept slugs and translate. |
| `types` `features` `infra` `status` `tag` | comma-separated sets |
| `pmin` `pmax` `smin` `smax` | price / size bounds (`pmax` absent = uncapped) |
| `master` `sub` | `beach\|lake` / `homes\|condos\|land` |
| `ready` `score_min` `rmax` | readiness floor, score floor, rank cap |
| `inc` | `1` to include incomplete listings |
| `q` | free-text, all tokens must match |
| `sort` | `rank` (default) `price_asc` `price_desc` `newest` |
| `limit` `offset` | default 10, max 50 / max offset 2000 |
| `country` | `SV` (default) |

Unknown params are ignored and malformed numbers fall back to defaults rather
than erroring — a bot sending `limit=abc` gets the first page, not a 400 it
cannot explain to a user. `country` is the exception: silently serving a
different country than asked for would be a lie, so that is a hard `400`.

`total` is the size of the whole filtered set, not the page, so a channel can
decide whether to offer "more results".

### `GET /api/v1/listings/:id`

One listing by canonical ID. Unknown ID → `404 not_found`.

## Consumers

| Consumer | How it reaches the core | Ships in |
|---|---|---|
| Website | imports `shared/` in-process | PR-4 |
| MCP server (`/api/mcp`) | imports `shared/` in-process — see [mcp.md](mcp.md) | PR-6 |
| Telegram bot | HTTP, over `/api/v1/*` | PR-7 |
| WhatsApp | HTTP, over `/api/v1/*` | later |
