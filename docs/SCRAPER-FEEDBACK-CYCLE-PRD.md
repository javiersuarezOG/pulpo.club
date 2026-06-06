# Scraper Feedback Cycle PRD

**Priority:** P0 developer-productivity work
**Status:** Ready for engineering pickup.
**Companion doc:** [`docs/RESILIENCE-AUDIT-PRD.md`](RESILIENCE-AUDIT-PRD.md) — the nightly resilience PRD (R1–R9) that this work complements.

## Problem

The current scraper dev cycle is "edit selectors → run nightly → wait 7 hours → see what broke." That isn't a feedback loop; it's a batch job.

A 7-hour nightly is a production soak run, not a tool for iterating on a single parser. Today every iteration on a scraper means waiting half a day to find out whether the catalog regex still matches, whether prices come through, whether dedup obliterates the new yield. Worse: a single guard exit non-zero (regression-guard, count canary, hero variant canary) discards the entire run's work — the scraper dev never even sees their parser output.

This document specifies the fast-path tooling that decouples scraper dev from the full pipeline.

## Goal

Build a scraper dev cycle where the developer can answer, in minutes:

1. Does this source fetch?
2. Does the parser extract listings?
3. Do records pass validation?
4. Do they survive dedup/ranking?
5. Would this source improve inventory count without poisoning quality?

The full nightly should become the final soak, not the thing you use to learn.

## Target feedback-loop times

| Loop | Purpose | Target time |
|---|---|---|
| Parser fixture test | Does parser still work on saved HTML? | `<10s` |
| Live source smoke | Can one source fetch + parse live? | `<2 min` |
| Source integration dry-run | Does one source survive validation/dedup/rank? | `<5 min` |
| Multi-source sampled run | Does the new source interact badly with existing ones? | `<15 min` |
| Full nightly | Production batch + deploy | Async only |

## Definition of Done

A scraper-dev workflow that runs from a clean checkout:

```bash
python3 -m pulpo.cli scraper-lab --source xitios --limit 20
pytest -q tests/scrapers/test_xitios.py
python3 automation/run.py --sources xitios --limit-per-source 50 --skip-llm --skip-photos --write-candidate /tmp/xitios
```

…and the developer knows within 5 minutes whether the scraper is good enough to PR. The nightly should only answer: "Does the whole system still work end-to-end?" It should not be the parser debugging tool.

## PR breakdown

### PR-FB-1 — Scraper Lab CLI (P0)

**Goal:** `python3 -m pulpo.cli scraper-lab --source xitios --limit 25` runs in under 2 minutes and outputs the full per-source funnel (fetched / parsed / normalized / validated / dedup_kept / ranked + failures + duration).

**Files to create / modify:**

- New: `automation/scraper_lab.py` — orchestration. Calls fetch → finalize → validate → dedup → rank in isolation.
- New: `pulpo/cli/scraper_lab.py` — subcommand handler.
- Modify: `pulpo/cli.py` — wire `scraper-lab` subcommand into the existing argparse tree.

**Reuse from existing code:**

- `pulpo/scrapers/_base.finalize_record` — already isolates the per-record finalize step.
- `automation/validation.py` — per-record validation; can run on a slice.
- `pulpo/ranker.py` — ranking; can run on a slice.
- `scripts/smoke_scraper.py` — already does the live-fetch part; refactor its core into a callable `smoke_one(slug, limit, offline)` that scraper-lab can invoke.
- `pulpo/scrapers/lib.listing_fingerprint` — dedup hashing.

**CLI surface:**

```bash
python3 -m pulpo.cli scraper-lab \
  --source xitios \
  --limit 25 \
  --skip-llm \
  --skip-photos \
  --write /tmp/pulpo-lab/xitios

# Output:
# source: xitios
# fetched: 25
# parsed: 25
# normalized: 24
# validated: 22
# dedup_kept: 21
# ranked: 21
# failures:
#   invalid:price: 1
#   invalid:photo:placeholder: 1
# duration: 74s
```

**Default behavior:**

- `--skip-llm` defaults ON (LLM enrichment is opt-in)
- `--skip-photos` defaults ON (no downloads)
- Combined defaults give the fast path
- Writes `<write_dir>/{raw.jsonl, normalized.jsonl, failures.jsonl, ranked.json}`

**Telemetry / scope:**

- No PostHog events (it's a dev tool — local only).
- No `web/data/` mutations.
- Logs everything to stdout in a script-friendly format.

**Acceptance:**

- One source can be tested live in under 2 minutes.
- Output includes raw, normalized, validation, dedup, and ranking counts.
- No LLM/photo/geocode work runs unless explicitly enabled.

### PR-FB-2 — Per-source fixture tests (P1)

**Goal:** Every scraper has saved HTML fixtures + a pytest file that exercises the parser against them. Pytest finishes in seconds.

**Directory structure:**

```
tests/fixtures/scrapers/
  xitios/
    catalog.html       (catalog page snapshot)
    detail-001.html    (representative detail page)
    detail-002.html    (another, for variety)
  santizo/
    catalog.html
    detail-001.html
  csbr/
    catalog.html
    detail-001.html
  citymax_sc/
    catalog.html
    detail-001.html
  ... etc for all 8 Phase C sources + the existing 11
```

**Test contract (one file per scraper at `tests/scrapers/test_<source>.py`):**

```python
def test_catalog_extracts_listing_urls(fixture_dir):
    scraper = XitiosScraper()
    html = (fixture_dir / "catalog.html").read_text()
    urls = scraper._extract_detail_urls_from_catalog_page(html, page_num=1)
    assert len(urls) >= 10  # site-specific lower bound

def test_detail_extracts_title_and_price(fixture_dir):
    scraper = XitiosScraper()
    html = (fixture_dir / "detail-001.html").read_text()
    record = scraper._extract_detail(html, "https://...", strategy="detail_og_meta")
    assert record["title"]
    assert record["price_usd"] > 0
    assert record["url"]

def test_placeholder_photo_rejected(fixture_dir):
    # ... per-source placeholder pattern test
```

**Files to create:**

- `tests/fixtures/scrapers/<source>/catalog.html` × 19 sources (capture from live in PR-FB-1's `--write` mode).
- `tests/scrapers/test_<source>.py` × 19 sources (extends the existing offline contract tests).
- Update: `tests/test_source_integration.py` — assert every scraper has its fixture directory + test file (similar to the existing photo_config + metadata contract).

**Reuse:**

- The 8 Phase C scrapers already have `test_<source>.py` contract tests. This PR EXTENDS them to load real HTML fixtures.

**Acceptance:**

- `pytest -q tests/scrapers/` runs in <30s.
- Each test verifies parser behavior on saved HTML without network access.
- A selector regression in any scraper fires a clear, actionable test failure.

### PR-FB-3 — Single-source pipeline dry-run (P3)

**Goal:** `python3 automation/run.py --sources xitios --limit-per-source 50 --skip-llm --skip-photos --skip-hires --skip-deploy --write-candidate /tmp/pulpo-candidate` runs in under 5 minutes and produces a mini `ranked.json` + `last_updated.candidate.json` without mutating `web/data/`.

**Files to modify:**

- `automation/run.py` — add CLI flags:
  - `--sources <comma-list>` (override which scrapers run)
  - `--limit-per-source <int>` (cap per scraper)
  - `--skip-llm` (no DeepSeek calls)
  - `--skip-photos` (no `phase_photos`)
  - `--skip-hires` (no `phase_hires`)
  - `--skip-deploy` (no Vercel)
  - `--skip-pa` (no PA pipeline)
  - `--write-candidate <dir>` (write to dir instead of `web/data/`)

**Implementation pattern:**

- Each `--skip-X` flag short-circuits the corresponding `phase_X()` function with a logged "skipped" line.
- `--write-candidate <dir>` redirects all `web/data/` writes to the specified dir. Implementation: thread `output_dir` through `phase_write_outputs` (currently around line 2323 of `automation/run.py`).
- `--sources` overrides the autodiscovery default.
- `--limit-per-source` passes through to each scraper's `crawl(limit=...)`.

**Acceptance:**

- Runs validation, dedup, ranking, shelf eligibility in <5 min for a single source.
- Does NOT mutate `web/data/`.
- Produces `<candidate_dir>/ranked.json` + `<candidate_dir>/last_updated.candidate.json`.
- Exits non-zero if the candidate is structurally invalid.

### PR-FB-4 — Scraper smoke GitHub workflow (P4)

**Goal:** Trigger remote single-source tests via `gh workflow run pulpo-scraper-smoke.yml -f source=xitios -f limit=25 -f mode=pipeline-dry-run`. Tests runner-side behavior (geo blocks, TLS handshakes, etc.) without disrupting main CI.

**File to create:** `.github/workflows/pulpo-scraper-smoke.yml`

**Workflow shape:**

```yaml
name: pulpo scraper smoke
on:
  workflow_dispatch:
    inputs:
      source:
        description: Scraper slug
        required: true
      limit:
        description: Per-source limit
        required: false
        default: "25"
      mode:
        description: fixture | live | pipeline-dry-run
        required: true
        default: live

jobs:
  smoke:
    timeout-minutes: 15
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6.0.2
      - uses: actions/setup-python@v6.2.0
      - run: pip install -r requirements.txt
      - run: |
          case "${{ inputs.mode }}" in
            fixture)
              pytest -q "tests/scrapers/test_${{ inputs.source }}.py" ;;
            live)
              python3 -m pulpo.cli scraper-lab --source ${{ inputs.source }} \
                --limit ${{ inputs.limit }} --write /tmp/lab ;;
            pipeline-dry-run)
              python3 automation/run.py --sources ${{ inputs.source }} \
                --limit-per-source ${{ inputs.limit }} \
                --skip-llm --skip-photos --skip-hires --skip-deploy \
                --write-candidate /tmp/candidate ;;
          esac
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: scraper-smoke-${{ inputs.source }}-${{ github.run_id }}
          path: |
            /tmp/lab
            /tmp/candidate
```

**Acceptance:**

- A source can be tested remotely via `gh workflow run`.
- Artifacts include raw/normalized/failure outputs.
- Failure does not block main CI (workflow is independent).
- Total wall time <15 min including setup.

### PR-FB-5 — Source delta report (P6)

**Goal:** After a scraper dry-run, produce a structured delta report: "Source delta: xitios — New valid listings: 21, Likely duplicates: 3, Rejected: 4 (by reason), Quality: …, Shelf impact: …"

**Files to create:**

- `automation/source_delta_report.py` — diff a candidate `ranked.json` against the current production `ranked.json` on main; categorize new/duplicate/rejected; compute per-shelf impact.

**Files to modify:**

- `automation/run.py` — when `--write-candidate` is set, also write `<candidate_dir>/delta_report.md`.

**Implementation reuse:**

- `pulpo/scrapers/lib.listing_fingerprint` — already produces stable per-listing hashes; reuse for duplicate detection.
- `web/data/ranked.json` on main — fetch via `git show HEAD:web/data/ranked.json` for the diff base.

**Report format:**

```
Source delta: xitios

New valid listings: 21
Likely duplicates: 3
Rejected: 4

By reason:
  invalid:photo:placeholder 2
  invalid:price 1
  duplicate:title_location_price 1

Quality:
  with price: 95%
  with location: 100%
  with usable photo: 86%
  with property_type: 100%

Shelf impact:
  beach_homes +7
  beach_land +12
  lake_homes +1
```

**Acceptance:**

- Operator can read the delta report and decide "merge this source" or "iterate" in <30s.
- Per-shelf impact surfaces inventory gain at the user-visible level.
- Quality percentages catch silent regressions (e.g. "with-price drops from 95% to 60% on a parser refactor").

### PR-FB-6 — Default-off expensive phases for scraper dev (P5)

**Goal:** Codify the dev/production mode split. During scraper dev, the expensive phases (LLM, photos, hires, geocoding backfill, PA, Vercel) should be off by default. Promote the `--skip-X` flags from PR-FB-3 to the default behavior of `python3 automation/run.py` UNLESS `--production` is passed.

**Files to modify:**

- `automation/run.py` — flip default behavior:
  - Without `--production`: skip LLM, photos, hires, geocoding-backfill, PA, deploy.
  - With `--production`: keep current full-pipeline behavior.
- `.github/workflows/pulpo-nightly.yml` — pass `--production` to the SV pipeline step.

**Risk:** If someone forgets `--production` in a manual nightly trigger, they ship a stripped-down pipeline. Mitigation: log a banner ("PRODUCTION MODE" vs "DEV MODE") at the top of the run; CI fails the nightly if DEV MODE banner appears.

**Acceptance:**

- `python3 automation/run.py --sources xitios --limit-per-source 50` produces a candidate without LLM/photos/etc.
- `python3 automation/run.py --production` matches the current full-pipeline behavior.
- Nightly workflow uses `--production` explicitly.

## Recommended execution order

```
PR-FB-1 (Scraper Lab CLI) — biggest immediate dev-cycle unlock
PR-FB-2 (per-source fixture tests) — prevents selector regressions
PR-FB-3 (single-source pipeline dry-run) — tests validation/dedup/ranking
PR-FB-4 (scraper smoke workflow) — remote runner-side behavior
PR-FB-5 (source delta report) — quality + inventory impact
PR-FB-6 (default-off phases) — codifies dev/prod split
```

PR-FB-1 alone is enough to unblock single-source iteration. PR-FB-2 prevents regressions. The rest are quality-of-life.

## Critical files reference

**New:**

- `automation/scraper_lab.py` — PR-FB-1
- `pulpo/cli/scraper_lab.py` — PR-FB-1
- `tests/fixtures/scrapers/<source>/{catalog,detail-001}.html` × 19 sources — PR-FB-2
- `tests/scrapers/test_<source>.py` (extended) × 19 — PR-FB-2
- `automation/source_delta_report.py` — PR-FB-5
- `.github/workflows/pulpo-scraper-smoke.yml` — PR-FB-4

**Modified:**

- `pulpo/cli.py` — wire scraper-lab subcommand (PR-FB-1)
- `automation/run.py` — add `--skip-X` flags + `--write-candidate` (PR-FB-3), flip defaults to dev mode (PR-FB-6)
- `tests/test_source_integration.py` — assert fixture dir per source (PR-FB-2)

## Verification per PR

**PR-FB-1:** `time python3 -m pulpo.cli scraper-lab --source xitios --limit 25 --write /tmp/lab` finishes in <120s. `/tmp/lab/normalized.jsonl` has 20–25 records. `/tmp/lab/failures.jsonl` shows categorized rejects.

**PR-FB-2:** `time pytest -q tests/scrapers/` finishes in <30s. Manually corrupting a scraper's selector (rename a regex capture group) produces an actionable failure.

**PR-FB-3:** `time python3 automation/run.py --sources xitios --limit-per-source 50 --skip-llm --skip-photos --skip-hires --skip-deploy --write-candidate /tmp/c` finishes in <5min. `/tmp/c/ranked.json` has 20–50 records with valid structure. `web/data/` is untouched.

**PR-FB-4:** `gh workflow run pulpo-scraper-smoke.yml -f source=xitios -f mode=live -f limit=10` completes; artifact contains raw/normalized output.

**PR-FB-5:** After PR-FB-3 ships, `--write-candidate` includes `<dir>/delta_report.md` with the expected sections.

**PR-FB-6:** `python3 automation/run.py --sources xitios --limit-per-source 50` defaults to dev mode (no LLM/photos); production behavior requires explicit `--production`.

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PR-FB-1 misses an important pipeline phase (e.g. photo_contract validation) | Med | Med | Mirror the phases run by the nightly's `Run pipeline` step exactly; document each `--skip-X` flag's blast radius |
| PR-FB-2 fixture files bloat the repo | Low | Low | Each HTML file ~50–200KB; 19 sources × 2–3 files = ~10MB total, acceptable |
| PR-FB-3's `--write-candidate` lets a developer accidentally ship a stripped candidate | Low | High | Acceptance: nightly's commit step refuses to commit if `last_updated.candidate.json` lacks a `production_run=true` marker |
| PR-FB-4 GitHub Actions runner-hours add cost | Low | Low | `workflow_dispatch` only; not on schedule; each run ~10–15 min |
| PR-FB-5 delta report bottlenecks on `git show HEAD:web/data/ranked.json` for huge files | Low | Low | Stream + cap; current ranked.json is ~5MB, well within limits |
| PR-FB-6's default-off mode silently degrades a real nightly | Med | High | Banner at top of run; CI fails if DEV MODE banner appears in a scheduled nightly run |

## Out of scope

- Full nightly phase split — deferred to R3 in `docs/RESILIENCE-AUDIT-PRD.md`.
- Hot-reload / file-watcher mode for `scraper-lab` — could add `--watch` later but not in PR-FB-1.
- IDE plugin integration.
- Migrating existing scrapers' offline tests to use the fixture-based pattern — call this out in the PR-FB-2 body as a follow-up; new scrapers MUST follow the pattern.
- Multi-source dry-run is automatic via PR-FB-3's `--sources xitios,santizo`.

## Relationship to the Resilience Audit PRD

The two PRDs are complementary, not competing:

- **This PRD (Scraper Feedback Cycle)** shortens the dev cycle so engineers can iterate on individual scrapers in minutes instead of hours.
- **`docs/RESILIENCE-AUDIT-PRD.md` (Resilience Audit)** ensures the full nightly preserves valid work even when one guard fails — so a single failure in production doesn't strand a day's catalogue.

PR-FB-3 (single-source pipeline dry-run) reuses the same `--write-candidate` pattern that R1 (durable candidate before guards) introduces. Both should land in a way that converges on a single `automation/candidate_bundle.py` abstraction.

## Hand-off note

The execution order across both PRDs:

1. **Workstream A (this PRD)** is the developer-productivity track. PR-FB-1 first.
2. **Workstream B (Resilience Audit PRD)** is the production-safety track. R1 first.
3. They're independent — different engineers can pick up each track.
4. R3 (workflow phase split) eventually subsumes PR-FB-6 (default-off phases); coordinate so they don't conflict.
