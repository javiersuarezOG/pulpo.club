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

## NEVER ship a broken auth/billing flow again — live preview verification (post-2026-05-19)

**PR #307 shipped a "fix" for the post-Stripe modal that left two real bugs in production** — a gate-bypass race that opened Clerk's SignIn modal on top of the WelcomeModal, AND a modal that lied about whether an invitation email was actually sent (the webhook can take three different no-email paths). Both manifested only with Clerk ON, both were invisible to CI (which runs Clerk OFF), and both shipped because the PR was merged with the manual Stripe-sandbox checklist `[ ]` unchecked.

**Mandatory rules for any PR that touches `api/stripe/**`, `api/clerk/**`, `web/app/app.jsx`'s welcome/login URL effects, `WelcomeModal` / `SignupModal`, `web/app/lib/route-gates.ts`, `web/app/account.jsx`'s auth-gate effect, or the Stripe success URL:**

1. **Walk the full Stripe-sandbox flow on the Vercel preview URL** (NOT just dev w/ Clerk off):
   - Open the preview URL in a **fresh incognito window**.
   - Hit `/start` → run a Stripe-sandbox checkout (4242 4242 4242 4242).
   - Confirm the modal sequence on the success URL: **no SignupModal flash, only WelcomeModal**.
   - Confirm the Clerk invitation email arrives in **inbox** (not spam, not promotions tab) on a **brand-new email address that has never been used in any prior Pulpo test**. Existing-email tests hit the silent-no-email path on the webhook and are misleading.
   - Click the email CTA → complete Clerk sign-up → confirm you land on `/account` signed in, in Pro state.

2. **Who walks step 1:**
   - **Agents (Claude Code etc.) walk the LOCAL dev server**: `npm run dev` + Playwright against `localhost:5173` with the existing e2e suite (`npx playwright test --grep "welcome modal" preview-smoke.spec.ts` + `--grep "/account\?welcome=1" responsive-smoke.spec.ts`). Agents currently CANNOT access the Vercel preview URL because previews are SSO-gated to the Vercel team — external traffic redirects to a Vercel login. (Setting `VERCEL_AUTOMATION_BYPASS_SECRET` on the project + threading it into agent requests would unblock this; until then, agents can't.)
   - **Sebas walks the Vercel preview** with the real Clerk live-instance + real Stripe sandbox. This is the only verification surface that catches Clerk-on bugs CI can't see.
   - Both must be done before merge.

3. **Attach evidence to the PR body** before requesting merge:
   - Agent: screenshot or test-run output proving the e2e suite passed locally, including the regression-guard test.
   - Sebas: screenshot of the WelcomeModal on the Vercel preview success URL (signed-out, then signed-in after the email round trip).
   - PostHog event snippet showing `webhook.received` → `webhook.checkout_completed` → `welcome_modal.shown variant=anon` → `welcome_modal.shown variant=signed_in` for the test session.
   - Confirmation that `welcome_modal.invitation_status_resolved status=invitation_pending` fired (once PR #2 of the activation-flow series lands).

4. **The `[x] Manual sandbox dry-run` checkbox is mandatory.** CI green is necessary but **not sufficient** to merge. If the box is unchecked, the merge does not happen — even on `--auto`.

5. **The Vercel preview URL is the testing surface for the Sebas-side check.** Production deploys carry real Stripe webhooks, real Clerk live keys, and real user money. The preview environment is the safest place to catch what CI can't see — use it.

6. **Skipping these guardrails is how a broken funnel hits paying users.** The user sees a Clerk modal they don't recognize and an inbox with no email, not a green CI badge.

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
- **Responsive:** every PR touching a visual surface attaches one mobile (375px) + one desktop (1280px) screenshot. The Playwright responsive-smoke spec at `tests/e2e/responsive-smoke.spec.ts` iterates every public section (`/`, `/browse`, `/saved`, `/plans`, `/account`) at four viewports (320×568, 375×812, 414×896, 768×1024), asserts `documentElement.scrollWidth ≤ innerWidth + 1`, and on failure prints the widest descendant's `outerHTML` so the diagnostic is actionable. For `/account` specifically the spec also clicks every sub-section tab (profile / notifications / subscription / security) at every viewport with both Free and Pro user seeds — different content paths render different DOM, so testing only the default landing tab misses three of four sub-sections. **Shared test helpers live at `tests/e2e/_helpers.ts`** (`TOLERATED`, `isTolerated`, `attachErrorRecorder`, `seedUser`, `seedProUser`); new specs import from there instead of inlining a fourth copy of the noise allowlist.
- **No backwards-compat shims** in the new app — the legacy is the legacy, the new is the new. Don't re-export old utilities to "ease migration."

## i18n — every user-visible string goes through `t()`

The app supports EN + ES (and will gain more). Every string a user can see — JSX text, `aria-label`, `placeholder`, `alt`, button labels, error copy — is looked up from [`web/app/i18n.jsx`](web/app/i18n.jsx)'s `UI_STRINGS` table via `t(key, locale)`. **No exceptions** for anywhere in `web/app/` *except* the LegacySignupModal block (only renders when Clerk is OFF, never in prod).

The trap that keeps biting us: rendering raw enum values via `capitalize()` (e.g. `road_access_type === "paved"` → "Paved" in any locale). For enum values, use a closed-set guard plus a per-value i18n key:

```js
const ROAD_ENUMS = new Set(["paved", "gravel", "dirt"]);
const roadValue = ROAD_ENUMS.has(v)
  ? t(`detail.fact.road.${v}`, lc)
  : capitalize(v);  // safety net for unknown enums; shouldn't be reached
```

The matching i18n keys (`detail.fact.road.paved`, `detail.fact.road.gravel`, `detail.fact.road.dirt`) live next to their parent label so future contributors find them all together.

**Adding a new translatable string:**

1. Add a row to `UI_STRINGS` in `web/app/i18n.jsx` with `{ en: "…", es: "…" }`. Group by surface (detail / nav / browse / etc.) — there are existing section comments to slot under.
2. Call `t("your.key", locale)` at the render site. `locale` is available as `app.locale`, `lc`, or via `currentLocale()` if the component is leaf-only and has no app prop.
3. If the string carries variables, use `{name}` placeholders + `t(key, locale, { name: value })`.

**Adding a new locale:**

Add the language code to `LOCALES` at the top of `i18n.jsx`. Every existing entry in `UI_STRINGS` gracefully falls back to `DEFAULT_LOCALE` (en) when the new key is missing — meaning a partial translation ships safely. Add an entry to the locale toggle (search `useLocale` for the call site) and the document.documentElement.lang sync is automatic.

**The smoke-test guardrail:**

[`tests/e2e/preview-smoke.spec.ts`](tests/e2e/preview-smoke.spec.ts) → "Spanish locale: no English canary words leak into rendered UI". The test loads `/`, switches `localStorage.pulpo-locale = "es"`, reloads, and asserts the body text + a sample of aria-labels do NOT contain a curated list of English canary words ("Paved", "Back to results", "Save listing", etc.). Each canary represents an i18n bug we've already fixed once. **When this test fails:**

- The right move 99% of the time is to add the offending string to `UI_STRINGS` and call `t()` from the render site.
- The wrong move is to add the word to the test's `SHARED_TOKENS` allowlist. Reserve that for words that genuinely exist in BOTH EN and ES copy (e.g. brand names, "Pulpo Pro").

When you add a new translatable string, **also add an English canary for it to the smoke test if it's the kind of word that would silently look fine in English**. Cheap insurance.

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
