# Pulpo System Health Audit PRD

Date: 2026-06-02
Owner: Product + Engineering + Data Science
Audit scope: pulpo.club production, local main at `fdd191ca`, GitHub Actions, PostHog, data pipeline, Clerk, Resend, Stripe, Vercel, Slack-backed monitors, public UX, responsiveness, language consistency, performance, CI, and test health.

## Executive Summary

Pulpo is usable today, but the safety system is not yet trustworthy enough for the product's current complexity.

The good news: production is serving fresh core catalogue data from 2026-06-02, the main nightly run recovered and deployed, the public pages I smoke-tested render without horizontal overflow across mobile and desktop, Stripe/Clerk locale plumbing is present in code, Clerk CSP includes Turnstile, the public API health endpoint is green, Vitest/typecheck/build pass, and PostHog dashboards for ops now exist.

The bad news: several of the controls that should catch regressions either do not run, parse the wrong thing, or pass while the user-visible experience is degraded. The highest-impact confirmed gaps are:

1. The Clerk stuck-invitation monitor is failing every 6h from GitHub Actions because Clerk's API blocks the runner with Cloudflare 1010.
2. The Resend deliverability monitor also fails from GitHub Actions with Cloudflare 1010.
3. Resend lifecycle events are landing in PostHog, but with `email_type="unknown"` and `recipient_hash=null`, so bounce, complaint, unsubscribe, and activation-delivery dashboards cannot be trusted.
4. The Resend heartbeat treats every `newsletter.*` event as a Resend webhook heartbeat, but internal newsletter build/reconcile events also match that prefix.
5. Production `featured.json` is expired from 2026-05-08 because the nightly writes it but the commit step omits the SV `web/data/featured.json` file.
6. The catalogue advertises local `hero_photo_path` files that mostly do not exist at the root URL: 884 of 959 records point at missing root-level local photo paths in the current checkout, and production home/browse fire many local photo 404s.
7. Full Playwright smoke is red and removed from CI; multiple specs still target retired HeroV3/HeroV4/USP surfaces, and admin/newsletter responsive selectors are stale.
8. CSS lint and bundle-size checks exist but are not meaningful gates: CSS lint currently fails with 29 issues, while the bundle checker points at an obsolete `web/dist/assets/index.js` layout and misses the real hashed Vite bundles.

This PRD proposes a phased recovery plan. The first tranche should restore observability truth and photo/data freshness. The second tranche should restore QA guardrails and funnel confidence. The third tranche should tighten design, performance, and integration operations.

## Evidence Collected

### Local code and test checks

| Check | Result | Notes |
| --- | --- | --- |
| `npm run typecheck` | Pass | TypeScript surface compiles. |
| `npm run build` | Pass with warnings | Vite warns that `stripe-checkout.js` and `telemetry/perf.ts` are both static and dynamic imports, reducing split effectiveness. Main JS is about 408 KB raw / 123 KB gzip; CSS about 157 KB raw / 26 KB gzip. |
| `npm run test` | Pass | 48 Vitest files, 635 tests passed, 4 skipped. |
| `npm run lint:css` | Fail | 29 stylelint errors in `web/app/styles/index.css`; this script is not run in CI. |
| `npm run check:contrast` | Pass | Token contrast guard is healthy. |
| `npm run check:size` | Broken | Reports `index.js not built` and `index.css not built` after build because it expects `web/dist/assets/index.*`; Vite emits hashed files under `web/dist/build/`. |
| `node scripts/i18n_lint.mjs` | Pass | No hardcoded JSX attribute strings detected. |
| `python3 scripts/check_country_hardcodes.py` | Pass | No unmarked country hardcodes found. |
| `PULPO_OFFLINE=1 pytest -q` local | Fail | 14 failures, mostly local env/dependency drift: missing Pillow and test leakage from `.env` (`DEEPSEEK_API_TOKEN`, `PULPO_SOURCES=kazu`). CI installs dependencies and is greener, but local tests are not hermetic. |
| Full Playwright `e2e:smoke` | Fail | 216 passed, 5 skipped, 27 failed in 11.7 minutes. Failures cluster around retired home selectors, stale admin/newsletter selectors, one account welcome responsive expectation, and a promo-code rollback expectation not updated for locale payloads. |

### Production/public checks

| Check | Result | Notes |
| --- | --- | --- |
| `https://pulpo.club/api/nightly/health` | 200 OK | Core SV data fresh: `last_data_commit_at=2026-06-02T08:24:38Z`, 959 total listings, no failed source in last run. |
| `https://pulpo.club/data/ranked.json` | 200 OK | 959 records. |
| `https://pulpo.club/data/ranked.list.json` | 200 OK | 959 records. Browseable count is 880 because 79 records are incomplete; header showing 880 is therefore intentional but should be labelled more clearly as browseable properties. |
| `https://pulpo.club/data/featured.json` | 200 OK but stale | `picked_at=2026-05-07`, `expires_at=2026-05-08`. Current nightly writes fresh featured output but the commit step omits SV `featured.json`. |
| Public pages `/`, `/browse`, `/plans`, `/start`, legal routes, `/contact` | Rendered | No horizontal overflow at 375 and 1280 in direct production smoke. |
| Public home/browse photo requests | Degraded | `/` requested 21 missing local `/photos/*.jpg` files in one mobile load; `/browse` requested 11. PostHog confirms hundreds of local `image.error` and `image.stuck` events in the last 7 days. |
| Spanish `/start?lang=es` | Body localized, title English | Document title remains `Pulpo - Beach and lake homes in El Salvador, ranked by value`. |
| Basic lab perf via Playwright | Acceptable cached lab numbers | Home mobile LCP observed about 256 ms and CLS about 0.004 in headless cache-like conditions. This is not a substitute for RUM. |

### Integration checks

| Integration | What is healthy | What is broken or unproven |
| --- | --- | --- |
| Clerk | CSP includes `https://challenges.cloudflare.com`; Clerk webhook events exist in PostHog today; frontend localization provider is reactive. | The stuck-invitation monitor cannot query Clerk from GitHub Actions: recent runs fail with Cloudflare 1010 from `https://api.clerk.com/v1/invitations`. PR #636 addresses part of this but must be merged and expanded into a monitor-health model. |
| Resend | Lifecycle webhook events are arriving in PostHog today (`newsletter.sent`, `newsletter.delivered`). Activation/newsletter senders stamp tags and headers. | Webhook parser emits `email_type="unknown"` and `recipient_hash=null`; rate dashboards skip. Weekly deliverability monitor fails with Cloudflare 1010 when hitting Resend API from GitHub Actions. |
| Stripe | Code passes locale to Customer Portal and Checkout, stamps `preferred_locales`, and captures Stripe customer-locale telemetry. Official Stripe APIs support portal and checkout locale, and Customer `preferred_locales`. | Needs live Stripe dashboard verification for Spanish Portal, Spanish Checkout, cancellation email language, and customer preferred locale. Portal return telemetry has only a small sample. |
| PostHog | Ops dashboards exist; recent events confirm many new telemetry streams. | Some dashboards are fed by broken classifiers; CSP alert setup script creates an insight but does not configure Slack notification automatically. Some critical events use null/legacy properties (`webhook.received.provider` is null for older rows). |
| Vercel | Production responds, deployment from latest nightly succeeded, CSP reporting endpoint is live. | `vercel.json` still includes `unsafe-eval` in production CSP; Vercel build logs warn memory config is ignored under Active CPU billing; deployment is heavy because photo assets are large. |
| Slack / GitHub Actions | Source-health and watchdog patterns exist; `SLACK_WEBHOOK_URL` is in use. | Some monitors fail before reaching Slack or are blocked by upstream APIs. There is no meta-monitor that alerts "the monitor itself failed". |

### External docs consulted

These were checked against primary documentation:

- Stripe Customer Portal session supports a `locale` parameter and `return_url`: https://docs.stripe.com/api/customer_portal/sessions/create
- Stripe Checkout session supports `locale`, including `es` and `es-419`: https://docs.stripe.com/api/checkout/sessions/create
- Stripe Customer object has `preferred_locales`: https://docs.stripe.com/api/customers/object
- Clerk CSP requires Turnstile in `script-src` and `frame-src`: https://clerk.com/docs/guides/secure/best-practices/csp-headers
- Resend webhook event types include email lifecycle events used by Pulpo: https://resend.com/docs/webhooks/event-types
- Resend tags are designed to be included in webhook events: https://resend.com/docs/dashboard/emails/tags
- Cloudflare 1010 means access was denied based on browser signature: https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/

## Product Health Scorecard

| Domain | Score | Rationale |
| --- | --- | --- |
| Core catalogue freshness | 7/10 | Latest SV catalogue is fresh and deployed, but featured data is stale and photo-path contract is broken for most non-top listings. |
| User-facing discovery UX | 6/10 | HeroV5 is visually coherent and responsive, but many shelf cards use generic placeholders because advertised local photos 404. Home has no in-page Pro CTA; conversion impact remains unproven. |
| Signup/billing funnel | 7/10 | Code has strong post-Stripe and locale fixes, but monitors around stuck invitations are unavailable from GitHub Actions and need live dashboard validation. |
| Email/deliverability telemetry | 4/10 | Resend webhook is active, but the classifier axis is broken, making delivery health dashboards unreliable. |
| Observability and alerts | 5/10 | Many dashboards/scripts exist; several are miswired, non-alerting, or run from an execution plane blocked by Cloudflare. |
| CI/test confidence | 5/10 | Unit/build/typecheck are strong; full E2E is stale/red and intentionally absent from CI; CSS and bundle guards are not active. |
| i18n/language consistency | 8/10 body, 6/10 metadata | Body copy passes i18n lint and public smoke, but `/start` document title remains English in Spanish mode. |
| Performance | 6/10 | Cached lab nav looks okay, but 404 image requests, large main bundle/CSS, and dead bundle guard need cleanup before confidence improves. |
| Design system soundness | 7/10 | Responsive public shell is stable and contrast passes. Admin widgets and photo fallback density need repair. |
| Data science/data quality | 6/10 | Ranking and validation are advanced, but source health is binary and misses brownouts; stale/cache/photo contracts need stricter canaries. |

## Confirmed Findings

### P0-1: Clerk stuck-invitation monitor is failing every 6h

**Evidence**

- Recent `Pulpo webhook health` workflow runs fail repeatedly, including `2026-06-02T20:33:34Z`, `15:55`, `09:59`, `02:31`, and many June 1 runs.
- Failure is in `scripts/check_stuck_invitations.py`:
  `GET https://api.clerk.com/v1/invitations?status=pending&limit=100 failed: 403 error code: 1010`.
- Cloudflare documents 1010 as a block based on browser signature.
- Open PR #636 (`fix/webhook-stuck-invitations-403`) exists and is related, but is currently behind main.

**Impact**

The exact alarm intended to catch paid users stuck before activation is unavailable. If a real paid user gets stuck, the workflow red state is easy to ignore and may not produce a clear Slack incident.

**Requirements**

- Merge or replace #636 with a monitor that survives Clerk API 403.
- Move the Clerk invitation query to an execution plane Clerk accepts: Vercel cron/function, Pulpo backend endpoint, or a runner with allowed egress.
- If Clerk query fails, emit `invitation.stuck_monitor_failed` to PostHog and Slack with error class, not just a GitHub Actions failure.
- Add a monitor heartbeat event: `monitor.webhook_health_completed { clerk_status, resend_status, stripe_status }`.
- Add an alert for absence of this monitor heartbeat for > 7h.

**Acceptance criteria**

- `Pulpo webhook health` is green for three consecutive scheduled runs.
- A forced Clerk query failure posts to Slack with a runbook link.
- PostHog has monitor success/failure history.
- No secret or email address is printed in logs.

### P0-2: Resend deliverability monitor is also blocked by Cloudflare 1010

**Evidence**

- `Pulpo email deliverability check` latest run on 2026-06-01 failed.
- Failure is `GET https://api.resend.com/domains failed: 403 error code: 1010`.
- This is the same execution-plane issue as Clerk.

**Impact**

The weekly check meant to catch DMARC/domain/sender regressions cannot run. Resend deliverability drift can recur without a working automated check.

**Requirements**

- Move `scripts/check_email_deliverability_recommendations.py` to a Vercel cron/function or other allowed execution plane.
- Keep GitHub workflow only as a wrapper if it calls the Pulpo-hosted monitor endpoint.
- Emit `monitor.resend_deliverability_completed { status, issue_count }`.
- Slack on `issue_count > 0`, and Slack on monitor execution failure.

**Acceptance criteria**

- Weekly deliverability check succeeds from the chosen runtime.
- A simulated domain issue yields a Slack message.
- A simulated API 403 yields a monitor-failed Slack message rather than a silent red workflow.

### P0-3: Resend lifecycle telemetry classifier is broken

**Evidence**

- PostHog recent lifecycle events show:
  - `newsletter.sent`, `email_type="unknown"`, `recipient_hash=null`
  - `newsletter.delivered`, `email_type="unknown"`, `recipient_hash=null`
- `api/resend-webhook.js` only parses `data.tags` when it is an array and then falls back to headers.
- Live data proves the assumption is wrong or incomplete: the tags/headers do not resolve to `email_type` or recipient hash.
- `scripts/check_webhook_health.py` rate checks filter denominator by `email_type='newsletter'`; denominators are zero and checks skip.

**Impact**

Email health dashboards look calm because they have no usable denominator. Bounce rate, complaint rate, unsubscribe rate, activation delivery, recipient-level delivery, and welcome/newsletter split are unreliable.

**Requirements**

- Update `api/resend-webhook.js` tag parsing to support:
  - Current Resend webhook payload shape observed from dashboard replay.
  - Existing array form for backward compatibility.
  - Headers if present.
- Add a `resend_webhook.classified` event or properties:
  - `email_type`
  - `recipient_hash_present`
  - `classification_source: tags | headers | unknown`
- Alert when `email_type="unknown"` rate exceeds 5% over the last 24h with denominator >= 10.
- Add unit tests using a captured real Resend webhook payload shape for sent/delivered/bounced/clicked.
- Replay one recent Resend event from the Resend dashboard after deployment.

**Acceptance criteria**

- Recent PostHog lifecycle events have non-null `email_type` and `recipient_hash` when the sender stamped them.
- Newsletter bounce/complaint/unsubscribe rate checks have non-zero denominators after the next send.
- Activation email delivery dashboard can split activation vs newsletter.

### P0-4: Resend heartbeat is a false-positive because it matches all `newsletter.*`

**Evidence**

- `scripts/check_webhook_health.py` defines the Resend family as `startsWith(event, 'newsletter.')`.
- PostHog shows many internal events under the same prefix, including `newsletter.commentary_generated`, `newsletter.issue_built`, `newsletter.welcome_reconcile_completed`, and `newsletter.send_succeeded`.
- These internal events can keep the "Resend" heartbeat green even if `/api/resend-webhook` stops receiving lifecycle events.

**Impact**

The monitor can miss the exact outage it was designed to detect.

**Requirements**

- Change the Resend webhook heartbeat to count only lifecycle events:
  `newsletter.sent`, `newsletter.delivered`, `newsletter.opened`, `newsletter.clicked`, `newsletter.bounced`, `newsletter.complained`, `newsletter.delivery_delayed`.
- Prefer a new explicit event `resend.webhook_received` emitted by `api/resend-webhook.js` on every verified webhook.
- Keep newsletter build/send cron heartbeat as a separate family.

**Acceptance criteria**

- Disabling the Resend dashboard webhook causes the Resend webhook heartbeat to alert even if newsletter build events continue.
- Internal newsletter jobs no longer satisfy the Resend lifecycle heartbeat.

### P1-1: `featured.json` is stale in production

**Evidence**

- Production `/data/featured.json` is served with `picked_at=2026-05-07` and `expires_at=2026-05-08`.
- Latest nightly logs show fresh featured selection generation.
- `.github/workflows/pulpo-nightly.yml` stages PA `featured.PA.json` but omits SV `web/data/featured.json` in the main data commit step.
- `git log -- web/data/featured.json` shows no updates since early feature PRs.

**Impact**

HeroV5 suppresses the legacy featured block under default flags, so this is not breaking the current first viewport. It is still a rollback and future-surface risk: any feature consuming `featured.json` serves a month-old pick.

**Requirements**

- Stage `web/data/featured.json` in the nightly commit step.
- Add a canary that fails if `featured.json.expires_at < now()` after the featured step.
- Add `featured_json_fresh` to `/api/nightly/health`.
- Add a frontend adapter guard: expired `featured.json` should be treated as unavailable rather than trusted.

**Acceptance criteria**

- Next nightly commit includes fresh `web/data/featured.json`.
- Production `/data/featured.json.expires_at` is within the current UTC day.
- Rollback to legacy featured block does not render expired copy.

### P1-2: Local photo-path contract is broken for ordinary cards

**Evidence**

- Current checkout: 884 of 959 `ranked.list.json` rows advertise `hero_photo_path` values whose root-level `web/photos/<file>.jpg` does not exist.
- Many files exist under `web/photos/_archive/<date>/`, while ranked records point at `/photos/<file>.jpg`.
- Production home requested 21 missing local photo URLs in one mobile load; `/browse` requested 11.
- PostHog last 7 days:
  - `image.stuck`, `source=home_shelf`, `is_local=true`: 377
  - `image.stuck`, `source=browse`, `is_local=true`: 260
  - `image.error`, `source=browse`, `is_local=true`: 215
  - `image.error`, `source=home_shelf`, `is_local=true`: 112
- Visual screenshot shows many generic mint fallback cards in shelves.
- Pipeline root cause likely: `_download_hero_photos()` prunes root photos based on the current post-validation listing set before the final retained/cached catalogue semantics are reflected, while ranked output continues to reference old root paths.

**Impact**

The UI does not blank because `Photo` falls back, but the first impression degrades and users pay for failed requests before seeing the fallback. Performance and trust suffer. The hero canary only checks top 10, so this can pass nightly.

**Requirements**

- Add a card-photo contract canary:
  - For every listing with `hero_photo_path`, the root static file must exist, or the field must be nulled before writing ranked output.
  - For top N browsable listings per shelf, at least 80% should have working local card photos unless explicitly waived.
- Fix pruning order or stale-listing merge semantics so archived photos are not referenced by current ranked records.
- Alternatively, update `hero_photo_path` to archive-aware URLs if archives are intended to remain serveable. Prefer root current assets over archive URLs for cache clarity.
- Add `photo_contract` to `/api/nightly/health`:
  - `ranked_with_local_path`
  - `local_path_exists`
  - `local_path_missing`
  - `top_shelf_missing`
- Add a Slack alert if `local_path_missing / ranked_with_local_path > 5%`.

**Acceptance criteria**

- Production home and `/browse` load with zero 404s for `/photos/*.jpg` in a 375px smoke test.
- PostHog local `image.error` and `image.stuck` counts drop to near-zero over 24h.
- Generic fallback cards become rare, not normal.

### P1-3: Full E2E smoke is red and not a CI gate

**Evidence**

- `.github/workflows/ci.yml` explicitly removed Playwright E2E from PR CI on 2026-05-25 due selector drift and runtime.
- Current full run fails against stale selectors:
  - Retired HeroV3/HeroV4/shoreline card selectors.
  - Hero CTA expectations after HeroV5 removed in-page CTA.
  - Admin/newsletter expected `.nl-widget`, while redesigned widget uses `.nl-preview-widget`.
  - Promo-code rollback test expected literal `{}` but locale is now always sent.
- Open PR #637 addresses part of this and is behind main.

**Impact**

Real browser coverage exists but cannot be trusted as a merge signal. Teams must remember which specs are still meaningful.

**Requirements**

- Merge or refresh #637.
- Split E2E into three suites:
  1. `e2e:critical` - public home, browse, detail, plans, start, account welcome, Stripe request mocks; runs in CI.
  2. `e2e:responsive` - 5 viewport sweep; nightly or visual PR requirement.
  3. `e2e:legacy` - retired rollback specs, quarantined and non-blocking.
- Replace CSS selectors for retired HeroV3/HeroV4 with HeroV5 selectors or delete obsolete rollback specs.
- Add a stale-selector linter for `.hp-hero-v3`, `.hp-hero-v4`, `.hp-shoreline`, `.nl-widget` unless explicitly marked as legacy.

**Acceptance criteria**

- `npm run e2e:critical` passes locally and in CI under 5 minutes.
- Full `e2e:smoke` either passes or is explicitly documented as non-gating legacy.
- No public UX PR merges without at least critical E2E.

### P1-4: CSS lint fails and is not in CI

**Evidence**

- `npm run lint:css` reports 29 stylelint errors in `web/app/styles/index.css`.
- CI frontend job does not run `npm run lint:css`.

**Impact**

Design-system drift accumulates silently. The project already has style rules but they are not enforced.

**Requirements**

- Fix existing stylelint errors.
- Add `npm run lint:css` to CI after the cleanup PR.
- Keep exceptions in comments only where necessary.

**Acceptance criteria**

- `npm run lint:css` passes on main.
- CI fails on new CSS lint errors.

### P1-5: Bundle-size guard is obsolete and not actionable

**Evidence**

- `npm run check:size` expects `web/dist/assets/index.js` and `index.css`.
- Actual Vite output is hashed under `web/dist/build/`, e.g. `index-BYSuxCFn.js`, `index-DsMEfgcf.css`.
- The script reports "not built" after a successful build.
- Current main JS and CSS exceed the old stated budgets, but the guard cannot see them.

**Impact**

Performance regressions can ship with a green build. The main bundle is large enough to merit active monitoring.

**Requirements**

- Update the size checker to discover Vite manifest/hash outputs.
- Track:
  - app entry JS gzip
  - CSS gzip
  - Clerk/Admin/account chunks
  - total first-load route assets for `/`, `/browse`, `/start`
- Decide budgets based on current baseline plus a small regression threshold.
- Add as warning first, then make blocking after two green weeks.

**Acceptance criteria**

- `npm run build && npm run check:size` reports real hashed files.
- CI publishes size deltas on PRs.
- A synthetic +50 KB entry bundle change fails once blocking mode is enabled.

### P1-6: `/start` Spanish document title is English

**Evidence**

- Production `/start?lang=es` renders Spanish body copy, but `document.title` is `Pulpo - Beach and lake homes in El Salvador, ranked by value`.
- `/start` mounts outside the main `App` branch, so `useDocumentMeta()` does not run there.

**Impact**

Spanish users see English browser title/search metadata on the paid acquisition entry point.

**Requirements**

- Add localized document meta handling inside `StartPage`, or mount `useDocumentMeta` for `/start`.
- Add test for `/start?lang=es` title and description.

**Acceptance criteria**

- `/start?lang=es` title and meta description are Spanish.
- `/start?lang=en` remains English.

### P1-7: Home conversion strategy is unresolved after HeroV5

**Evidence**

- HeroV5 has no in-page Pro CTA; all destination cards route to browse/discovery.
- PostHog last 9 days shows `paid_home_rendered` and HeroV5 views, but only one `upgrade.checkout_started` in the period sampled.
- Pre-HeroV5 home conversion used CTA routing and FreeMonthModal more directly.

**Impact**

The home page may now be discovery-led by design, or it may have accidentally lost a primary conversion path. This is a product decision, not just a code issue.

**Requirements**

- Product/Data Science to compare conversion before/after HeroV5:
  - `paid_home_rendered -> cta_routed -> free_month_modal.shown -> upgrade.checkout_started`
  - 2026-05-25 to 2026-05-31 vs 2026-06-01 to 2026-06-07.
- If conversion is down >10% with comparable traffic, add a Pro CTA back:
  - Header CTA on `/` only, or
  - sixth HeroV5 destination card that opens FreeMonthModal.
- If conversion is within +/-10%, keep discovery-led home and document it.

**Acceptance criteria**

- Product decision recorded.
- If CTA is restored, Vercel preview walks Stripe sandbox end-to-end.
- PostHog dashboard has HeroV5 conversion cohort pinned.

### P1-8: CSP violations still have recent unresolved samples

**Evidence**

- PostHog has 9 `csp.violation` events in the last 14 days.
- Recent production admin/sources violations block GitHub API calls under `connect-src`.
- Preview violations block Vercel live feedback script.
- `scripts/posthog_setup_csp_alert.py` creates the insight but prints "PostHog UI step: attach Slack notification"; it does not configure Slack automatically.

**Impact**

The CSP report endpoint works, but alerting is not fully wired. Admin surfaces may have degraded GitHub/autorepair context.

**Requirements**

- Decide whether admin/sources should call GitHub API directly from browser. If yes, allowlist `https://api.github.com` in `connect-src` with a comment and test. If no, proxy through backend.
- Add Slack notification to CSP insight manually or via script/API.
- Add `csp.violation` alert heartbeat to ops dashboard.
- Keep preview-only Vercel live script violations out of prod alerts or bucket them separately.

**Acceptance criteria**

- CSP violations for production are zero for 7 days, or explicitly accepted with runbook.
- A test violation causes Slack alert.

### P1-9: Source health treats brownouts as green

**Evidence**

- Latest data marks all sources green, but yields are thin:
  - `elagente=2` after recent 403 outage.
  - `nexo=5` after placeholder-photo outage.
  - `realtyelsalvador=100` recovered strongly.
- Current `source_status` is largely zero/non-zero and error-based.

**Impact**

The system can declare a source green when it is only partially recovered. Data Science sees skewed regional/source distributions without an alert.

**Requirements**

- Add per-source rolling baseline health:
  - last 7 successful counts median
  - current count ratio
  - `green`, `degraded`, `red`, `recovering`
- Alert if current count is <50% of 7-run median for two consecutive runs.
- Expose degraded sources in `/api/nightly/health` and admin/sources.

**Acceptance criteria**

- `nexo` and `elagente` show degraded/recovering until counts stabilize.
- Alert copies include count, median, ratio, and latest failure id if available.

### P2-1: `api/nightly/health` mixes PA and SV runs in `last_7_runs`

**Evidence**

- Production `/api/nightly/health` `last_7_runs` includes a PA scaffold run with total 20 and an SV run with total 959.
- The endpoint is named and consumed like the active production health endpoint, but run history is multi-country mixed.

**Impact**

Operators can misread a PA run as an SV collapse or vice versa.

**Requirements**

- Add `country_code` to run history rows if not already present.
- Filter `/api/nightly/health` by active country by default.
- Add optional `?country=PA` for PA health once `pa.pulpo.club` is active.

**Acceptance criteria**

- SV health endpoint `last_7_runs` shows only SV runs.
- PA run history is accessible separately.

### P2-2: Local Python tests are not hermetic

**Evidence**

- Local `PULPO_OFFLINE=1 pytest -q` failed because `.env` values leaked:
  - `DEEPSEEK_API_TOKEN` made a test call the LLM path.
  - `PULPO_SOURCES=kazu` reduced offline smoke output and wrote Kazu failure artifacts.
- Missing Pillow in local environment caused photo-quality tests to fail.

**Impact**

Developers can get false failures, mutate tracked/generated files, and accidentally spend API budget while running "offline" tests.

**Requirements**

- Add a test bootstrap that clears cost-bearing env vars unless a test explicitly opts in.
- Ensure `PULPO_OFFLINE=1` implies no LLM/network calls.
- Add dev setup docs or a `make setup` equivalent that installs Python image dependencies.
- Make generated artifacts go to temp dirs in tests.

**Acceptance criteria**

- `PULPO_OFFLINE=1 pytest -q` passes in a clean local virtualenv after documented setup.
- Running pytest does not modify `web/data` or `samples`.
- Tests fail if an LLM call is attempted under `PULPO_OFFLINE=1`.

### P2-3: Admin/newsletter surface and tests disagree

**Evidence**

- Responsive smoke expects `.nl-widget`; current implementation uses `.nl-preview-widget`.
- Full E2E fails admin/newsletter across all five viewports.
- Recent newsletter PRs changed UI significantly.

**Impact**

Admin UI may be okay, but the responsive smoke cannot validate it. The test is stale enough to hide real admin overflow.

**Requirements**

- Update responsive-smoke selector to `.nl-preview-widget`.
- Add one admin/newsletter smoke per viewport that asserts:
  - main widget visible
  - no horizontal overflow
  - primary test-send controls visible
  - per-newsletter language toggles visible
- Keep admin routes in a separate admin smoke suite.

**Acceptance criteria**

- Admin newsletter responsive smoke passes at 320, 375, 414, 768, 1280.

### P2-4: Image error telemetry is untyped or under-specified

**Evidence**

- Runtime emits `image.error` and `image.stuck`; PostHog confirms data.
- `web/app/telemetry/events.ts` search did not show typed entries for these events during audit.

**Impact**

Critical image health telemetry can drift without type checking.

**Requirements**

- Add typed event registry entries for `image.error` and `image.stuck`.
- Include properties:
  - `url`
  - `listing_id`
  - `idx`
  - `source`
  - `is_local`
  - `was_cached_likely` for stuck
- Add image-health dashboard thresholds.

**Acceptance criteria**

- Event registry type-checks call sites.
- Dashboard shows image error/stuck per 100 sessions by surface.

### P2-5: Stripe/Clerk/Resend integration verification needs a recurring live ritual

**Evidence**

- Code has locale/CSP/invitation protections.
- Live dashboard checks are still required to prove:
  - Stripe Portal Spanish UI.
  - Stripe Checkout Spanish UI.
  - Stripe `preferred_locales` on customers.
  - Stripe cancellation email language.
  - Clerk invitation creation and acceptance.
  - Resend activation delivery and tags.

**Impact**

Local tests cannot fully validate hosted surfaces and provider dashboards.

**Requirements**

- Add a monthly integration drill runbook:
  1. Create paid test user in Spanish.
  2. Verify Stripe Checkout Spanish.
  3. Verify activation email in Spanish and Resend webhook classification.
  4. Set password via Clerk invitation.
  5. Open portal in Spanish.
  6. Cancel subscription.
  7. Verify account page canceling copy, Stripe customer `preferred_locales`, and cancellation email language.
- Automate what can be automated; document screenshots required for hosted surfaces.

**Acceptance criteria**

- Last integration drill date visible in ops dashboard or docs.
- Drill failures create issues automatically.

### P2-6: Bundle splitting and first-load performance need a focused pass

**Evidence**

- Build warnings say modules are both statically and dynamically imported.
- Main app entry and CSS are large for a public acquisition page.
- `/start` is mounted separately and light, but home/browse still carry a broad app shell.

**Impact**

Performance may be fine on cached lab runs but vulnerable on first-load mobile and LATAM networks, especially with image 404s.

**Requirements**

- Fix double static/dynamic import warnings.
- Route-split admin, account, Clerk-heavy code, and non-home surfaces.
- Add RUM metrics to PostHog for:
  - LCP
  - CLS
  - INP or interaction latency proxy
  - route
  - locale
  - device class
- Add a Lighthouse/Playwright perf budget for `/`, `/browse`, `/start`.

**Acceptance criteria**

- No Vite mixed import warnings.
- Entry JS and CSS budgets tracked in CI.
- Home mobile P75 LCP under agreed target in PostHog.

### P2-7: Design reference coverage is incomplete

**Evidence**

- HeroV5 is now the production home entrypoint.
- Visual screenshots exist from this audit, but no committed design reference contract was confirmed for HeroV5 in `docs/design-references`.

**Impact**

Future home edits can drift without visual comparison.

**Requirements**

- Add committed desktop and mobile HeroV5 references.
- Add browse mobile reference focused on card photo/fallback density.
- Add visual checklist to PR template for Discover/Browse/Detail changes.

**Acceptance criteria**

- Design refs exist and are linked from CLAUDE.md.
- Future visual PRs attach before/after screenshots.

### P3-1: `nightly_summary.py` can mislead outside workflow context

**Evidence**

- Local execution reported "Commit: NOT REACHED / pulpo.club will NOT refresh this run" while production was serving June 2 data and the workflow had committed/deployed.
- The script appears to rely on workflow-context artifacts absent from a normal checkout.

**Impact**

Operators may misdiagnose a healthy run as not deployed when running diagnostics locally.

**Requirements**

- Add a mode label:
  - `workflow_context`
  - `local_checkout_context`
- In local mode, read GitHub API or `/api/nightly/health` before claiming deploy status.
- Support `--help` without mutating tracked files for all audit scripts.

**Acceptance criteria**

- Local summary cannot state "will NOT refresh" without checking production or an explicit workflow artifact.

### P3-2: `audit_last_run.py --help` mutates tracked sample output

**Evidence**

- Running `python3 scripts/audit_last_run.py --help` executed the audit and rewrote `samples/last_run_audit.txt`.

**Impact**

CLI ergonomics can accidentally dirty working trees.

**Requirements**

- Add argparse help.
- Default write path to stdout or require `--write`.
- Add a test that `--help` exits 0 and does not write.

**Acceptance criteria**

- Running `--help` leaves git status unchanged.

### P3-3: Production CSP still uses `unsafe-eval`

**Evidence**

- Production CSP header includes `script-src 'unsafe-inline' 'unsafe-eval'`.
- Clerk docs note production `unsafe-eval` should be removed where not required.

**Impact**

Security hardening debt. Not the most urgent product bug, but should be tracked.

**Requirements**

- Audit whether Vite + Clerk current production needs `unsafe-eval`.
- Remove in a CSP-only PR with report-only preview first.

**Acceptance criteria**

- CSP report-only for 48h shows zero eval-related breakage.
- Enforced CSP removes `unsafe-eval`.

## Phased Roadmap

### Phase 0: Merge already-started recovery PRs

**Goal**

Clear existing recovery work before opening duplicate branches.

**Work**

- PR #636: `fix/webhook-health): handle Clerk 403 so the heartbeat workflow stays observable`
  - Rebase onto main.
  - Confirm it does not merely downgrade a failing monitor into silence.
  - Add Slack/PostHog monitor-failed signal if missing.
- PR #637: `chore(e2e): unstick e2e:smoke against hero_v5 default-on + redesigned admin`
  - Rebase onto main.
  - Extend to newsletter responsive selector drift if not covered.

**Acceptance**

- Both PRs merge or are superseded by stronger PRs from Phase 1.

### Phase 1: Restore observability truth

**PR 1A: Resend lifecycle classification fix**

Files:

- `api/resend-webhook.js`
- `tests/api/resend-webhook.test.js` or equivalent
- `web/app/telemetry/events.ts`
- `scripts/check_webhook_health.py`

Requirements:

- Parse real Resend webhook payload tags/headers.
- Emit non-null `email_type` and `recipient_hash` where sender provided them.
- Change Resend heartbeat from `startsWith(newsletter.)` to lifecycle-only.
- Add unknown-classification alert.

Verification:

- Replay Resend event.
- PostHog shows `email_type=activation|newsletter`, `recipient_hash != null`.
- `python3 scripts/check_webhook_health.py --dry-run` reports lifecycle heartbeat from actual lifecycle event only.

**PR 1B: Move blocked provider monitors out of GitHub runner**

Files:

- `scripts/check_stuck_invitations.py`
- `scripts/check_email_deliverability_recommendations.py`
- `.github/workflows/pulpo-webhook-health.yml`
- `.github/workflows/pulpo-deliverability-check.yml`
- new API/cron wrapper if using Vercel

Requirements:

- Clerk and Resend API calls run from an allowed execution plane.
- GitHub workflow cannot be the only place provider failures surface.
- Add monitor heartbeat and failure events.

Verification:

- Three green scheduled runs.
- Simulated provider 403 posts Slack.

**PR 1C: CSP alert completion**

Files:

- `scripts/posthog_setup_csp_alert.py`
- `vercel.json` if admin GitHub API is intentionally allowlisted
- admin/sources code if proxying GitHub through backend

Requirements:

- Slack notification actually attached or replaced with a script-owned alert.
- Production CSP violations triaged.

Verification:

- Test violation triggers alert.
- Production admin/sources no longer emits GitHub connect-src violations.

### Phase 2: Repair catalogue/photo data contracts

**PR 2A: `featured.json` freshness**

Files:

- `.github/workflows/pulpo-nightly.yml`
- `web/app/data/featured.ts`
- `api/nightly/health.js`
- tests for nightly staging if available

Requirements:

- Stage SV `featured.json`.
- Fail or warn if expired.
- Treat expired frontend featured data as unavailable.

Acceptance:

- Production `/data/featured.json` fresh after next nightly.

**PR 2B: Card photo-path canary**

Files:

- `automation/run.py`
- `pulpo/cli.py`
- `.github/workflows/pulpo-nightly.yml`
- tests around photo pruning and ranked output

Requirements:

- No ranked row may point at missing root local photo.
- Add per-shelf/top-N local photo coverage threshold.
- Fix prune/archive ordering.

Acceptance:

- Home/browse production smoke reports zero local `/photos/*.jpg` 404s.
- PostHog local image errors collapse.

**PR 2C: Source brownout health**

Files:

- `automation/watchdog.py`
- `scripts/check_source_health.py`
- `api/nightly/health.js`
- admin/sources widget

Requirements:

- Add degraded/recovering states from rolling median.
- Expose in public/admin health.

Acceptance:

- Thin-yield sources are visible as degraded until stable.

### Phase 3: Restore QA confidence

**PR 3A: E2E critical suite**

Files:

- `tests/e2e/*`
- `package.json`
- `.github/workflows/ci.yml`

Requirements:

- `e2e:critical` green and CI-gated.
- Retired selectors quarantined.
- Admin newsletter smoke corrected.

Acceptance:

- CI runs critical browser suite in under 5 minutes.

**PR 3B: CSS and bundle guardrails**

Files:

- `web/app/styles/index.css`
- `web/app/styles/check-bundle-size.mjs`
- `.github/workflows/ci.yml`

Requirements:

- CSS lint green and CI-gated.
- Size checker discovers hashed Vite outputs.
- Budgets initially warn, later block.

Acceptance:

- CI fails for new CSS lint errors and meaningful bundle regressions.

**PR 3C: Hermetic Python tests**

Files:

- pytest fixtures/config
- tests touching LLM/env
- docs/dev setup

Requirements:

- Clear cost-bearing envs under offline tests.
- Install/document Pillow.
- No generated artifact mutations.

Acceptance:

- `PULPO_OFFLINE=1 pytest -q` passes locally without touching tracked/generated data.

### Phase 4: Product and funnel decisions

**PR 4A: HeroV5 conversion decision**

Requirements:

- Data Science compares pre/post HeroV5 home conversion.
- Product decides discovery-led vs restored CTA.

Acceptance:

- Decision documented.
- If CTA added, Stripe sandbox walkthrough passes.

**PR 4B: `/start` metadata localization**

Requirements:

- Spanish `/start` title and description are Spanish.

Acceptance:

- Browser title tests pass.

**PR 4C: Integration drill runbook**

Requirements:

- Monthly Clerk/Stripe/Resend live walkthrough.
- Dashboard or docs show last drill date.

Acceptance:

- First drill completed and linked.

### Phase 5: Performance and design polish

**PR 5A: Image and route performance**

Requirements:

- Fix mixed dynamic/static imports.
- Route-split non-home chunks.
- Add RUM metrics for LCP/CLS/INP proxy.

Acceptance:

- No Vite split warnings.
- P75 route metrics visible in PostHog.

**PR 5B: Design references**

Requirements:

- Commit HeroV5 desktop/mobile references.
- Commit browse mobile photo-density reference.
- Add CLAUDE.md visual diff reminder.

Acceptance:

- Future home/browse/detail PRs compare against references.

## Data Science Requirements

### Source health model

Data Science should own thresholds with Engineering implementation.

Inputs:

- `source_health_history.jsonl`
- `run_history.json`
- `last_updated.json.per_source_raw`
- validation pass/drop counts

Outputs:

- `source_status`: `green | degraded | recovering | red`
- `source_count_ratio`
- `rolling_median_7`
- `consecutive_degraded_runs`

Questions:

- What is the minimum acceptable yield for low-volume sources like `elagente`?
- Should source confidence affect ranking exposure?
- Should a source in `degraded` state appear in shelf composition limits?

### Photo coverage model

Metrics:

- root local thumbnail exists
- root local hero exists
- hires exists
- card_eligible
- hero_eligible
- shelf top-N coverage

Targets:

- Top 50 browseable listings: 95% working local thumbnail.
- Each home shelf first viewport: 90% working local thumbnail.
- Top 10 hero candidates: 100% safe hero variant.

### Funnel model

Product/Data Science should produce weekly readouts for:

- HeroV5 destination click rate.
- Browse-to-detail rate.
- Detail-to-paywall/upgrade rate.
- Home render to checkout started.
- Start page conversion.
- Activation completion within 1h and 24h.
- Subscription cancellation portal return state change rate.

## Product Requirements

### Discovery and Pro conversion

Open decision:

- Keep home discovery-led, or add a Pro CTA back.

Decision rule:

- If post-HeroV5 `paid_home_rendered -> upgrade.checkout_started` is down more than 10% vs pre-HeroV5 with comparable traffic, add CTA.
- If within +/-10%, document discovery-led home as intentional.

### Trust and media quality

Public surfaces should not normalize generic placeholder cards when the product promise is ranked, curated real estate.

Requirements:

- First viewport home shelves should show real property photos in most cards.
- Fallback art remains a graceful last resort, not the common state.
- Data contract should prevent false local-photo URLs.

### Language consistency

Requirements:

- Any route reachable in Spanish must have Spanish body, title, meta description, hosted Stripe/Clerk UI, and emails where user-facing.
- `/start` metadata is the immediate gap.
- Stripe/Clerk/Resend live drill validates hosted surfaces.

## Engineering Requirements

### Monitor architecture

Principle:

Monitoring is part of the product. A monitor that fails silently is itself an incident.

Requirements:

- Every monitor emits a success/failure heartbeat.
- Provider API monitors must run from a compatible execution plane.
- Slack alerts include runbook URL and error class.
- PostHog stores monitor outcomes for dashboards.

### Telemetry contracts

Requirements:

- Every event added to code must exist in `web/app/telemetry/events.ts` or server event registry if available.
- Every lifecycle webhook event carries classifier axes:
  - provider
  - email_type or webhook_family
  - source
  - hashed recipient/user id when safe
- Unknown classifier rate is alertable.

### CI contracts

Requirements:

- CI must cover:
  - pytest
  - ruff
  - country hardcode guard
  - typecheck
  - i18n lint
  - Vitest
  - build
  - CSP diff guard
  - home/newsletter version bump guards
  - CSS lint after cleanup
  - bundle-size check after repair
  - critical E2E after suite pruning

## Design Requirements

### Public UX

Current observations:

- Home HeroV5 is visually coherent, no horizontal overflow in public smoke.
- Cookie modal covers central hero card on first mobile load; acceptable but should be included in reference screenshots.
- Many home/browse cards show generic mint fallback due missing photos.
- Browse page can become visually repetitive when fallback density is high.

Requirements:

- Add visual references for HeroV5 and browse fallback-density.
- Treat fallback density as design quality metric.
- Keep text inside buttons/cards responsive; no overflow seen in tested public routes, preserve this.

### Admin UX

Requirements:

- Newsletter widget selectors and responsive tests must reflect redesigned UI.
- Admin widgets should have mobile overflow checks if they are expected to be usable on mobile.

## Integration Requirements

### Clerk

Current status:

- CSP Turnstile allowlist present in production.
- Clerk events appear in PostHog.
- Invitation monitor from GitHub runner blocked.

Requirements:

- Provider API monitor from allowed runtime.
- Monthly invitation create/accept drill.
- Alert on stuck invitations and monitor failure.

### Resend

Current status:

- Webhook endpoint active; lifecycle events received.
- Classification broken.
- Deliverability API monitor blocked from GitHub runner.
- `PULPO_ACTIVATION_FROM_EMAIL` override detected in PostHog 16 times over 7 days; review whether intentional.

Requirements:

- Fix lifecycle parser.
- Move deliverability monitor.
- Alert on unknown email type.
- Alert on monitor failure.
- Dashboard can split activation/newsletter/contact/admin_test.

### Stripe

Current status:

- Code supports Customer Portal locale, Checkout locale, and customer `preferred_locales`.
- Official docs confirm locale fields.
- Telemetry for `stripe.billing_portal_session_created` and `stripe.customer_locale_set` exists but sample is small.

Requirements:

- Live drill validates:
  - portal Spanish
  - checkout Spanish
  - cancellation confirmation email language
  - customer preferred locale
  - post-portal return polling

### PostHog

Current status:

- Ops dashboards and insights exist.
- Some insights are fed by broken classifier data.
- CSP alert requires Slack wiring.

Requirements:

- Dashboard validation after telemetry fixes.
- Unknown classifier and monitor heartbeat alerts.
- Funnel dashboard should use true funnel/conversion windows, not just event count tables, for decision work.

### Vercel

Current status:

- Production deploys and serves data.
- CSP reporting headers present.
- Static photo deployment/rewrite contract currently broken by archived asset paths.

Requirements:

- Fix photo static asset contract.
- Remove ignored memory config warnings or document.
- Track deploy artifact size.
- Consider Blob/CDN storage for photos if repo/deploy size keeps growing.

### Slack/GitHub Actions

Current status:

- Slack webhook exists and is reused.
- Some monitors fail in GitHub without producing a clear provider-specific Slack alert.

Requirements:

- Each scheduled workflow should either:
  - complete successfully and emit heartbeat, or
  - notify Slack on failure with run URL.
- Avoid relying on GitHub-hosted runners for provider APIs that Cloudflare blocks.

## Verification Matrix

| Workstream | Verification |
| --- | --- |
| Resend parser | Replay real webhook; PostHog lifecycle has `email_type` and `recipient_hash`; rate checks have non-zero denominators. |
| Clerk monitor | Three green scheduled runs; simulated 403 posts Slack and PostHog monitor failure. |
| Deliverability monitor | Weekly check runs from allowed runtime; simulated issue posts Slack. |
| Featured freshness | Production `/data/featured.json.expires_at` current; frontend ignores expired featured data. |
| Photo contract | Production `/` and `/browse` have zero local photo 404s; top shelf photo coverage exceeds target. |
| E2E critical | CI-gated critical suite green under 5 minutes. |
| CSS lint | `npm run lint:css` green and CI-gated. |
| Bundle guard | Hashed Vite bundles measured; PR delta visible. |
| `/start` metadata | Spanish route title/meta Spanish. |
| HeroV5 conversion | Data Science readout with decision recorded. |
| Integration drill | Clerk/Resend/Stripe screenshots/logs attached to monthly check. |

## Open Questions

1. Should home remain discovery-led with no Pro CTA, or should Pro conversion return to the first viewport?
2. Is `PULPO_ACTIVATION_FROM_EMAIL` override intentional in production? If yes, document the desired value and owner.
3. Should archived photos ever be served publicly, or should ranked records never point at archived assets?
4. What is the acceptable fallback-image density on home shelves?
5. Should admin surfaces be first-class responsive surfaces or desktop-only tools? Tests should reflect the decision.
6. Should PA runs be exposed in the same public health endpoint or split by country domain now?

## Non-Goals

- Rewriting the data pipeline wholesale.
- Replacing Clerk, Resend, Stripe, PostHog, or Vercel.
- Building a full data warehouse before fixing the JSONL/source-health contracts.
- Making every E2E spec blocking; only the critical subset should gate CI.
- Removing all CSP inline allowances in the same tranche as product reliability fixes.

## Proposed Ownership

| Area | Owner |
| --- | --- |
| Monitor execution plane and Slack heartbeat | Engineering |
| Resend lifecycle parser and deliverability dashboards | Engineering + Data Science |
| Photo-path contract and source brownout model | Data Engineering + Data Science |
| HeroV5 conversion decision | Product + Data Science |
| E2E/CI restore | Engineering |
| Design references and fallback-density standard | Product Design + Engineering |
| Stripe/Clerk/Resend monthly drill | Product Ops + Engineering |

## Appendix: Commands Run

Representative commands and checks from the audit:

```bash
npm run typecheck
npm run build
npm run test
npm run lint:css
npm run check:contrast
npm run check:size
PULPO_OFFLINE=1 pytest -q
python3 automation/watchdog.py --data-dir web/data
python3 scripts/check_webhook_health.py --dry-run
python3 scripts/check_source_health.py --dry-run
python3 scripts/posthog_setup_ops_dashboards.py --dry-run
gh run list --limit 40
gh run view <workflow-run> --log
curl https://pulpo.club/api/nightly/health
curl https://pulpo.club/data/ranked.json
curl https://pulpo.club/data/featured.json
Playwright production smoke for /, /browse, /plans, /start, legal routes, /contact
PostHog HogQL queries for webhook, image, CSP, funnel, portal, and email lifecycle events
```

## Appendix: Current Open PRs Relevant To This PRD

| PR | Relevance |
| --- | --- |
| #636 `fix/webhook-health): handle Clerk 403 so the heartbeat workflow stays observable` | Partially addresses P0-1. Needs rebase and validation that monitor failure alerts, rather than just suppressing failure. |
| #637 `chore(e2e): unstick e2e:smoke against hero_v5 default-on + redesigned admin` | Partially addresses P1-3. Needs rebase and may need expansion for admin/newsletter responsive selector drift. |
