# Pulpo Club — Claude Code Guidelines

## Collaboration style (Sebastian)
- Run with it. Don't ping for questions you can answer better than him with the context you have.
- Make the call, document it, keep moving. He'd rather correct course than be the bottleneck.
- Per-PR merge gate is for *during* the new-UX rollout. After PR-10 the gates remain as standing CI; the manual-check ritual disappears.
- Plan source of truth: `~/.claude/plans/use-the-ux-fluffy-cocke.md`.

## Branch Rules (NEVER skip this)
- NEVER commit or push directly to `main`
- Always work on a feature branch: `feat/description` or `fix/description`
- Before starting any task, confirm the current branch with `git branch`
- If on `main`, create a branch first: `git checkout -b feat/your-task-name`

## Before Making / Pushing Any Changes
1. `git pull origin main` — get Javi's latest
2. `git checkout -b feat/your-task-name` — create your branch
3. Make changes, test locally
4. `git add <files>` (explicit — never `git add .` for sensitive trees) `&& git commit`
5. `git push -u origin feat/your-task-name`

## Merging to main

**PRs are required.** Direct push to `main` is blocked at the GitHub level (rule `GH006: protected branch update failed — Changes must be made through a pull request`).

After pushing the branch:
```bash
gh pr create --base main --head <your-branch> --title "..." --body "..."
```
Vercel will auto-generate a preview URL on the PR.

**Default merge command:**
```bash
gh pr merge <NUM> --auto --squash --delete-branch
```
The `--auto` flag queues the merge to fire as soon as required checks pass. Auto-merge is enabled at the repo level. Required checks (`pytest`, `frontend (typecheck + build)`, `Vercel`) typically complete in ~1 minute — `--auto` eliminates the "Expected — Waiting" race that happens if you try to merge immediately after `gh pr create`.

**Do NOT use `--admin` to bypass branch protection** unless a check is genuinely stuck or broken. The recurring "Expected, waiting" state is almost always transient (CI hasn't started yet); `--auto` handles it cleanly. Reserve `--admin` for the data-PR fallback path documented in `pulpo-nightly.yml`.

If a local-merge attempt to `main` fails with `protected branch hook declined`, that's the protection rule firing — roll back with `git reset --hard origin/main` and open a PR.

## Testing Before Pushing
- **Frontend (Vite app)**: `npm run dev` opens http://localhost:5173. Build check: `npm run build`. Typecheck: `npm run typecheck`.
- **Frontend (legacy)**: serves at `/legacy.html` until the PR-10 cutover. Tested via `npx serve .` if needed.
- **Pipeline changes**: run `python3 -m pulpo.cli --offline` to verify no errors
- **Tests**: `PULPO_OFFLINE=1 pytest -q` — full suite must pass (or fail only in known-broken areas not touched by your change)
- **Lint**: `ruff check .`

## NEVER ship a /preview crash again — null-safety + smoke test (post-2026-05-07)

**Two crashes shipped in two PRs.** That's twice too many. The pattern was the same both times: a real listing's field was null where the prototype's mock was always populated. Components called `.toFixed()` / `.length` directly without a null guard, ErrorBoundary fired, page blanked.

**Mandatory rules:**

1. **Every Listing field that's `| null` in `web/app/data/types.ts` must be guarded in every component.** Never `listing.price_per_m2.toFixed(0)`. Always `formatPpm(listing.price_per_m2)` or equivalent. New format helpers go in `web/app/components.jsx` next to `formatPrice` / `formatSize`. The pattern: `if (n == null) return "—"; return …`.

2. **Before merging any PR that touches `web/app/data/*` OR a render path that reads Listing fields:**
   - Run `npm run e2e:smoke` (Playwright) locally. The smoke test boots the dev server, opens `/` and `/?dev=1`, asserts no console errors, fails on the `"Something went wrong."` ErrorBoundary fallback. ~30s.
   - Or click through the dev server manually: `npm run dev`, open all four routes (Discover, Browse, Saved, Plans), check the dev console for red.
   - Vercel preview is the last line of defence, not the first.

3. **Adding a new field to `web/app/data/types.ts`?** Search-replace the field name across `web/app/`. Every read site needs to consider the null case.

4. **Skipping these guardrails is worse than missing the deadline.** The user sees crashes, not commits.

## Frontend conventions (post-PR-1.5)

The new app lives at `web/app/` (React 18 + Vite). Build output → `web/dist/`. The legacy vanilla-JS dashboard is at `web/legacy.html` and stays untouched until PR-10.

- **Design tokens** live at `web/app/styles/tokens.css` (lands in PR-1.5). Every color, font, spacing, radius, shadow, and motion easing comes from there.
- **Banned in any `.css`/`.tsx`/`.jsx` file under `web/app/`:**
  - Hex color literals (`#fff`, `#1a1a1a`)
  - `rgb(...)` / `rgba(...)` literals (use the oklch tokens)
  - `font-family: Arial`, `Times New Roman`, `system-ui` as inline fallbacks (the tokens cover the fallback chain)
  - Off-token spacing (`margin: 13px`, `padding: 9px`) — pick a token or add one to `tokens.css`
- **stylelint** enforces the above (PR-1.5 onward). CI fails on violation. Override only with `/* token-exception: <reason> */` and justify in the PR.
- **New filter / shelf / badge:** add an entry to `web/app/config/registry.ts` and an i18n key. **Don't** hard-code in a component.
- **Visual fidelity:** Discover/Browse/Detail are diffed against `docs/design-references/` in every PR that touches them. Visual deviation needs a one-line justification.
- **Responsive:** every PR touching a visual surface attaches one mobile (375px) + one desktop (1280px) screenshot. Playwright smoke includes `page.setViewportSize({ width: 320, height: 568 })` and asserts no horizontal overflow on `/` and `/browse`.
- **No backwards-compat shims** in the new app — the legacy is the legacy, the new is the new. Don't re-export old utilities to "ease migration."

## Geocoding & beach reference table

Coastal listings get their lat/lng from a single LLM call (DeepSeek). The
prompt at `automation/llm_enrichment_prompts.py` includes an
`AUTHORITATIVE BEACH COORDINATES` block rendered from
`NAMED_BEACHES` in `automation/distance_fields.py`. **Same tuple feeds
both the prompt's anchor table AND the `dist_beach_km` haversine grid.**
Adding a beach in one place propagates to both.

Read `docs/named-beach-reference.md` before:
- adding a new country / region to the platform;
- adding or moving a `NAMED_BEACHES` entry;
- investigating "listing claims walk-to-beach but `dist_beach_km` is
  several km".

The nightly pipeline runs `automation/unmapped_beach_detector.py` and
prints `[unmapped_beaches] suspects=N clusters=M` plus the top
clusters. A non-zero cluster_count means new listings are landing in
unmapped territory — the table needs an entry. History is appended to
`web/data/unmapped_beaches_history.jsonl`.

To force-retrofit existing listings after a prompt or table change:
`python3 scripts/retrofit_geocoding.py` (dry-run with `--dry-run`,
cap with `--limit N`).

## Commit Message Format
- `feat:` new feature
- `fix:` bug fix
- `chore:` maintenance/config
- `refactor:` restructuring without behaviour change
- `test:` test-only change

Prefix with the PR number where it fits the new-UX rollout: `feat(pr-3): ...`.

## What Sebastian Works On
- `pulpo/ranker.py` and `pulpo/ranker_legs/*.py` — ranking model and weights
- `pulpo/normalize.py` — normalization, classification, zone detection
- `web/legacy.html` — current production frontend, frozen until PR-10 cutover
- `web/app/**` — new React app (this is the active surface; lands in PR-0 onward)
- `web/data/` — never edit manually, generated by the pipeline
