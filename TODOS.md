# TODOs / Backlog

This file tracks deferred work that's intentionally out-of-scope of an active PR but should not be forgotten. Each item has a stable identifier (in square brackets) so other PRs / commits can reference it.

## Photo pipeline

- **[hires-retirement]** After 2 weeks of clean hires-pipeline operation, decide whether to retire the legacy `.jpg` thumbnail and `.hero.jpg` derivatives. The hires pipeline ships parallel/additive to those by design (see plan v2). Retirement is a separate decision with its own validation window.
- **[hires-coverage]** Implement URL rewrite for goodlife (`-WxH` WordPress size-suffix strip) and encuentra24 (Cloudinary `t_or_fh_m` → `t_full`). Verify a sample of 5 URLs per source returns ≥1080×1080 bytes BEFORE adding the source to `PULPO_HIRES_SOURCES`. The transform skeleton is already in `automation/hires_url_transform.py`.
- **[hires-concurrency]** Phase 1 ships serial. Add async fan-out (`httpx.AsyncClient` with `asyncio.Semaphore(4)`) if `PULPO_HIRES_BUDGET_S` proves chronically insufficient. Watch the `wall_clock_s` field in `web/data/hires_pipeline_metrics.jsonl` over the first 2 weeks.
- **[hires-storage]** If `web/photos-hires/` growth becomes unmanageable (>1 GB or Vercel deploy size hits the cap), migrate to Vercel Blob or Cloudflare R2. The `_download_hires_photos` write path is the only producer; the `api/social/image.js` candidate list is the only consumer — both behind small abstractions, easy swap.
- **[hires-aesthetic-llm]** The deterministic aesthetic scorer (edge-Gini + color entropy + corner watermark + OCR) is in scope for the nightly. LLM-based aesthetic scoring (`pulpo-social/packages/photo-quality/src/core/aesthetic.ts`) is NOT — it requires either a Python parity port or a Node subprocess bridge from the Python pipeline. Defer until/unless deterministic scoring proves insufficient at distinguishing publication-worthy photos.
- **[hero-rank-order]** Audit `automation/run.py:_download_hero_photos` (lines 209-411) for explicit `sort by rank_score desc` before iteration. Without that, a budget overrun produces a random slice of listings rather than the highest-value ones. Recommend a small separate PR if missing.
- **[hires-validate-cli]** Add a `python -m pulpo.cli validate-hires` subcommand that runs resdet over `web/photos-hires/*.hires.jpg` and reports the upscale rate. Useful as a pre-deploy guardrail and for spot-checks between nightly runs. Re-uses the vendored resdet binary that the in-nightly QC step depends on.

## Other

(Add new sections here as backlog grows.)
