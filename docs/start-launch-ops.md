# `/start` launch — ops checklist (Stripe / Clerk / Vercel)

Every operational change Sebastian needs to make outside the codebase to
accompany the `/start` rollout. Pair this with the engineering plan at
`~/.claude/plans/prd-pulpo-start-pure-whistle.md`.

## Stripe Dashboard

### Multi-currency on the Pulpo Pro Price (required for PR-A)

The Checkout Session created by `api/stripe/start-checkout.js` passes a
`currency` parameter picked from the visitor's geo (USD / EUR / MXN / ARS).
For Stripe to accept that, the Price object must list every currency in
its `currency_options`.

1. Stripe Dashboard → **Products → Pulpo Pro → Pulpo Pro Price**.
2. Click "Add another currency" three times. Set:
   - `USD` — $10.00
   - `MXN` — MX$199 (psychological round price, not FX-derived from EUR)
   - `ARS` — AR$12,900 (likewise — adjust as inflation moves)
3. `EUR` stays as the base — €10.00.
4. **Do NOT** enable Adaptive Pricing. It conflicts with explicit
   `currency_options`. If Stripe surfaces an "Adaptive Pricing is on"
   banner, switch it off.
5. The Price ID stays the same (`STRIPE_PRICE_ID_PRO` in Vercel env vars
   does not change).

Verify by clicking "Preview" on the Price — Stripe should show a
currency-selector with all four codes listed.

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

### Test-mode vs live-mode keys (operational note)

Test-mode promo codes (`TEST`) and live-mode promo codes (`REDDIT01`) live
in **separate ledgers**. After flipping to live keys in Vercel:

- Re-create every promo code in live mode (test-mode codes won't resolve).
- Re-attach them to the live-mode "3 months free" coupon.
- `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID_PRO` in Vercel env must both
  switch in lockstep — test price IDs won't resolve against live keys
  and vice versa.

When triaging a "no code found" report, check the Vercel function log for
the `key_prefix=sk_test_` vs `key_prefix=sk_live_` token emitted by
`start-checkout.js:113` — that's the fastest way to confirm a test/live
mismatch.

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

No new env vars introduced by PR-A. The endpoint reads:

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
