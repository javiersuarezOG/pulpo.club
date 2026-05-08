# Pulpo · Backlog

Living list of follow-ups, untested caveats, and pre-existing tech debt. Work
items here are explicitly *not yet scheduled* — when you pick one up, move it
into the regular PR/issue flow. Sebastian is the owner unless noted otherwise.

Last updated: 2026-05-08 (post-PR-9.5 ship).

---

## Calibration after the next nightly

- [ ] **Tune `detect_text_overlay` thresholds against real Pulpo photos.** PR-151 shipped with `min_word_count=8` and `min_area_pct=5.0`. Once the next nightly populates `has_text_overlay` across the full catalog (`web/data/ranked.json`), look at:
  - How many listings get flagged true / false / null
  - Sample 20 flagged + 20 unflagged manually — what's the precision?
  - If precision < ~80%, raise `min_word_count` to 10–12 or `min_area_pct` to 7–8. Code lives in [automation/photo_quality.py](automation/photo_quality.py).
  - If recall is poor (real brochures missed), drop the area threshold or lower confidence.
  - Long-term: add a Phase-2 vision LLM pass for borderline cases (Tesseract ≥ 60% conf but flagged false).

---

## UX / FE polish

- [x] ~~**PlansPage hard-coded English.**~~ Shipped in PR-153 — every user-facing string flipped to `t()` calls with full EN/ES coverage; verified visually at 375×812 (ES) and 1280×800 (EN).
- [ ] **Account.jsx mock orders are hardcoded dates** ("5 May 2026" through "5 Jan 2026" in [account.jsx:325-331](web/app/account.jsx)). Will read as stale once today moves past them. Now lower priority since PR-9.5 ships the Stripe Customer Portal — the portal already shows the user their full invoice history, so the in-app table is now a "preview" of recent orders. Replace with a `n_months_ago(today, n)` helper or pull live data from Stripe.
- [x] ~~**Stripe checkout friction for anonymous users.**~~ Shipped in PR-153 — `pendingAction: "checkout"` field on `SignupModal` chains the flow automatically after auth completes (Clerk + legacy paths).
- [ ] **`ranked.json` is ~4 MB on every cold load.** Even with the 60-card pagination from PR-150 the JSON is fully parsed in memory. Worth splitting into pages server-side once the catalog grows past ~1500 listings.

## Telemetry

- [x] ~~Wire client-side `web-vitals` to PostHog.~~ **Already shipped.** Re-audited 2026-05-08: `web/app/telemetry/web-vitals.ts` boots `onCLS`/`onLCP`/`onINP`/`onTTFB`, called from [`app.jsx:121`](web/app/app.jsx). Events are typed in [`telemetry/events.ts`](web/app/telemetry/events.ts) (`web_vitals.lcp` / `inp` / `cls` / `ttfb`). Followup: build the actual PostHog insights/dashboards consuming these events — the data is flowing but no triage view exists yet.

## Pre-existing tech debt

- [ ] **Local pytest mismatch:** `tests/test_photos.py::test_hero_download_creates_jpeg` fails locally with `Wrong JPEG library version: library is 90, caller expects 80`. Pillow vs `libjpeg` mismatch in Sebastian's env. CI passes. `pip install --force-reinstall Pillow` should fix it.

## Untested caveats from PR-150 (Discover/Detail UX punch-list)

These shipped in [PR-150](https://github.com/javiersuarezOG/pulpo.club/pull/150) but were verified only in Chromium / dev. Worth a real-device spot check before relying on them:

- [ ] **Real Stripe end-to-end (Checkout + Customer Portal)** with a Stripe test card (4242 4242 4242 4242, any future date, any CVC). Steps:
  1. Sign in as a Free user on a Vercel preview with `STRIPE_SECRET_KEY` + Clerk wired.
  2. Click "Upgrade — $10/month" on the Plans page → redirect to `https://checkout.stripe.com/...` lands.
  3. Pay with the test card → return to `/preview/?upgrade=success` and the success toast fires.
  4. Watch the Clerk Dashboard: `publicMetadata.plan = "pro"` set by webhook; `privateMetadata.stripeCustomerId` set.
  5. Reload the app — UI reflects Pro tier (no upgrade prompts, full gallery, off-market unlocked).
  6. **PR-9.5:** navigate to `/account?section=subscription`. The "Manage plan →" button is live → click → redirected to `https://billing.stripe.com/p/session/...`.
  7. Update card / change plan / cancel in the portal → "Return to Pulpo" → land on `/preview/?account=subscription`. UI consistent.
  8. Cancel flow: click Upgrade again on a fresh test user, hit "back" / cancel during Checkout, verify the cancel toast.
  Wiring verified by [`tests/e2e/preview-smoke.spec.ts`](tests/e2e/preview-smoke.spec.ts) (mocked endpoints — both Checkout and Portal); the full roundtrip is the part that needs a Stripe test key + a human.
- [x] ~~ES locale visual~~ — verified in PR-153 via Playwright on the Plans page; remaining surfaces (Account, SignupModal, BottomNav) still untested visually.
- [ ] Real iPhone Safari + Android Chrome — only Chromium emulated viewports were tested.
- [ ] Tablet (768–1023px) — only mobile and desktop endpoints tested.

## PR-9.5 — Pro account-management UI (Stripe Customer Portal)

✅ **Shipped.** [`api/stripe/billing-portal.js`](api/stripe/billing-portal.js) + [`web/app/auth/stripe-portal.js`](web/app/auth/stripe-portal.js) wire the "Manage plan →" button to a Stripe Customer Portal session. Customer ID comes from `privateMetadata.stripeCustomerId` stamped by the existing webhook on `checkout.session.completed`. Return URL lands on `/preview/?account=subscription`.

**Stripe Dashboard prereq:** enable Customer Portal at Settings → Billing → Customer portal. The default config works; pick what users can do (update card / change plan / cancel) per product policy. The API call is config-agnostic.

**Pro account-management UI follow-ups:**
- [ ] **Replace mock order history** in [`account.jsx:325-331`](web/app/account.jsx) with live Stripe data. Lower priority now that the portal already shows the user their full invoice history.

## Other PR-9 gaps surfaced during the upgrade-flow audit

- [ ] **Detail-view soft prompt @ view 5 / hard gate @ view 8** — the counter exists in [`app.jsx:309`](web/app/app.jsx) but no UI enforces the prompts. Plan called for a "soft prompt at 5, hard gate at 8" funnel for free users.
- [ ] **Free-plan upgrade strips** — sticky banner ("Pulpo Free: 3 of 8 detail views this month") on Discover/Browse/Saved for logged-in-free users. Plan §985.
- [ ] **Save-cap inline card at save 10** — currently a toast; plan called for an inline upgrade card in the Saved page when the cap hits.
- [ ] **Redacted `/api/listings/:id`** — confirm the endpoint actually omits broker fields for unauth requests (the CSS blur is visual only per plan §506; the truth is server-side).
- [x] ~~**`/api/saves` returns 500 in dev despite a valid Clerk session.**~~ Fixed in PR-9.5 ([`api/_clerk.js`](api/_clerk.js)) — `@clerk/backend` v3 expects a Web Fetch `Request`, not a Vercel Node `IncomingMessage`. Added a `toWebRequest(req)` helper that translates and is now the single auth path used by `/api/saves`, `/api/stripe/create-checkout-session`, and `/api/stripe/billing-portal`.

## Map (deferred from PR-150)

- [ ] **Real interactive map for listing detail.** PR-150 hid the fake `.static-map` illustration. To bring back a real map: expose `lat` + `lng` on the FE `Listing` type ([web/app/data/types.ts](web/app/data/types.ts)) and adapter ([web/app/data/listings.ts](web/app/data/listings.ts)), the data is already in [pulpo/normalize.py:618](pulpo/normalize.py). Ship Leaflet + OSM tiles (free, no API key). Lazy-load to keep the bundle lean on first paint.
