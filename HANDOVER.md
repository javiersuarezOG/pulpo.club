# Handover — pulpo.club new-UX rollout

**Date:** 2026-05-07
**Last working session:** Claude Opus 4.7 (1M context) — shipped PR-4c through PR-136 across one session.
**Status:** mid-rollout, ~70% through the master plan in `~/.claude/plans/use-the-ux-fluffy-cocke.md`.

## Read these in order

1. **`CLAUDE.md`** in the repo root — Sebastian's rules (never push to main, always `--auto --squash`, frontend conventions, mandatory null-safety + smoke-test rules).
2. **`~/.claude/plans/use-the-ux-fluffy-cocke.md`** — master plan. PR-9 onward is what's next.
3. **This file** — current state + what to do next.

## Recently shipped (this session)

| PR | Title | Status |
|---|---|---|
| #124 | PR-4c · Magazine carousel + live header stats + vrs² toggle | merged |
| #125 | PR-5 · Detail-panel telemetry + lightbox a11y | merged |
| #126 | PR-6 · ES coverage + a11y polish (prefers-reduced-motion) | merged |
| #127 | PR-4d · Discover density + carousel polish | merged |
| #128 | PR-7 · Backend derives: source_type + previous_price + regression guard | merged |
| #129 | PR-4e · Discover density take 2 (3 real bugs from PR-4d) | merged |
| #130 | fix · Browse default `price_max=null` (873 listings, not 700) | merged |
| #131 | PR-4f · Interactive PriceHistogram (range slider) | merged |
| #132 | PR-7.5 · Bilingual DeepSeek prompt + url_language | queued (had merge conflict, resolved) |
| #133 | PR-7.6 · Photo quality scoring + featured pick | merged |
| #134 | PR-8 · Bilingual NLP keywords + 6 new dictionaries + enum derives | queued |
| #135 | PR-8.5 · OSM Nominatim geocoding fallback + dist_beach_km | queued |
| #136 | perf · photo-nav prefetch + 7 typed perf events | queued |

**Verify before doing anything:** `git log origin/main -10` and `gh pr list` — by the time you read this, some of #132–#136 may have landed (auto-merge is enabled on all).

## Sebastian's collaboration style

> Run with it. Don't ping for questions you can answer better than him with the context you have. Make the call, document it, keep moving. He'd rather correct course than be the bottleneck.

DO NOT use `AskUserQuestion` for tooling/naming/ordering decisions. DO ping for irreversible product/business choices and for setup tasks that need env vars (Clerk/Stripe/Resend).

## What's next per the plan

### PR-9 · Auth + saves + paywall (2.5 days)
**This is the next planned PR** but it's HARD-BLOCKED on Sebastian provisioning env vars first. Don't start coding until these are set:

- Clerk app + `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`
- Stripe account + price IDs + `STRIPE_SECRET_KEY`, `STRIPE_PUBLISHABLE_KEY`, webhook secret
- Vercel envs configured

If those aren't ready, do **PR-10 (Cutover)** first — it's independent.

### PR-9.5 · Pro account-management UI (½ day)
Stripe Customer Portal embed. Depends on PR-9.

### PR-9.6 · Newsletter — Resend (1 day)
Pro-plan-gated. Depends on `RESEND_API_KEY` env var.

### PR-10 · Cutover (½ day)
Make `/preview` → `/`. Delete `new_ux/`. Independent of PR-9 — can ship now.
- Edit `vercel.json`: change `/` rewrite from `/web/legacy.html` to `/web/dist/index.html`.
- Delete `new_ux/` (the design-reference prototype).
- Add a one-week-only `/legacy` rewrite to `/web/legacy.html` for rollback.
- Run a final smoke test pass.
- Add a telemetry dashboard doc summarizing all the typed events.

### Smaller items I noted but didn't ship

- **Discover hero photos (PR-4d.1)** — I deferred curated category artwork because it needs creative assets. The 8 categories use auto-cropped listing photos as fallback. If/when Sebastian provides 8 images at `web/app/assets/styles/<key>.{webp,jpg}` (560×360, ≤80KB each), it's a 30-min wire-up: `web/app/pages.jsx` `StyleCarousel` → import and prefer the curated path before the inventory-photo fallback.
- **`dist_beach_km` chips on the FE** — backend now emits the field (PR-8.5 #135). FE adapter already passes it through but no card pill or filter chip yet. Low effort follow-up.
- **`is_motivated` shelf** — backend NLP now flags ~20% of listings as motivated (PR-8 #134). Plan calls for the shelf rule `days_listed >= 90 AND (is_repriced OR is_motivated)`. Currently uses just `days_listed >= 90`. One-line change in `pages.jsx` `SHELVES` array once #134 merges.
- **Multi-photo scoring (extending PR-7.6)** — currently scores only the hero photo. Extending to top-N photos is a 1-line change in `automation/run.py:_download_hero_photos` to `for url in li.photo_urls[:5]:`. Triples bandwidth, but lets `featured.json` pick listings whose BEST photo is excellent, not just whose first photo happens to be.
- **Distance regex `_dist_to_beach_text_m`** — parses "200m de la playa" / "5 minutos caminando" → meters. Bumps `is_walk_to_beach` precision but the boolean detector already gets ~11% population so this is precision polish, not a recall fix.

## Hot risks / failure patterns I've seen

- **Two `/preview` crashes shipped earlier in the project** (pre-this-session). Both were null-trap bugs in render paths. The mandatory mitigations are in `CLAUDE.md` — `formatPpm()` style null-safe formatters, the Playwright smoke test, manual click-through before merging anything that touches `web/app/data/*` or render paths. Don't skip these.

- **Merge conflicts on `web/data/ranked.json`**. This file gets touched by every backend PR (schema migrations + backfills). When PRs queue up, the second one inevitably hits a conflict in `ranked.json`. Resolution is mechanical:
  1. `git checkout --theirs web/data/ranked.json` (take main's post-merge state)
  2. Re-apply your PR's schema migration (run the migration script if you have one, or do the field-add inline with a small Python one-liner)
  3. Regenerate the JSON schema: `python3 -m automation.generate_ranked_schema`
  4. Validate: load the schema and validate the first 50 listings
  5. Commit + push — auto-merge picks up

  I had to do this for #132 vs #133 in this session. Do not be afraid of it.

- **Auto-merge doesn't auto-update branches** at this repo's settings. When PR-A merges, PR-B becomes "BEHIND main." Use `gh pr update-branch <num>` to bump it; auto-merge fires once CI re-passes. Worth pinning to memory.

- **One pre-existing test fails locally**: `tests/test_photos.py::test_hero_download_creates_jpeg` — PIL/libjpeg version mismatch on Sebastian's local machine. Always run pytest with `--ignore=tests/test_photos.py`. CI passes (clean libjpeg there). Do not "fix" this — it's environmental.

- **CSP-eval console warning** is benign noise from PostHog. Already tolerated by the smoke test.

- **Bundle size** is right at the alarm threshold (~90 KB gz). Each PR adds 0.5-2 KB. The `check:size` script is configured "alarm-not-block" — warnings don't fail CI. If you cross 95 KB consider chunking strategies.

## Pending data refresh

PR-7.5 (#132) ships a one-time `scripts/reenrich_all.py` that wipes the LLM enrichment sidecar so the next nightly re-enriches all 873 listings with the new bilingual prompt. **Estimated cost: ~$10 in DeepSeek tokens, ~15 min wall-clock.** I already ran the migration on the committed `ranked.json` (clears bilingual canonical fields to null + adds `url_language=null`); the live re-enrichment fires on the next `python -m automation.run` after #132 merges. Sebastian needs to ensure `DEEPSEEK_API_TOKEN` is set in the Actions secrets.

## Useful commands

```bash
# Sync + branch
git checkout main && git pull origin main
git checkout -b feat/pr-N-description

# Run gates locally before push
PULPO_OFFLINE=1 python3 -m pytest -q --ignore=tests/test_photos.py
ruff check .
npm run typecheck && npm run lint:css && npm run build
npm run check:contrast && npm run check:size && npm run e2e:smoke

# Open + auto-merge
gh pr create --base main --head <branch> --title "..." --body "..."
gh pr merge <NUM> --auto --squash --delete-branch

# Bump a stuck PR
gh pr update-branch <NUM>

# Regenerate JSON schema after Listing model edits
python3 -m automation.generate_ranked_schema

# Check NLP keyword population on real data
python3 -m pulpo.nlp_extractor --check web/data/ranked.json
```

## What I learned about the project

- The plan in `~/.claude/plans/use-the-ux-fluffy-cocke.md` is well-structured and Sebastian iterates it as PRs land. **Read it before each PR** — the per-PR section often has acceptance criteria + scope clarifications.
- The `Listing` dataclass in `pulpo/models.py` is the single source of truth. Schema regen + `web/assets/types.d.ts` mirror are kept in sync via `tests/test_ranked_schema.py`.
- The two FE type files (`web/app/data/types.ts` for the new app's adapter shape, `web/assets/types.d.ts` for the legacy/schema-test mirror) drift in their concerns — keep them aligned with conscious scope.
- The pipeline order in `automation/run.py` matters. `apply_distances` runs twice in the current state (once after price-history derive, once after LLM + Nominatim) so haversine fires on freshly-geocoded listings.
- Telemetry catalog at `web/app/telemetry/events.ts` is typed — adding an event = adding a row there. PostHog autotracks the standard segments (country, device, browser, referrer); don't duplicate.

## Prompt for the next Claude session

Paste this as the first user message in a fresh session:

> Continue the new-UX rollout for pulpo.club. Read these in order:
>
> 1. `/Users/sehonores/Desktop/CodeExperiments/snoop-latam/pulpo.club/HANDOVER.md` — current state of all PRs, what's blocked, what's queued, my notes from the last session
> 2. `/Users/sehonores/Desktop/CodeExperiments/snoop-latam/pulpo.club/CLAUDE.md` — project rules: never push to main, --auto --squash merging, frontend conventions, null-safety rules
> 3. `~/.claude/plans/use-the-ux-fluffy-cocke.md` — the master plan
>
> PR-9 (auth + saves + paywall) is the next planned PR but hard-blocks on env vars Sebastian needs to provision (Clerk + Stripe — see "PR-9 prerequisites" in HANDOVER.md). If those aren't set yet, do PR-10 (cutover) instead — it's independent and can ship now.
>
> Sebastian's collaboration style: Run with it. Make calls and document them, don't ping for tooling questions. He'd rather correct course than be the bottleneck.
>
> Branch state: Verify with `git log origin/main -10` and check the merge queue with `gh pr list`. As of handover, PRs #132, #134, #135, #136 are all queued for auto-merge — they may have landed by the time you read this. Always `git pull origin main && git checkout -b feat/...` before starting.

Good luck. — prior Claude
