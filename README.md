# pulpo.club — Phase 1

Salvadoran beach + raw-land aggregator. Scrapes boutique-broker sites, normalizes mixed units (vrs² / manzanas / m² / acres), ranks every listing on a four-factor investment score, exposes the shortlist behind a username/password gate, and ships a weekly Wednesday refresh.

## Layout

```
pulpo-sv/
├── pulpo/
│   ├── units.py          # vara/manzana/m²/acre conversions + parsers
│   ├── models.py         # Listing dataclass + to_public_dict() teaser serialization
│   ├── normalize.py      # raw scrape dict → Listing (with zone snapping)
│   ├── ranker.py         # multi-factor composite + 1-based position rank
│   ├── cli.py            # python -m pulpo.cli
│   └── scrapers/         # base + per-site (goodlife, oceanside, kazu, century21, remax)
├── automation/
│   ├── run.py            # single-command pipeline runner (cron / GHA entrypoint)
│   ├── add_user.js       # bcrypt user-line generator for the USERS env var
│   └── cron_local.sh     # self-hosted alternative to the GitHub Action
├── api/                  # Vercel serverless functions
│   ├── _auth.js          # cookie + bcrypt helpers
│   ├── login.js          # POST /api/login
│   ├── members.js        # GET  /api/members  (full ranked.json behind auth)
│   └── logout.js         # POST /api/logout
├── web/
│   ├── index.html        # static dashboard (auto-degrades public ↔ member)
│   └── data/
│       ├── ranked.json         # FULL — only served via /api/members
│       ├── ranked-public.json  # broker/url/exact-price stripped, safe to serve
│       └── last_updated.json
├── fixtures/sample_listings.json   # 15 realistic SV listings for offline runs
├── samples/ranked.csv              # generated CSV with all rank columns
├── tests/test_units.py             # unit-conversion + parser tests
├── assets/                         # pinwheel logo (SVG)
├── .github/workflows/pulpo-weekly.yml
├── vercel.json
├── package.json
└── requirements.txt
```

## Quick start

```bash
# Offline pipeline run (no deps required)
python3 -m pulpo.cli --offline

# Live scrape — install deps first
pip install -r requirements.txt
python3 -m pulpo.cli --source goodlife --limit 20

# Or any single source — registry: goodlife, oceanside, kazu, century21, remax
python3 -m pulpo.cli --source century21 --limit 20

# Full pipeline (writes web/data/*.json + samples/ranked.csv)
python3 automation/run.py

# Tests
python3 tests/test_units.py

# Mint a member account (interactive prompt for the password)
node automation/add_user.js alice
# → paste the printed line into the USERS env var on Vercel
```

## How the pipeline works

1. **Crawl** — each scraper module pulls index pages, then visits each detail page. Falls back to `fixtures/sample_listings.json` when `httpx`/`selectolax` aren't installed or `PULPO_OFFLINE=1` is set.
2. **Normalize** — turns each raw dict into a canonical `Listing`. Parses Salvadoran units ("30 manzanas", "800 vrs²", "10,500 m²"), parses prices ("$1.5M", "US$ 250,000", "$250k"), snaps the location text to a canonical zone slug.
3. **Rank** — computes the four-factor composite below, sorts descending, assigns a 1-based position rank where `rank=1` is the strongest opportunity.
4. **Output** — emits `samples/ranked.csv`, the full `web/data/ranked.json` (members only) and the stripped `web/data/ranked-public.json` (public teaser).

## The investment-attractiveness model

A pure "cheap-for-zone" scorer punishes prime-location plays at fair price and rewards cheap parcels in zones nobody is buying — the classic real-estate trap where a nominal discount masks an exit-risk problem. Institutional underwriting decomposes the question into four legs, and `pulpo/ranker.py` does the same.

### The four legs

| Leg | Default weight | What it measures | Source signal |
|---|---|---|---|
| **Value** | 35% | Price vs. comparable sales | $/m² percentile within comp pool (zone → macro-zone → global cascade) |
| **Quality** | 25% | Locational tier + physical attributes | A/B/C zone tier + beachfront, paved access, water, power |
| **Liquidity** | 20% | Exit-risk proxy | Zone activity score adjusted by days-on-market and repricing motion |
| **Upside** | 20% | Path-of-progress / growth headroom | Per-zone growth-corridor score; bonuses for beachfront and subdividable scale in growth zones |

Each leg returns 0..100, then they combine: `composite = wv·V + wq·Q + wl·L + wu·U`. Composite is converted to a 1-based position rank for display.

### Why this answers the prime-A-vs-cheap-B question

The four-factor decomposition makes the trade-off legible. A prime A-tier El Tunco lot at fair price will lose on **value** (it's not cheap relative to its comp pool) but win on **quality** (A-tier zone, beachfront premium, infrastructure) and **liquidity** (deep buyer pool, fast exit). A "cheap" Conchagua interior parcel will win on **value** but lose on **quality** and **liquidity**. A Conchagua *beachfront* parcel benefits from a Gulf-of-Fonseca **upside** boost (port + Bitcoin City thesis).

The composite picks a winner; the table also surfaces all four component scores side-by-side so you can override the algorithm with judgment. Six investors with the same data should be able to agree on *why* a listing scored 80 even when they disagree on whether 80 is enough to buy.

### Tuning the thesis

The dashboard exposes a live weights tuner — drop **value** to 0.10 and crank **upside** to 0.50 and the leaderboard reshuffles toward path-of-progress plays. The CLI / cron pipeline accepts the same overrides:

```bash
PULPO_W_VALUE=0.10 PULPO_W_QUALITY=0.20 PULPO_W_LIQUIDITY=0.20 PULPO_W_UPSIDE=0.50 python3 automation/run.py
```

Weights renormalize, so they don't have to sum to 1.0.

### Worked example (from the live offline run)

```
 #  composite   V    Q    L    U   zone        price       $/m²   title
 1     84.8   100   75   70   85   mizata      $250,000    $17.89  2 mz Playa Mizata frente al mar (REPRICED)
 2     83.2   100   65   75   85   el-cuco     $400,000    $11.45  5 mz El Cuco zona segunda línea
 3     82.4    83   89   95   60   el-tunco    $300,000    $21.46  2 mz El Tunco 200m off beach (REPRICED)
 4     76.6    67   89   90   65   el-zonte    $250,000    $35.77  1 mz El Zonte vista al mar (REPRICED)
 5     76.1    67   79   70   95   el-cuco   $3,000,000    $14.31  30 mz beachfront El Cuco — paved access
 6     73.2    50   99   85   70   el-zonte  $1,200,000    $57.23  3 mz beachfront El Zonte
 7     72.2   100   45   35   95   conchagua   $500,000     $1.43  50 mz Conchagua con vista al Golfo
```

#3 is the answer to "should I buy a prime A-location lot at fair price?" — Tunco at $21.46/m² isn't a value play (V=83), but the A-tier quality (89) and liquidity (95) push it to #3 above several cheaper-but-less-liquid alternatives. #5 is the case for a single big A-zone bet over multiple cheap B-zone parcels: 30 manzanas of beachfront El Cuco at $14.31/m² wins on upside (95) because of subdividability into a growth corridor.

## Auth model (no Stripe — manual account issuance)

* `web/index.html` calls `/api/members` first. If the cookie is valid → full `ranked.json` is loaded; if not → falls back to the public teaser bundle and shows a login form.
* `/api/login` accepts `{username, password}` JSON, bcrypt-compares against the `USERS` env var, sets an HMAC-signed `pulpo_sess` cookie (HttpOnly + Secure + SameSite=Lax, 14-day expiry).
* `vercel.json` redirects any direct hit on `/data/ranked.json` to `/api/members` so the file can never be served statically — only the public bundle is.
* `automation/add_user.js` mints `username:bcryptHash` lines for pasting into the `USERS` env var. No DB, no migrations.

```bash
# Generate session secret
node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))"
# Paste into Vercel as SESSION_SECRET

# Add a user
node automation/add_user.js javier
# Paste the printed line into the USERS env var (comma-separated if extending)
```

## Public vs member fields

| Field | Public teaser | Member |
|---|---|---|
| `rank`, `rank_score`, `value/quality/liquidity/upside_score` | ✓ | ✓ |
| `zone`, `municipality`, `department`, `area_m2`, `raw_size_text` | ✓ | ✓ |
| `is_beachfront`, `has_paved_access`, `has_water`, `has_power`, `is_repriced`, `days_listed`, `photos_count` | ✓ | ✓ |
| `title` (truncated to 60 chars, broker name stripped) | ✓ | full title |
| `price_band` (e.g. `$250k–$500k`) | ✓ | – |
| `price_usd`, `price_per_m2`, `raw_price_text` | – | ✓ |
| `broker_name`, `broker_phone`, `broker_email` | – | ✓ |
| `url`, `source`, `source_id`, `description` | – | ✓ |

Coordinates are coarsened to ~1 km grid in the teaser.

## Deploy (Vercel)

1. Push the repo to GitHub.
2. In Vercel: New Project → import the repo → no build command needed.
3. Set env vars: `SESSION_SECRET` (32+ chars) and `USERS` (comma-separated bcrypt lines).
4. Point `pulpo.club` at the Vercel project (Add Domain).
5. The GitHub Action (`.github/workflows/pulpo-weekly.yml`) runs every Wednesday 06:00 SV, refreshes `web/data/*.json`, commits the changes back, and a redeploy fires automatically.

## Scraping reliability — current state (be honest)

The scrapers in `pulpo/scrapers/*.py` are **scaffolding, not validated**. They use best-effort selectors against common WordPress real-estate-plugin DOM patterns (Estatik, IMPress Listings, RealHomes, Houzez), and the entire pipeline currently runs in `PULPO_OFFLINE=1` mode against `fixtures/sample_listings.json`.

Before treating the live numbers as trustworthy, this work is required (tracked as task #28):

1. **Selector calibration** — for each of `goodlife`, `oceanside`, `kazu`, `century21`, `remax`: save 3–5 detail-page HTML snapshots, iterate `DETAIL_*_SEL` constants until ≥95% field coverage on title, area, price, location, photos, broker. `goodlife` and `oceanside` are calibrated (2026-04-28); the other three are scaffolding pending samples.
2. **Health check** — daily smoke test that fails CI if any source returns 0 listings; alert on degradation.
3. **JS-rendered fallback** — if any of the three sites use client-side rendering, swap to Playwright headless. The `BaseScraper` interface is designed so this is a single-module change.
4. **Anti-bot graceful failure** — backoff on 429/403; never spam.
5. **Per-source confidence flag** — tag each scraped record `full | partial | fallback` so the dashboard can mark calibration regressions.

What we *can* commit to once calibrated: weekly Wednesday refresh, with a fixture-fallback path that keeps the dashboard up even if one source breaks. Phase 2 adds Postgres for diff-based repricing detection (right now `is_repriced` is read from raw, not diffed) and Mapbox geocoding.

## What's not in this repo (intentionally — Phase 2+)

- Postgres + dedup
- Mapbox geocoding
- Encuentra24 + Propi scrapers (high-volume targets, harder than boutique sites)
- Newsletter rendering, Beehiiv migration, Stripe paywall

## Verification

`python3 tests/test_units.py` covers unit-conversion math, parser robustness (varias formats of `vrs²`, mixed thousands separators, prefix tokens like "Lot:"), and the El Cuco worked example ($3M / 30mz = $14.31/m²). The committed `samples/ranked.csv` is the actual end-to-end output against the fixture set.
