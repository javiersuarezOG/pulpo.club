# Observability — Pulpo

## Stack

| Surface | Tool | Why |
|---|---|---|
| Product analytics + funnels | **PostHog** (EU host, cloud) | Auto-segments by country/device/browser; built-in funnels, retention, feature flags, session replay. Free up to 1M events/mo. |
| Web Vitals (LCP/INP/CLS/TTFB) | `web-vitals` → PostHog events | Real-user perf, segmentable by device/route. |
| Server runtime | Vercel runtime logs | Single-line `[api] <name> status=… ms=…` per request, grep-able. |
| Pipeline health | `web/data/last_updated.json` | Per-source green/yellow/red; field-population rates per release. |

## Setup

PostHog requires two Vercel env vars:

```
VITE_POSTHOG_KEY    = <project API key from PostHog dashboard>
VITE_POSTHOG_HOST   = https://eu.i.posthog.com   # default
```

Without them, `track()` silently no-ops — production safe (the FE just doesn't telemeter), but no funnels appear in PostHog. Set both before PR-10 cutover.

## Where the gates fire

- **Local `vite dev`:** silent unless `?ph=1` URL flag.
- **Vercel preview deploys:** active (so we can verify events on PR review).
- **Production:** active.

PostHog JS is lazy-loaded inside `requestIdleCallback` (~50KB gzipped, not first-paint-critical). Autocapture is **off** — we use the explicit typed catalog at `web/app/telemetry/events.ts`.

## Privacy

- No PII in event payloads. `listing_id`, `auth_state`, etc. — no broker emails, no listing addresses.
- Session replay sample rate: 10%, all input fields masked.
- `consent.declined` blocks all subsequent events client-side.
- Server-side logs hash any email-like field with a server-only salt before logging (post-PR-9).

---

## Event catalog

Source of truth: [`web/app/telemetry/events.ts`](../web/app/telemetry/events.ts). Adding an event = adding a row there; the typed contract rejects unknown names + wrong payload shapes at build time.

### Acquisition

| Event | Payload | Fires from | Funnel position |
|---|---|---|---|
| `landing.viewed` | `{ route }` | App mount ([app.jsx:120](../web/app/app.jsx)) | Funnel start |
| `consent.granted` / `consent.declined` | `{ region? }` | ConsentBanner — **declared, not yet fired** | Privacy gate |

### Discover surface

| Event | Payload | Fires from |
|---|---|---|
| `hero.cta_clicked` | `{ destination: "browse" \| "see_listing" }` | Hero CTA buttons ([pages.jsx](../web/app/pages.jsx)) |
| `shelf.scrolled` | `{ shelf_key, scroll_pct, items_visible }` | (declared, not yet fired) |
| `shelf.see_all_clicked` | `{ shelf_key }` | "See all" buttons |
| `style_carousel.tile_clicked` | `{ style_key }` | StyleCarousel tile click |
| `card.clicked` | `{ listing_id, source_view, source_shelf? }` | Listing-card click on Discover/Browse/Saved |
| `view_original.clicked` | `{ listing_id, source_label }` | "View on source" CTA on Detail panel |

### Browse surface

| Event | Payload | Fires from |
|---|---|---|
| `browse.filter_changed` | `{ filter_key, value, active_count }` | (declared, not yet fired across all filters) |
| `browse.sort_changed` | `{ sort }` | Sort dropdown |
| `browse.view_toggled` | `{ view: "cards" \| "table" }` | View toggle |
| `browse.empty_results` | `{ filters }` | Empty-state render |
| `browse.price_histogram.dragged` / `.bar_clicked` / `.reset` | various | Price-histogram interactions |

### Detail / Saves

| Event | Payload | Fires from |
|---|---|---|
| `detail.opened` | `{ listing_id, auth_state, plan? }` | Detail panel mount per listing |
| `detail.photo_lightbox_opened` | `{ listing_id }` | Lightbox open |
| `save.toggled` | `{ listing_id, auth_state, action: "add" \| "remove" }` | Heart click on cards |

### Auth (Clerk + legacy paths share these)

| Event | Payload | Fires from |
|---|---|---|
| `signup_modal.shown` | `{ trigger, mode }` | `app.openSignup` — every modal-open ([app.jsx](../web/app/app.jsx)) |
| `signin.completed` | `{ provider, plan }` | First user-state transition null → signed-in (auth-telemetry effect, [app.jsx](../web/app/app.jsx)) |
| `signup.completed` | `{ provider }` | Same transition, **only when** the SignupModal was open with `mode="signup"` |
| `auth.signout_started` | `{ had_clerk_actions }` | Logout button click — fires before any state change. Pair with `signout.completed` to detect signOut hangs / cookie re-hydration |
| `signout.completed` | `{}` | User-state transition signed-in → null |

**Trigger derivation for `signup_modal.shown`:**

- `pendingSave` set → `trigger: "heart"`
- `pendingAction === "checkout"` → `trigger: "checkout"`
- `pendingListing` set → `trigger: "pendingListing"`
- otherwise → `trigger: "manual"` (e.g. topnav avatar, footer plans)
- `mode` mirrors the SignupModal's `mode` prop (`signup` or `login`).

**Provider mapping:**

- Legacy `signin()` callback: `provider="legacy"` (or whatever was passed in — typically `"email"` or `"google"`).
- Clerk hosted modal: `provider="clerk"` (Clerk's own `OAuthMethod` is not surfaced through to the auth-state transition; if you need that granularity later, intercept `signUp` in `clerk-bundle.jsx`).

### Plans / Upgrade (Stripe Checkout)

| Event | Payload | Fires from |
|---|---|---|
| `plans.viewed` | `{ source }` | Plans page mount (declared, fire site varies) |
| `paywall.shown` | `{ kind, listing_id? }` | Off-market detail overlay ([pages.jsx](../web/app/pages.jsx)) and save-cap rejection ([app.jsx](../web/app/app.jsx)) |
| `paywall.bypassed` | `{ kind, action, listing_id? }` | Click through paywall — `action="upgrade"` for See plans, `action="have_account"` for I-have-an-account |
| `upgrade.checkout_started` | `{}` | `startStripeCheckout` first line — fires on every Pro CTA click ([stripe-checkout.js](../web/app/auth/stripe-checkout.js)) |
| `upgrade.checkout_returned` | `{ result: "success" \| "cancelled" }` | App mount when `?upgrade=…` param is present ([app.jsx](../web/app/app.jsx)) |

### Manage subscription (Stripe Customer Portal — PR-9.5)

| Event | Payload | Fires from |
|---|---|---|
| `portal.opened` | `{}` | `openStripePortal` first line — fires on every Manage plan click ([stripe-portal.js](../web/app/auth/stripe-portal.js)) |
| `portal.error` | `{ reason }` | Server returned non-200 OR network error. `reason` ∈ `{ network, sign_in_required, no_customer, no_url, http_<n>, stripe_error, auth_failed }` |

### Locale + system

| Event | Payload | Fires from |
|---|---|---|
| `locale.changed` | `{ from, to }` | LocaleToggle |
| `data.fetch.failed` | `{ stage, error_class }` | `useListings` fetch error path |
| `client.error` | `{ message, stack? }` | Top-level ErrorBoundary |
| `api.error` | `{ endpoint, status, reason?, detail? }` | Any non-2xx response from `/api/saves`, `/api/stripe/*`. Wired in `saves-client.js`, `stripe-checkout.js`, `stripe-portal.js`. Lets the dashboard see API failure rate without needing Vercel runtime-log access. |

### Web Vitals

| Event | Payload | Fires from |
|---|---|---|
| `web_vitals.lcp` / `.inp` / `.cls` / `.ttfb` | `{ value, rating, route }` | [`web-vitals.ts`](../web/app/telemetry/web-vitals.ts), booted in `app.jsx` |

### App-specific perf

| Event | Payload | Fires from |
|---|---|---|
| `card.photo_nav_latency` | `{ listing_id, from_idx, to_idx, ms }` | Card photo arrow click |
| `perf.card_image_load` | `{ listing_id, idx, ms, source }` | Eager card image (above-the-fold on Browse / Discover / Saved). Fires on `<img onLoad>` for cards rendered with `priority`. Lazy cards do not emit — their fetch is intersection-deferred and would mostly measure idle scroll time. |
| `perf.data_fetch` | `{ file, ms, bytes, cache }` | `useListings` data fetch |
| `perf.filter_recompute` | `{ ms, result_count, active_filters }` | Browse filter pipeline |
| `perf.detail_open` | `{ listing_id, ms }` | Card click → detail render |
| `perf.lightbox_open` | `{ listing_id, ms }` | Detail thumb click → lightbox |
| `perf.route_transition` | `{ from, to, ms }` | `app.go(...)` |

### Server-side (`logApi`)

Every API endpoint logs a single grep-friendly line per request:

```
[api] saves status=200 ms=42 op=add count=4 plan=pro
[api] stripe.create_checkout_session status=200 ms=312 user_id=user_… session_id=cs_…
[api] stripe.billing_portal status=200 ms=187 user_id=user_… session_id=bps_…
[api] stripe.webhook status=200 ms=88 type=customer.subscription.updated event_id=evt_…
```

Use Vercel's runtime-logs grep to triage: search for `status=5\d\d` to surface failures, `status=4\d\d` for auth/validation issues. The `ms=` field is the wall-clock latency.

---

## Funnels (built in PR-10)

1. **Click-through (primary success metric):**
   `landing.viewed → card.clicked → detail.opened → view_original.clicked`.

2. **Acquisition + activation:**
   `landing.viewed → card.clicked → detail.opened → save.toggled → signup_modal.shown → signup.completed → signin.completed`.
   (`signup.completed` and `signin.completed` are paired — the former is the new-user marker, the latter is every-transition marker. Pin both as funnel completion criteria depending on the question.)

3. **Save funnel:**
   `card.clicked → save.toggled (gated:true) → signup_modal.shown(trigger=heart) → signup.completed`.

4. **Off-market paywall:**
   `detail.opened (auth=free|anonymous) → paywall.shown(kind=off_market) → paywall.bypassed.action=upgrade → plans.viewed → upgrade.checkout_started → upgrade.checkout_returned(result=success)`.

5. **Subscription management:**
   `portal.opened → … (Stripe Portal off-platform) … → next page-mount → re-derived plan via Clerk session refresh`.
   Server-side: `stripe.webhook customer.subscription.updated|deleted` is the source of truth for plan flips. PostHog Insights can pin the wall-clock between `portal.opened` and the next webhook-driven plan transition (visible via subsequent `signin.completed` payloads when plan changes).

PostHog auto-segments each of the above by country, device_type, browser, referrer — no extra instrumentation.

---

## Currently dormant events

Declared in `events.ts` but no call site as of 2026-05-08:

- `shelf.scrolled` — granular per-shelf event isn't fired
- `browse.filter_changed` — partial coverage (price histogram, sort, view); other filters not yet wired
- `plans.viewed` — declared, fire site needs adding to the Plans page mount

`consent.granted` / `consent.declined` were wired in PR-177; both fire from `ConsentBanner` and PostHog `optIn()`/`optOut()` is now consent-gated in `telemetry/client.ts`.

Track the remaining dormant events in `BACKLOG.md` under "Telemetry → wire dormant events" so they don't slip.

## Adding an event

1. Add the entry in `web/app/telemetry/events.ts` (key + payload type).
2. Import `track` directly in the component, call `track('your.event', { ... })`.
3. PostHog's typed contract rejects unknown events at build time.
4. PR description should list any new events introduced.
5. **Update this doc** — the catalog above is the human-readable mirror of `events.ts`. Don't let them drift.

---

## Performance baseline (Lighthouse)

We capture a Lighthouse run after every prod-shape change so regressions are diff-able rather than guessed at.

Procedure:

```bash
# Headless run against prod (or a Vercel preview URL)
npx lighthouse https://pulpo.club/ \
  --output json --output html \
  --output-path docs/observability/lighthouse-YYYY-MM-DD \
  --chrome-flags="--headless"
```

Both files (`lighthouse-YYYY-MM-DD.report.json` + `.report.html`) commit to `docs/observability/`. The JSON is the diff source; the HTML is for humans.

When to capture:

- After **PR-A** (prod Clerk key rotation) — **next baseline owed**, currently blocked: prod is still serving Clerk dev keys (concrete-mackerel-86), and Vercel Security Checkpoint sometimes 403s the homepage. Capture once both are clean so the baseline isn't poisoned.
- After any change to the entry HTML, the bundle splitter, or the data-loading shape (`ranked.json`, listing-detail JSON, hero images).
- Once per quarter even with no change, so we catch dependency-driven creep.

What "good" looks like for the new app right now:

- LCP ≤ 2.5s on 4G mobile sim.
- CLS ≤ 0.1 — hero swap is the usual offender; the rotation is `position: absolute` over a fixed-height container and *should* be cumulative-shift-free.
- INP ≤ 200ms — Discover and Browse are shelf-scroll-heavy; watch the long-task list.
- TBT ≤ 200ms — `clerk-bundle.js` (80KB gzipped) is lazy-loaded behind `clerkEnabled()`; if it shows up in the main critical path, something regressed.

`web/app/telemetry/web-vitals.ts` already streams real-user LCP/INP/CLS/TTFB into PostHog (`web_vitals.lcp`, `web_vitals.inp`, `web_vitals.cls`, `web_vitals.ttfb`) — Lighthouse is a synthetic checkpoint on top of that.
