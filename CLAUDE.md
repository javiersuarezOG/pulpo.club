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

## Worktree convention

Before opening files for a substantial task, check whether a sibling
worktree already exists for the scope. One agent per sibling directory:
`pulpo.club.<scope>/`. Keep the main checkout on `main`, untouched,
and do feature work in the scoped worktree/branch. This avoids two
agents editing the same working tree while preserving a clean main
checkout for quick diffs and emergency patches.

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

### Merge-driver division of labour (post-2026-05-27)

For routine PRs where Sebastian is online and watching, Claude Code drives the merge to keep the loop tight:

1. **Claude opens the PR** with `gh pr create`, body includes the manual dry-run checklist.
2. **Claude shares the Vercel preview URL + the exact dry-run steps** (and watches PostHog / logs in parallel for telemetry confirmation).
3. **Sebastian walks the dry-run** on the preview URL. CLAUDE.md's existing per-class verification gates still apply (auth/billing flow, CSP, mobile viewport, etc.). Sebastian replies with "green" or paste of whatever broke.
4. **Claude runs `gh pr merge <NUM> --auto --squash --delete-branch`** after the "green" — `--auto` waits for required CI then merges.

This swaps the merge click off Sebastian's plate but preserves the human-in-the-loop on every verification gate. Sebastian can still merge manually whenever he prefers — the merge command is the same either way.

**When Sebastian merges manually instead:** no Claude action needed; Claude verifies on `main` afterwards via `git log` / `gh pr view --json mergedAt`.

**When NEITHER should merge automatically:** any PR where the dry-run can't be walked yet (broken Vercel preview, missing env var, blocked on a dashboard secret rotation, etc.). Hold the PR until the gate is walkable.

## Testing Before Pushing
- **Frontend (Vite app)**: `npm run dev` opens http://localhost:5173. Build check: `npm run build`. Typecheck: `npm run typecheck`.
- **Frontend (legacy)**: serves at `/legacy.html` until the PR-10 cutover. Tested via `npx serve .` if needed.
- **Pipeline changes**: run `python3 -m pulpo.cli --offline` to verify no errors
- **Tests**: `PULPO_OFFLINE=1 pytest -q` — full suite must pass (or fail only in known-broken areas not touched by your change)
- **Lint**: `ruff check .`

### Local-only pytest failure: libjpeg ABI mismatch (post-2026-05-25)

If `PULPO_OFFLINE=1 pytest -q` fails LOCALLY on `tests/test_photos.py` or `tests/test_repick_heroes.py` with `OSError: encoder error -2 when writing image file` plus a stderr line `Wrong JPEG library version: library is 90, caller expects 80`, that's a Pillow-vs-libjpeg ABI mismatch — Pillow was compiled against libjpeg 8 but the active environment serves libjpeg 9. CI on `ubuntu-latest` uses a consistent libjpeg + Pillow pair and is unaffected.

Fix:
```
pip install --upgrade --force-reinstall --no-binary :all: Pillow
```
If that still leaves the mismatch, the cleanest path on macOS is to recreate the venv against the system libjpeg:
```
brew install libjpeg
pip install --upgrade --force-reinstall Pillow
```
The failure is purely a local-env artifact; do NOT change the photo-pipeline code to "work around" it.

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
   - Open DevTools Console before clicking the email CTA. Click the email CTA → complete Clerk sign-up → confirm the password input and CAPTCHA widget render, with zero CSP violations and zero `Clerk: Failed to load the CAPTCHA` messages.
   - Confirm you land on `/account` signed in, in Pro state.

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

## NEVER ship a broken CSP change again (post-2026-05-27)

Any PR touching `vercel.json`'s `Content-Security-Policy` must include:

1. A Vercel preview DevTools Console screenshot or recording showing zero CSP violations on `/`, `/start`, and `/account?__clerk_status=sign_up&__clerk_ticket=invalid`.
2. A PR-body list of every third-party CSP domain and why it is allowed. New domain = new line item.
3. A local test run including `tests/api/vercel_security_headers.test.js` and `tests/e2e/captcha-csp.spec.ts`.

## NEVER let a webhook go silent (post-2026-05-27)

Every webhook endpoint Pulpo owns needs a positive heartbeat before it
is called production-ready. A green handler test only proves it works
when invoked; it does not prove the external provider is still sending,
the signing secret still matches, or telemetry still lands.

Mandatory rules:

1. Add the event family to `scripts/check_webhook_health.py` before
   shipping the endpoint. The scheduled workflow
   `.github/workflows/pulpo-webhook-health.yml` runs every 6 hours and
   alerts through `SLACK_WEBHOOK_URL`.
2. Rotating a signing secret means re-run the provider dashboard smoke
   test immediately. Do not declare the rotation done until the latest
   delivery shows 2xx AND the matching PostHog event appears.
3. A webhook silence alert is actionable even when the app "looks fine".
   The 2026-05-27 Resend outage was invisible for 7 days because there
   was no positive heartbeat.

## Stripe return_url must be section-aware (post-2026-05-27)

Stripe handoffs must return the user to the exact surface they came
from, with enough query state for the landing route to refresh Clerk
metadata. Customer Portal return URLs go to `/account/subscription`,
not `/`; Checkout success URLs keep `?welcome=1&session_id=...`.

New Stripe handoffs must:

1. Include the account section in the return URL, e.g.
   `/account/subscription?from=portal`.
2. Carry a source flag such as `?from=portal` so the landing route can
   call `reloadUser()` and avoid stale publicMetadata.
3. Emit a PostHog return event and pair it with the rendered-state event
   so dashboard queries can prove the UI saw the updated billing state.

## NEVER ship a UI control that lies about persistence (post-2026-05-27)

Found two examples in the Account area at once: the Profile Save button
fired a "Changes saved." confirmation but called `setTimeout` instead of
writing anything; the Notifications top-level toggles (Newsletter,
Platform updates, Frequency) all flashed "Preference saved" while only
mutating local React state. Users changed their settings, refreshed,
and watched their changes vanish.

**Rule:** any control that triggers a "Saved" / "Updated" / "Done"
confirmation MUST have a real persistence consumer downstream. That
means ONE of:

1. **Clerk frontend SDK** (`clerk.user.update`, `clerk.user.setProfileImage`,
   etc.) — for first-class identity fields. Verify by reloading the page
   AND by reading the value back via the Clerk Backend API in tests.
2. **`/api/clerk/update-profile`** — for everything stored in
   `publicMetadata.profile.*`. Server-side `ALLOWED_PROFILE_KEYS` gates
   writes. Adding a new field = (a) add the validator, AND (b) point at
   the downstream consumer that reads it. No field ships without both.
3. **A documented external system** (Resend audience for subscribe
   state, Stripe for billing, etc.) — wire the API call before the
   control ships, not after.

**Forbidden patterns:**
- Persisting to local React state + flashing a confirmation toast.
  That's the literal bug we shipped twice.
- Persisting to Clerk `publicMetadata` for a key no consumer reads
  (today: `cadence`, `notifications.platform_updates`). That's a
  hidden lie — the data lands somewhere but no behavior changes. If
  no consumer exists yet, the control doesn't ship; document the
  follow-up in the plan.
- "We'll wire it later" — if there's no downstream consumer in the
  same PR, remove the control or hide it behind a flag default off.

**Smoke-test guardrail (mandatory when touching /account):**
`tests/e2e/account-authed.spec.ts` (added post-2026-05-27) signs in
with the Clerk test user, mutates every visible control, reloads, and
reads each value back via `clerkClient.users.getUser(id)`. Any new
control on /account MUST be exercised by this spec before merge.

**Telemetry guardrail:**
- `account.profile_save_started` / `_succeeded` / `_failed` and
  `account.profile_photo_upload_started` / `_succeeded` / `_failed`
  fire on every mutation. PostHog alert: if `_started` count diverges
  from `_succeeded + _failed` for >5 minutes, a save path is silently
  swallowing — investigate.
- `account.profile_save_no_consumer` fires if the save handler runs
  but no Clerk action surface is wired. Non-zero in prod = regression
  in the action-binder; treat as a sev-2.

## NEVER hardcode subscription state again (post-2026-05-27)

`web/app/account.jsx`'s subscription block shipped `"Renews on 5 Jun 2026"` as a literal placeholder. Every customer — including canceled ones who clicked Cancel in the Stripe portal — saw "Renews on..." copy. Hardcoded dates can't track real subscription state, so any state that diverges from "active + renewing forever" silently lies to the user.

**Three rules now mandate dynamic state on this surface:**

1. **No hardcoded date strings in any account / subscription UI.** Dates render from real subscription fields via `web/app/lib/subscription.ts`'s `deriveSubscriptionState` (`current_period_end`, `cancel_at_period_end`, `canceled_at` — written by `customer.subscription.updated` in `api/stripe/webhook.js`). `Intl.DateTimeFormat` handles locale formatting. Any literal like `"5 Jun 2026"`, `"5 de junio de 2026"`, etc. in JSX is banned. If you can't derive the date from real state, don't render a date.

2. **`subState.display` is the single switch for sub-block copy.** Each display value (`active` / `canceling` / `canceled` / `grace` / `past_due`) has its own i18n key set under `account.sub.plan_meta.*`, `account.sub.status_copy.*`, `account.sub.pill.*`. The anti-renewal-leak canary in [web/app/lib/subscription.test.ts](web/app/lib/subscription.test.ts) asserts:
   - `canceling` and `canceled` copy NEVER contain "Renews on" / "Se renueva".
   - `active` copy NEVER contains "Cancels on" / "Se cancela".
   - Every variant interpolates `{date}` cleanly with no unresolved placeholder.
   If you add a new display state, extend the canary AND the i18n keys together — don't ship one without the other.

3. **PostHog `account.sub_block_rendered` fires once per display-state transition.** Properties include `display`, `cancel_at_period_end`, `raw_status`, `in_grace`, `has_period_end`, `ever_paid`. Alert on `display=canceling && raw_status=active && cancel_at_period_end=false` mismatches; spot regressions where the webhook stops stamping `current_period_end` or `cancel_at_period_end`. Pair with `account.sub_resubscribe_clicked` to measure re-acquisition funnel from canceled state.

**Invoice access policy:** the "View invoices in the Stripe portal →" link is gated on `everPaid` (currently Pro OR ever past_due OR ever canceled OR has `current_period_end`), NOT on `isPaid`. A canceled user keeps full access to their historical receipts. The Customer Portal endpoint self-heals `stripeCustomerId` via email lookup (see PR #510), so the link is always safe to render for ever-paid users.

## NEVER skip locale on third-party billing surfaces (post-2026-05-27)

Every Stripe + Clerk API call that creates a user-facing surface
(Checkout Session, Customer Portal session, hosted modal, invitation
email) MUST receive the user's current `app.locale`. Locale captured
only at signup is not enough: the user can switch languages later and
expects the next Stripe/Clerk surface to follow.

Mandatory for every new endpoint that calls
`stripe.checkout.sessions.create`, `stripe.billingPortal.sessions.create`,
`clerk.invitations.createInvitation`, or any API that ships text to the
user:

1. Accept `body.locale` on the request.
2. Normalize through a `SUPPORTED_LOCALES` set.
3. Pass the normalized value to the SDK call.
4. Stamp the locale into session/invitation metadata when downstream
   webhooks need to re-read it.
5. Add `locale` to the corresponding `posthog.capture(...)` event.

Mandatory for every client wrapper that POSTs to those endpoints:

1. Accept `locale` as an argument or read `localStorage.pulpo-locale`.
2. Include it in the request body.

Smoke-test guardrail: every endpoint unit test covers `{ en, es,
missing, garbage }` locale inputs. Endpoint without a locale test does
not ship.

## NEVER skip post-redirect state refresh (post-2026-05-27)

Any client surface returning from a third-party billing/auth redirect
(Stripe Portal, Stripe Checkout, Clerk hosted modal, etc.) MUST handle
the webhook-vs-redirect race. A single `reloadUser()` on mount is not
enough: the webhook can land 1-10s after the user redirects back, so
the first reload can fetch stale metadata.

Pattern:

1. Detect the return via a `?from=<source>` query param set on the
   redirect's `return_url`.
2. Strip the param before the reload completes so refresh/back does not
   replay it.
3. Poll `reloadUser()` up to roughly 5 attempts x 1.5s, stopping on
   the first detected metadata change.
4. Render an inline "Refreshing..." indicator while polling.
5. Fire `<surface>_state_changed` and `<surface>_stale` PostHog events
   so the funnel is observable.

Forbidden:

- One-shot reload on mount with no retry.
- Hardcoded `setTimeout(reload, 2000)`; webhook latency varies, so
  reload must be state-diff driven.
- Swallowing the stale case silently.

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
- **Mobile-first is mandatory.** Every visual change is designed for mobile (320–768px) first and enhanced upward. Use `min-width` media queries in new CSS, not `max-width`. A PR that works on desktop but breaks at 320px is not mergeable, even when "desktop is the primary surface" — roughly half our traffic is mobile and the paywall converts on mobile. Existing `max-width` CSS in the codebase is grandfathered; don't refactor it speculatively, but don't add new desktop-first rules either.
- **Both viewports must work before merge.** Every PR touching a visual surface attaches one mobile (375px) + one desktop (1280px) screenshot. The Playwright responsive-smoke spec at `tests/e2e/responsive-smoke.spec.ts` iterates every public section (`/`, `/browse`, `/saved`, `/plans`, `/account`) at **five** viewports (320×568, 375×812, 414×896, 768×1024, 1280×800), asserts `documentElement.scrollWidth ≤ innerWidth + 1`, and on failure prints the widest descendant's `outerHTML` so the diagnostic is actionable. **CI failure at any viewport — mobile or desktop — blocks merge.** For `/account` specifically the spec also clicks every sub-section tab (profile / notifications / subscription / security) at every viewport with both Free and Pro user seeds — different content paths render different DOM, so testing only the default landing tab misses three of four sub-sections. **Shared test helpers live at `tests/e2e/_helpers.ts`** (`TOLERATED`, `isTolerated`, `attachErrorRecorder`, `seedUser`, `seedProUser`); new specs import from there instead of inlining a fourth copy of the noise allowlist.
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

## Persistence & backups (read before claiming "we need a DB backup")

**Pulpo has no database.** The 2026-05-20 pre-prod audit was confused
by a stale `DATABASE_URL` stub in `.env.example` and flagged "no
backup story documented." `DATABASE_URL` is never referenced in any
`.py` / `.js` / `.ts` / `.yml` — it's a leftover from an early PR and
has been removed.

All Pulpo persistence lives in one of two places:

1. **Listings data** — `web/data/*.json` (`ranked.json`, `featured.json`,
   `llm_enrichment.json`, etc.) is regenerated nightly by the pipeline
   and committed to `main` by `pulpo-bot`. Recovery RPO = last successful
   nightly run (≤ 24h); RTO = re-run the nightly. Git history is the
   backup — `git log -- web/data/ranked.json` walks every prior state.

2. **User data** — every byte of user-identifying state is owned by a
   third-party SaaS, and each provider is responsible for its own
   backups:
     - **Clerk** — accounts, sessions, invitations, plan metadata.
       (Clerk backup SLA: per their DPA.)
     - **Stripe** — customers, subscriptions, invoices, payment intents.
       (Stripe's own retention.)
     - **PostHog** — events, sessions, Person properties.
     - **Resend** — newsletter audience, email lifecycle telemetry.

There is NO self-hosted Postgres, Supabase, Neon, Vercel KV, or
Upstash instance. If a future feature genuinely needs one, the PR that
adds it must also add the backup posture to this section.

## "Shipped" means the user-visible surface renders the change (post-2026-05-26)

**PR-MC-PA-1 wrap-up overclaimed.** The smoke run exited 0, wrote
`ranked.PA.json` (empty array, 2 bytes), and I declared "green for the
parameterization scope." The user opened `pa.pulpo.club` and got a DNS
error — no domain, no data, no usable surface. Two more PRs were needed
to actually produce PA listings. "Pipeline ran" is upstream of done; it
is not done.

**The rule:** before claiming a change works, check the user-visible
surface. If the change targets a URL, `curl -I` that URL and inspect a
sample. If the change produces a file, open it and verify the content
matches the claim, not just that the file exists. If the surface
doesn't exist yet (DNS not configured, Vercel project not created,
deploy not built), say **"code shipped; deploy pending: [explicit list
of remaining manual steps]"** — never "works."

Concrete checks per change-shape:

- **API / route change** → `curl` the route, eyeball the response body.
- **Frontend change** → load the page in a browser at the relevant
  viewport (per the mobile-and-desktop rule above) and exercise the
  feature.
- **Pipeline / data change** → open the output file, count rows,
  spot-check 2–3 records' content. "Row count > 0" is not enough; the
  records must be correct for the change.
- **New subdomain / Vercel project** → `dig +short <subdomain>` AND
  `curl -I https://<subdomain>/` AND inspect rendered HTML. Three
  separate failure modes; none subsumes the other.
- **New CI guardrail** → run the guardrail against a known-bad input
  to confirm it fails; then against current main to confirm it
  passes. A guardrail that never triggers is decorative.

**The smell test:** if the wrap-up reads "pipeline exited 0, file
written, tests pass" without a sentence about what a user would
actually see, it's incomplete. Add the user-visible verification or
flag the deploy gap explicitly.

## Country-hardcode guardrail (post-2026-05-26)

Three SV-only string literals (`country="SV"`, an exclusion regex
listing non-SV country names, and a schema `{"const": "SV"}`) silently
dropped every PA listing in the MC-PA-1 smoke. PR #489 fixed them and
[`scripts/check_country_hardcodes.py`](scripts/check_country_hardcodes.py)
now runs in CI to prevent the regression class.

**When the check fails:**

1. Read the active country from the manifest:
   ```python
   from pulpo.countries import active as _active_country
   country_name = _active_country().name_en
   ```
   or `loaded()` if you need a list of every registered country.
2. If the hardcode is legitimately single-country (e.g. a scraper that
   only serves one country's site, or the dataclass-default fallback),
   add `# multi-country-exempt: <one-line reason>` on the offending
   line. The reason makes the exemption auditable; "exempt" alone is
   not enough.
3. If the file is entirely country-specific by design (the SV manifest,
   an SV-only scraper, the company-jurisdiction config), add its path
   to `ALLOWED_FILES` in the script.

**What NOT to do:**

- Don't add `el.salvador|guatemala|panam[aá]|...` regex alternations
  directly. Build them dynamically from `_KNOWN_COUNTRY_NAMES` minus
  the active country (see `automation/validation.py` for the pattern).
- Don't suppress the check with a blanket exempt marker on a long
  list of code lines. If the change is broad enough that more than
  2-3 lines need exemptions, you're probably hardcoding instead of
  reading from the manifest.

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
