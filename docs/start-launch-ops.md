# `/start` launch — ops checklist (Stripe / Clerk / Vercel)

Every operational change Sebastian needs to make outside the codebase to
accompany the `/start` rollout. Pair this with the engineering plan at
`~/.claude/plans/prd-pulpo-start-pure-whistle.md`.

## Stripe Dashboard

### Multi-currency on the Pulpo Pro Price (required for PR-A)

The Checkout Session created by `api/stripe/start-checkout.js` passes a
`currency` parameter picked from the visitor's geo. v1 supports two
currencies: **EUR** (EU diaspora) and **USD** (everywhere else, including
El Salvador's legal tender). Every other geo falls back to USD.

1. Stripe Dashboard → **Products → Pulpo Pro → Pulpo Pro Price**.
2. Click "Add a price by currency". Add:
   - `USD` — $9.99 (round marketing price — *do not* let Stripe pre-fill an FX-converted value like $11.83)
3. `EUR` stays as the base — €9.99.
4. **Do NOT** enable Adaptive Pricing. It conflicts with explicit
   `currency_options`. If Stripe surfaces an "Adaptive Pricing is on"
   banner, switch it off.
5. The Price ID stays the same (`STRIPE_PRICE_ID_PRO` in Vercel env vars
   does not change).

Verify by clicking "Preview" on the Price — Stripe should show a
currency-selector with EUR + USD.

**Adding MXN / ARS later** (when the regional channels start producing
traffic in PostHog): add the row to the Stripe Price *and* add the matching
country → currency line in `api/stripe/_geo.js` AND in
`web/app/lib/pricing.ts` (both files hold parallel maps — see the
header comment in pricing.ts for the full recipe). The geo map only
returns currencies that exist on the Stripe Price — adding to one
without the others 500s the checkout for that geo.

### Price-rotation playbook (changing the displayed amount)

To change the Pulpo Pro displayed price (e.g. running a price
experiment):

1. **Code**: edit `web/app/lib/pricing.ts` — update `amount` and
   `displayString` for each currency in the `PRICES` map. That single
   file drives every paid-CTA surface (hero microcopy, USP band,
   /start, FreeMonthModal, UspPopup, /plans).
2. **Stripe**: in the Dashboard → **Products → Pulpo Pro → "Add another
   price"**, create a new monthly recurring Price with `currency_options`
   for both EUR and USD at the new amount. Same `recurring.interval =
   month`, same `tax_code = txcd_10103100`. Stripe blocks editing
   `unit_amount` on a Price that has been used in any Checkout — that's
   why we add a new Price instead of editing the existing one.
3. **Archive the old Price** (Dashboard → old Price → "Archive"). Any
   existing subscriptions stay attached to the archived Price unless you
   explicitly migrate them via a Subscription Schedule — separate
   decision, separate playbook.
4. **Rotate `STRIPE_PRICE_ID_PRO`** in Vercel (production scope — the
   only scope we use) with the new `price_…` ID. Redeploy.
5. **Verify on the Vercel preview** per `CLAUDE.md`'s live-preview
   verification mandate before merging the code PR. The Checkout
   summary screen must show the new amount and, if testing a promo,
   the coupon must still resolve ("3 months free → then €X.XX/mo").
6. **Coupons keep working untouched.** Self-applied promo codes
   (REDDIT01, AMIGOS, IG01, WHATSAPP01, TEST, …) attach to the **Coupon**
   object, not to a Price. Swapping the underlying Price changes
   nothing about how they resolve — Stripe applies the same discount
   to whatever line item the Checkout Session has.

### "3 months free" coupon + promo codes (required for PR-A)

The /start page supports promo codes via URL (`?code=REDDIT01`) or
user-entered. Every code resolves to the same coupon — "3 months free,
100% off, repeating, 3 months". After month 4 the subscription charges
the full price, so Stripe still collects a card at checkout (correct
behaviour).

1. Stripe Dashboard → **Product catalogue → Coupons → New coupon**.
2. Settings:
   - Name: `3 months free`
   - Type: Percent off
   - Percent off: `100`
   - Duration: `Repeating`
   - Number of months: `3`
3. Save the coupon. Note the coupon ID (`coupon_…`) — you don't need it
   in code, the promo codes resolve internally.
4. Attach promo codes:
   - **Live mode**: `REDDIT01`, `AMIGOS`, `IG01`, `WHATSAPP01`, etc.
     (founder owns the naming — one per campaign).
   - **Test mode**: `TEST` (already exists per Sebastian).
   Each promo code: New → enter the code text → attach to the "3 months
   free" coupon → leave "Limit redemptions" + "First-time only" off
   unless the campaign needs them.

### Webhook endpoint (already configured)

Confirm `https://pulpo.club/api/stripe/webhook` is registered in:

- Stripe Dashboard → **Developers → Webhooks**.
- Subscribed events include: `checkout.session.completed`,
  `customer.subscription.updated`, `customer.subscription.deleted`.
- The signing secret is in Vercel env vars as `STRIPE_WEBHOOK_SECRET`.

If you rotate the signing secret in Stripe, also update the Vercel env
var or every event will fail signature verification.

### Promo codes live alongside the Stripe keys

Promo codes and the "3 months free" coupon live in whichever Stripe
workspace is referenced by `STRIPE_SECRET_KEY` + `STRIPE_PRICE_ID_PRO`
in Vercel. If you rotate those keys to a different Stripe environment,
the promo codes from the old environment won't resolve — re-create
them in the new workspace and re-attach to the "3 months free"
coupon there.

When triaging a "no code found" report, check the Vercel function log
for the `key_prefix=` token emitted by `start-checkout.js:113` — that
identifies which Stripe key the function actually loaded, which is
the fastest way to confirm a wrong/stale key is in play.

## Clerk Dashboard

### Invitation email enabled (required for PR-A)

The webhook creates a Clerk invitation when an anonymous /start payment
lands with an unrecognized email. The user must receive that invitation
email to set up their account.

1. Clerk Dashboard → **Customizations → Email Templates → Invitation**.
2. Confirm the template is enabled (toggle on).
3. Customize:
   - **Subject**: "Welcome to Pulpo — set up your account"
   - **From name**: `Pulpo`
   - **From email**: a verified Clerk-routed address (the default works;
     a custom domain like `hello@pulpo.club` is a separate Clerk setup).
   - **Body**: include a line referencing the property-marketplace value
     prop ("Your Pulpo Pro subscription is active — set your password to
     start browsing") and the inviting CTA button.
4. Send a test invitation to your own email to verify deliverability +
   tone.

### Invitation email template — Pulpo-branded magic-link copy (PR-B.4b)

The post-PR-B.4b flow lands users on `/account?welcome=1` after Stripe.
A modal there tells them to "check your inbox" for a magic-link sign-in.
The Clerk template needs to feel like Pulpo, not Clerk-dev. Sebastian to
apply in **Clerk Dashboard → Customizations → Email Templates → Invitation**:

**Brand assets to set first** in `Customizations → Branding`:

- **Logo:** upload `assets/logo_mark_only.svg` from the repo root (deep-green octopus mark — same file as the favicon). Or download from `https://pulpo.club/assets/logo_mark_only.svg`.
- **Application name:** `Pulpo`.
- **Primary colour:** the `--accent-strong` token from `web/app/styles/tokens.css`
  is `oklch(0.28 0.08 165)`. Clerk's colour picker expects hex; convert to
  the closest sRGB equivalent (`#1a3d33` is a safe approximation — verify in
  the Clerk preview that the button reads as the same deep green as the
  in-app primary button).
- **Background colour:** `--paper` token (oklch(1 0 0) — white, `#ffffff`).
- **Font:** Clerk supports a curated font list. Pick **Inter** if present
  (matches Pulpo's UI font); otherwise pick the closest neo-grotesque.

**Template content:**

- **Subject:** `Welcome to Pulpo Pro — sign in here`
- **From name:** `Pulpo`
- **Body** (Markdown / Clerk template syntax):

  ```
  {{> app_logo}}

  ## Welcome to Pulpo Pro

  Your subscription is active. Tap below to sign in and start
  browsing.

  [Sign in to my account →]({{action_url}})

  This link expires in 24 hours. If the button doesn't work,
  paste this URL into your browser:
  {{action_url}}

  © {{current_year}} Pulpo
  ```

- **CTA button text:** `Sign in to my account →`

Pulpo voice is declarative + trim. We do NOT recap the USPs in the
email — the user just paid, they know what they bought. The CTA goes
to `{{action_url}}` which our `createInvitation` call sets to
`${origin}/account?welcome=1` so the user lands back on the same
modal (now in its `signed_in` variant) after Clerk's sign-in flow.

**Known limitation:** the customized template assumes every invitation
is post-payment (the current state — `clerk.invitations.createInvitation`
is only called from the Stripe webhook). If a future Pulpo flow needs
neutral invitation copy (team invites, beta access), Sebastian will need
to either (a) accept the Pro-flavoured copy as a temporary mismatch, (b)
build a "Delivered via emails webhook" custom-SMTP path that lets us
template per-flow, or (c) wait for Clerk to add per-flow template overrides.

### Magic-link-only authentication

PR-B.4b assumes a single auth path: the Clerk invitation magic-link.
Sebastian to disable password / Google / Apple in **Clerk Dashboard →
User & Authentication → Email, Phone, Username → Authentication
strategies**. Keep only `Email address` with `Email link` as the
sign-in method.

Why: one path means one surface to brand, one funnel to instrument,
and fewer support tickets per acquired user. Once the funnel is
proven, SSO can be re-enabled as a follow-up.

### Google SSO enabled (recommended for PR-A)

When the user clicks the invitation link, Clerk's hosted sign-up page is
served. If Google SSO is enabled there, the user can complete sign-up
with one click instead of typing a password.

1. Clerk Dashboard → **User & Authentication → Social Connections**.
2. Enable **Google**.
3. Provide a Google OAuth Client ID + Secret (or use Clerk's shared
   dev credentials for the test instance).
4. No code change required — Clerk's hosted sign-up page picks the
   provider up automatically.

### Backend SDK env vars (already configured)

Confirm both are set in Vercel:

- `CLERK_SECRET_KEY` (`sk_test_…` or `sk_live_…`)
- `CLERK_PUBLISHABLE_KEY` or `VITE_CLERK_PUBLISHABLE_KEY` (either; the
  backend falls back to the Vite-prefixed one if the explicit server var
  is missing — see `api/_clerk.js:40-46`).

## Vercel

### Env vars

PR-A introduced no env vars. **PR-B.3 added server-side PostHog telemetry** for the webhook + public checkout endpoint, reusing the env vars the Python nightly pipeline already uses:

- `POSTHOG_PROJECT_TOKEN` — same project token the pipeline + frontend use. The webhook silently no-ops when missing, so this is a soft requirement (telemetry just won't flow until set).
- `POSTHOG_HOST` — optional, defaults to `https://eu.i.posthog.com`.

Plus all the existing endpoint reads:

- `STRIPE_SECRET_KEY` (existing)
- `STRIPE_PRICE_ID_PRO` (existing)
- `STRIPE_WEBHOOK_SECRET` (existing — used by webhook only)
- `CLERK_SECRET_KEY` (existing)
- `CLERK_PUBLISHABLE_KEY` / `VITE_CLERK_PUBLISHABLE_KEY` (existing)

### Rewrites

PR-A adds no rewrites to `vercel.json`. PR-B adds two for the public
pages:

```json
{ "source": "/start",   "destination": "/web/dist/index.html" },
{ "source": "/welcome", "destination": "/web/dist/index.html" }
```

(Land that when the frontend page is ready.)

### Edge geo header

The Checkout flow reads `x-vercel-ip-country` to pick the presentment
currency. Vercel attaches this header on every Edge / Node function
request automatically — no configuration needed. On local dev without
the header, the endpoint defaults to USD.

## Smoke tests Sebastian can run after PR-A merges

After PR-A is merged + deployed (no UI yet — these are direct API checks):

```bash
# Valid email, no promo code — expects { url: "https://checkout.stripe.com/..." }
curl -X POST https://pulpo.club/api/stripe/start-checkout \
  -H 'content-type: application/json' \
  -d '{"email":"smoke+a@pulpo.club"}'

# Valid email, TEST promo code (test-mode)
curl -X POST https://pulpo.club/api/stripe/start-checkout \
  -H 'content-type: application/json' \
  -d '{"email":"smoke+b@pulpo.club","promoCode":"TEST"}'

# Invalid promo code — expects { error: "invalid_promo_code" } 400
curl -X POST https://pulpo.club/api/stripe/start-checkout \
  -H 'content-type: application/json' \
  -d '{"email":"smoke+c@pulpo.club","promoCode":"NOTACODE"}'

# Bad email — expects { error: "invalid_email" } 400
curl -X POST https://pulpo.club/api/stripe/start-checkout \
  -H 'content-type: application/json' \
  -d '{"email":"not-an-email"}'

# Geo currency lookup — expects { country: "XX", currency: "usd|eur|mxn|ars" }
curl https://pulpo.club/api/geo
```

For the end-to-end webhook smoke (anonymous flow creates a Clerk
invitation), open one of the URLs from the curl response in a browser,
complete the Stripe-hosted checkout with `4242 4242 4242 4242`, and check
the Clerk dashboard → Invitations for a new pending invitation with
`publicMetadata.plan = "pro"`.

## What happens if I forget a step

| Skipped step | Symptom |
|---|---|
| Multi-currency `currency_options` on the Price | `/api/stripe/start-checkout` returns 500 with `stripe_error: currency_options not configured for currency mxn` (or whichever currency the visitor's geo resolved to). |
| "3 months free" coupon not created | The `TEST` (or any) promo code resolves but no discount is applied — the user sees full price at Stripe. |
| Promo codes not attached to coupon | `/api/stripe/start-checkout` returns 400 with `invalid_promo_code` for every code attempt. |
| Clerk invitation template disabled | User pays successfully, no invitation email arrives. Webhook log shows `path=anonymous_invitation_created` but the user is locked out. **Mitigation**: invitation can be re-sent manually from Clerk Dashboard → Invitations → Resend. |
| Google SSO not enabled | Invitation flow only offers email+password. Not a blocker; users can still complete via password. |
| `STRIPE_WEBHOOK_SECRET` not in Vercel env | Every webhook delivery 400s with `Webhook secret not configured`. Payments succeed at Stripe but plan never flips to pro. |
