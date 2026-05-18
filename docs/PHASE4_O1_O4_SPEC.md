# Phase 4 — O1 (full-resolution scrape) + O4 (per-source dashboards)

**Status:** spec, not implemented. Hand-off doc for the dev picking these
up. Plan reference: `~/.claude/plans/the-last-automatic-post-refactored-island.md`
§4.1 / §4.5. Companion to PRs #261 (U1 hero re-escalation), #268 (U3
Qwen3-VL aesthetic booster), and pulpo-social #40 (L4 CRAFT precheck).

These two items share a config file and want to land as separate PRs in
the order **O1 → O4** so the dashboard reflects the post-O1 cohort
rather than baking in pre-O1 noise.

---

## Context — why these matter

Phase 4 U1 (hero re-escalation, PR #261) and U3 (Qwen3-VL aesthetic
booster, PR #268) made the **picker** smarter. They both operate on
`photo_urls` as provided by each scraper today. Two ceilings remain:

1. **Source resolution.** No downstream gate can manufacture detail
   that was never scraped. Most source sites publish multiple image
   sizes per listing; the scrapers currently grab whichever variant
   the listing page surfaces by default — often a card thumbnail.
   Per-site URL transforms unlock the full-res variant when one
   exists. This is O1.

2. **Per-site visibility.** Today there's no aggregate view of which
   source sites supply consistently bad photos. The operator has no
   way to deprioritize a site whose median hero photo is poor, and
   no way to set per-site thresholds (a site that maxes out at 1200px
   shouldn't be gated against the same 1080-everywhere floor as one
   that publishes 4K). This is O4.

Together they close the loop: O1 raises the resolution floor where
possible, O4 surfaces where it's still failing.

---

## Shared artifact — `pulpo/scrapers/photo_config.json`

Both items consume this single file. Land it in **O1's PR**; **O4**
extends the schema.

### Schema

```json
{
  "$schema": "./photo_config.schema.json",
  "version": 1,
  "sources": {
    "remax": {
      "full_res": {
        "strategy": "url_replace",
        "rules": [
          {
            "match": "/_thumb/",
            "replace": "/_large/",
            "comment": "RE/MAX gallery thumbs live under /_thumb/; /_large/ is the same file at ~1920px."
          },
          {
            "match": "(_\\d+x\\d+)\\.jpg$",
            "replace": ".jpg",
            "regex": true,
            "comment": "Strip dimension suffix (e.g. _600x400.jpg → .jpg) to fetch the original."
          }
        ],
        "validate_via_head": true
      },
      "min_source_long_side_px": 1920,
      "deprioritize_weight": 1.0
    },
    "bienesraices": {
      "full_res": {
        "strategy": "field_swap",
        "rules": [
          {
            "from_field": "featured_image",
            "to_field": "image_wm",
            "comment": "The site's JSON payload has a watermark-free variant under image_wm with higher resolution."
          }
        ]
      },
      "min_source_long_side_px": 1600,
      "deprioritize_weight": 1.0
    },
    "goodlife": {
      "full_res": {
        "strategy": "wordpress_size_strip",
        "rules": [
          {
            "match": "-\\d+x\\d+(\\.[a-z]+)$",
            "replace": "$1",
            "regex": true,
            "comment": "WordPress generates size variants per upload. Stripping the -WIDTHxHEIGHT suffix yields the original."
          }
        ]
      },
      "min_source_long_side_px": 1280,
      "deprioritize_weight": 1.0
    }
  },
  "defaults": {
    "min_source_long_side_px": 1080,
    "deprioritize_weight": 1.0,
    "validate_via_head": false
  }
}
```

**Field definitions:**

- `sources.<name>.full_res.strategy` — one of:
  - `url_replace` — apply each rule's `match` → `replace` against the
    URL string. Rules apply in order; first match wins per rule. Set
    `regex: true` to treat `match` as a regex (default literal).
  - `field_swap` — only meaningful when the scraper consumes a JSON
    payload (e.g. bienesraices' `gallery_image` field). Swap a low-res
    field for a high-res sibling.
  - `wordpress_size_strip` — convenience preset for WP-Media-generated
    size variants. Equivalent to a single regex `url_replace` rule
    against `-WIDTHxHEIGHT` suffixes.
- `sources.<name>.full_res.validate_via_head` — when `true`, the
  scraper issues a `HEAD` against the upgraded URL before substituting.
  Falls back to the original URL on `>= 400` or timeout. Default
  `false` — most sites don't 404 on a wrong size, so the HEAD round-
  trip is wasted bandwidth. Set per-site after observing 404s in
  practice.
- `sources.<name>.min_source_long_side_px` — per-site override for the
  source-dimension pre-filter consumed by O4 (and existing
  `_pick_best_photo_url` candidates can be filtered with this in
  follow-up; see "Out of scope" below).
- `sources.<name>.deprioritize_weight` — multiplier applied to the
  composite hero score when this site supplies the photo. `< 1.0`
  drops the site below peers; `> 1.0` boosts. Operator knob set
  during O4 review. Default `1.0` (no effect).
- `defaults` — fallback values for sites without an explicit entry.
  Today's `defaults.min_source_long_side_px` (1080) keeps current
  behavior for sites the operator hasn't characterized.

The schema MUST validate via `pulpo/scrapers/photo_config.schema.json`
(JSON Schema draft 2020-12). Add a tiny test in `tests/test_photo_config.py`
that loads the JSON, validates it against the schema, and asserts every
configured source name is one of the 7 scraper module names listed in
`pulpo/scrapers/`.

---

## O1 — Per-site full-resolution scrape config

### Goal

For every source site listed in `pulpo/scrapers/`, the
`photo_urls` list returned to `automation/run.py` contains the
highest-resolution variant the source publicly exposes.

### Files to touch

1. **New:** `pulpo/scrapers/photo_config.json` — schema above, fully
   populated for all 7 sites (remax, bienesraices, century21,
   encuentra24, goodlife, nexo, oceanside, realtyelsalvador).
2. **New:** `pulpo/scrapers/photo_config.schema.json` — JSON Schema for
   the config.
3. **New:** `pulpo/scrapers/_photo_url_upgrade.py` — single shared
   helper module:
   - `load_photo_config() -> dict` (cached at module load)
   - `upgrade_photo_urls(source: str, urls: list[str], payload: dict | None = None) -> list[str]`
     — applies the configured strategy. `payload` carries the parsed
     site response when `field_swap` is used (e.g. bienesraices'
     `prop` dict).
   - `_apply_url_replace(url, rules) -> str`
   - `_apply_field_swap(payload, rules) -> dict` (returns a possibly-
     mutated copy of the listing's photo source field list)
   - The module MUST be import-safe with no network calls at import
     time. HEAD validation lives inside `upgrade_photo_urls` and is
     opt-in per the config.
4. **Modify:** each of `pulpo/scrapers/remax.py`, `bienesraices.py`,
   `goodlife.py`, `century21.py`, `encuentra24.py`, `nexo.py`,
   `oceanside.py`, `realtyelsalvador.py` — after the existing
   `photo_urls` assembly block, call:
   ```python
   from pulpo.scrapers._photo_url_upgrade import upgrade_photo_urls
   photo_urls = upgrade_photo_urls("<source-name>", photo_urls, payload=<parsed-dict-or-None>)
   ```
   No other scraper logic changes. Resolution upgrade is the ONLY
   responsibility of this hook — text-overlay detection,
   compute_score, etc. continue to live in `automation/run.py`.
5. **New:** `dev/audit_photo_resolutions.py` — operator script.
   - Reads `web/data/listings_history.json` for the 9 May-15-17
     fixtures (IDs hard-coded; same list as
     `pulpo-social/test_images/may-15-17-rejected/GRADES.md`).
   - For each, re-scrapes the listing fresh, applies `upgrade_photo_urls`,
     and `HEAD`s the first `photo_url` to read `Content-Length`.
     Probes width via the `Image.open(... .convert("RGB")).size` path
     after fetching the smallest possible byte range. (Practical:
     just fetch the first 8 KB — Pillow can read dimensions from the
     JPEG SOF marker without the full file.)
   - Prints a table:
     ```
     source_id                                 before_long_side  after_long_side  delta
     remax__003094257004                       1080              1920             +840
     bienesraices__2059                         800              1600             +800
     ...
     ```
   - Exit code 0 when ≥ 7/9 fixtures have `after_long_side >= 1920`,
     1 otherwise. Use this as the acceptance gate.
6. **New test:** `tests/test_photo_url_upgrade.py` — 4 tests:
   - Each strategy (`url_replace`, `field_swap`, `wordpress_size_strip`)
     produces the expected upgraded URLs against fixture inputs.
   - An unknown source falls through to `defaults` and returns the
     original URLs unchanged.
   - `validate_via_head=true` with a mocked `HEAD` returning 404 falls
     back to the original URL.
   - Schema validation: loading `photo_config.json` validates against
     `photo_config.schema.json`.
7. **Modify:** `automation/run.py` — none, ideally. The scraper hook
   pushes the upgrade in-place. If a follow-up wants to apply the
   per-site `min_source_long_side_px` as a candidate pre-filter,
   leave that for a separate PR after O4 data lands.

### Acceptance criteria

- [ ] `python dev/audit_photo_resolutions.py` exits 0 against the 9
      May-15-17 fixtures. Document any site that genuinely doesn't
      publish ≥ 1920px (acceptable to ship at the source's ceiling).
- [ ] `pytest tests/test_photo_url_upgrade.py` — all 4 tests pass.
- [ ] `pytest tests/test_scraper*.py tests/test_photos.py` — no regression.
- [ ] A nightly pipeline run after deploy populates
      `web/photos/<source>_<id>.hero.jpg` with `long_side >= 1600` for
      at least 70% of new listings (instrumentation lands in O4; until
      then operator inspects 10 random files).
- [ ] No new network calls in the per-listing hot path unless
      `validate_via_head=true` is set for that source.

### Risk + mitigation

- **A wrong transform breaks a site's photo path.** Mitigation:
  every strategy supports `validate_via_head: true` so the scraper
  can verify the upgraded URL exists before substituting. Enable per-
  site during a 1-day soak after first deploy, then turn off once
  the URL pattern is confirmed stable.
- **Source site changes their URL pattern.** Mitigation: the audit
  script (`dev/audit_photo_resolutions.py`) is the canary — schedule
  it as a weekly cron via GitHub Actions and surface failure in
  Slack. (Out of scope for this PR; spec follow-up.)

### Out of scope

- Per-site rate limiting / proxy support.
- The `min_source_long_side_px` knob is *declared* in the config but
  not yet *enforced* in `_pick_best_photo_url`. Wiring is a small
  follow-up after O4 data confirms which sites need a tighter floor.
- Scraper changes to extract MORE photo URLs per listing (multi-photo
  exposure to pulpo-social is plan item O2 — a separate spec).

---

## O4 — Per-source photo quality dashboard

### Goal

Operator sees per-source aggregate photo-quality metrics on a single
admin page, refreshed nightly, so they can deprioritize sites that
consistently supply low-quality photos and tune
`min_source_long_side_px` per source.

Prerequisite: **O1 has landed and at least 3 nightly cycles have run
post-deploy.** This gives the dashboard a clean cohort to aggregate.

### Files to touch

1. **New:** `automation/source_photo_stats.py` — pure aggregation
   module.
   - `compute_source_stats(repo: Path) -> dict` — walks
     `web/photos/*.hero.jpg.meta.json` sidecars (the canonical
     source of per-photo verdicts post-U1) plus the corresponding
     thumbnail sidecars, groups by source prefix (`{source}_{id}.jpg`
     → `source = "remax"` etc.), and produces:
     ```python
     {
       "computed_at": "2026-05-25T10:00:00Z",
       "sample_window_days": 14,
       "sources": {
         "remax": {
           "sample_size": 187,
           "median_quality_score": 62,
           "p90_quality_score": 88,
           "median_long_side_px": 1920,
           "median_bytes_per_pixel": 0.18,
           "hero_eligible_ratio": 0.91,
           "rejection_rate": 0.06,
           "text_overlay_flagged_ratio": 0.04,
           "aesthetic_mean": null
         },
         ...
       },
       "total_listings_sampled": 1247
     }
     ```
   - `aesthetic_mean` is non-null only when U3 has been on for the
     sample window (read from `web/data/llm_vision_budget.jsonl`
     keyed by hero file via the `winning_url` field already persisted
     in hero meta sidecars). Pure read; never invokes the LLM here.
   - `rejection_rate` = (listings whose newest hero failed
     `hero_eligible`) / sample_size. Sourced from the per-file
     sidecars.
   - `text_overlay_flagged_ratio` = (hero meta with
     `has_text_overlay == True`) / sample_size.
2. **Modify:** `automation/run.py` — at the END of `run.py`'s main
   `cmd_pipeline()` flow (after photo download), call:
   ```python
   from automation.source_photo_stats import compute_source_stats
   stats = compute_source_stats(REPO_ROOT)
   (REPO_ROOT / "web" / "data" / "source_photo_stats.json").write_text(
       json.dumps(stats, indent=2) + "\n", encoding="utf-8"
   )
   ```
   So the file refreshes once per nightly run alongside other
   `web/data/*.json` outputs.
3. **New:** `web/app/admin/photo-stats/page.tsx` (or `.jsx` to match
   project style) — admin-only React page:
   - Reads `/data/source_photo_stats.json` at request time (same
     pattern as other admin pages that consume `web/data/*.json`).
   - Renders a sortable table with one row per source. Columns:
     `Source | Sample | Median score | Hero-eligible % | Rejection % | Text-overlay % | Median long-side | Aesthetic mean`.
   - Default sort: `rejection_rate desc` (worst-quality sites first).
   - Conditional cell colors: green if `median_quality_score >= 70`,
     amber 40-69, red < 40. Same scheme on `hero_eligible_ratio`
     (green > 0.85, amber 0.6-0.85, red < 0.6).
   - Footer link: "Open `photo_config.json`" (relative GitHub URL) so
     the operator can adjust `deprioritize_weight` / `min_source_long_side_px`
     directly from the dashboard view.
   - Behind the existing admin-auth gate (Clerk session check; same
     pattern as `web/app/admin/*` siblings).
4. **New:** `tests/test_source_photo_stats.py` — 3 tests:
   - Hand-crafted fixture directory with 5 sidecar JSONs across 2
     sources produces the expected aggregate (medians, ratios).
   - Empty directory returns `{"sources": {}, "total_listings_sampled": 0}`.
   - A sidecar with malformed JSON is skipped silently (matching
     `_read_sidecar` policy in `automation/run.py`).
5. **No new dependencies.** The aggregation is pure stdlib + Pillow-
   free (sidecars carry the dimensions already). The admin page reuses
   existing UI components (`Table` / `Badge` from `web/components/`).

### Acceptance criteria

- [ ] `pytest tests/test_source_photo_stats.py` — all 3 tests pass.
- [ ] Nightly run produces `web/data/source_photo_stats.json` with
      a non-empty `sources` dict (assuming ≥ 1 listing was scraped).
- [ ] `/admin/photo-stats` renders the dashboard with the live data,
      sorted by `rejection_rate desc` by default.
- [ ] Color thresholds in the UI are unit-testable (extract the
      classification helper into a pure function exported from
      the page module; test in `web/app/admin/photo-stats/__tests__/`).
- [ ] Per-source `deprioritize_weight` round-trips through
      `photo_config.json` and is consumed by the existing composite
      sort in `automation/run.py::_pick_best_photo_url` (multiply the
      composite score by `deprioritize_weight` after the
      aesthetic-blend step). This adds a one-line lookup in the
      picker; the helper from O1's `_photo_url_upgrade.py` already
      loads the config so a sibling helper `source_weight(source)`
      lives there too.

### Risk + mitigation

- **Sidecar drift.** If `compute_image_metadata` changes its output
  shape, the aggregator silently produces wrong numbers. Mitigation:
  the stats module reads only the fields it needs (`width`, `height`,
  `file_size_kb`, `hero_eligible`, `has_text_overlay`,
  `hero_photo_quality_score`) and skips missing-field rows with a
  per-source counter `meta_incomplete`. The dashboard surfaces this
  counter so missing-fields surface visibly instead of silently.
- **Stale stats during partial nightly runs.** When the nightly job
  bails halfway, the JSON file might reflect a partial cohort.
  Mitigation: write atomically (tmp file + rename), and include
  `computed_at` so the dashboard can show "last updated 14h ago"
  with an amber warning when > 48h.

### Out of scope

- Live (in-flight) per-source metrics — this is a nightly aggregate.
- Time-series charts (deltas week-over-week). Add later if the static
  snapshot turns out to be insufficient.
- Automatic alerting on `rejection_rate` spikes. Operator-driven for
  now.
- Cross-source comparisons against industry baselines (manual context
  only; not data we have).

---

## Dependency graph (recap)

```
   O1 (full-res scrape per site, photo_config.json)
       │
       ▼  (≥ 3 nightly cycles to populate sidecars)
   O4 (per-source dashboard, reads sidecars + photo_config)
       │
       ▼
   Per-site min_source_long_side_px wiring  ← follow-up PR
       │
       ▼
   Per-site deprioritize_weight feedback loop ← follow-up PR
```

---

## Hand-off checklist for the dev

- [ ] Read this doc + the plan section linked at the top.
- [ ] Read `automation/run.py::_pick_best_photo_url` (U1 anchor) and
      `automation/photo_quality.py::compute_image_metadata` (sidecar
      shape) before touching code.
- [ ] Open O1 PR alongside the `photo_config.json` + 7 scraper edits.
      Keep the diff per scraper to ≤ 5 LOC (one import + one call).
- [ ] Soak O1 for ≥ 3 nightly cycles on production. Confirm no
      spike in `photo_fetch_log.jsonl` errors.
- [ ] Open O4 PR with the aggregator + admin page. Verify it renders
      stats covering the post-O1 cohort, not the pre-O1 baseline.
- [ ] Final review: confirm `deprioritize_weight` round-trips end-to-end
      (operator edits the JSON → next nightly picks photos with the
      new weighting → dashboard reflects the shift).

If any spec point conflicts with code reality (e.g. a scraper's
photo-URL pattern doesn't fit any of the three strategies), file an
addendum in this doc rather than diverging silently.
