# Monthly Integration Drill

last_drill_date: 2026-06-03
next_drill_due: 2026-07-03
owner: Sebastian

References:
- `CLAUDE.md` — "NEVER ship a broken auth/billing flow again"
- `bug-postmortem-stripe-modal-loop.md`
- `bug-postmortem-csp-blocks-clerk-turnstile.md`

## Goal

Walk the full paid-user loop once per month with real third-party surfaces:
Stripe Checkout, Resend activation email, Clerk invitation/password setup,
Stripe Customer Portal cancellation, Stripe-sent cancellation email, and
PostHog telemetry.

Use a fresh incognito window and a brand-new `+`-aliased Gmail address that
has never been used in Clerk or Stripe.

## Checklist

1. Start in Spanish.
   - Open the Vercel preview or production URL in incognito.
   - Set locale to `es`.
   - Navigate to `/start?code=PULPOFREEMONTH`.
   - Screenshot slot: start page in Spanish.

2. Complete Stripe Checkout in Spanish.
   - Click the primary CTA.
   - Confirm Stripe Checkout chrome, buttons, and cancellation copy are Spanish.
   - Use the sandbox card for previews or the agreed live-drill path for production.
   - Confirm the discount line is visible when `PULPOFREEMONTH` is present.
   - Screenshot slot: Stripe Checkout Spanish surface.

3. Confirm activation email delivery and Resend telemetry.
   - Confirm the activation email lands in Inbox, not Spam/Promotions when possible.
   - Confirm subject/body are Spanish.
   - In PostHog, confirm Resend lifecycle telemetry includes `email_type=activation`
     and non-null `recipient_hash`.
   - Screenshot slot: email inbox and PostHog event.

4. Set password through Clerk invitation.
   - Click the activation email.
   - Confirm Clerk SignUp modal renders in Spanish.
   - Confirm Turnstile/CAPTCHA renders without CSP console violations.
   - Set a password and land signed in on `/account?welcome=1`.
   - Screenshot slot: Clerk modal + signed-in account.

5. Open Customer Portal in Spanish.
   - Navigate to `/account/subscription`.
   - Click `Gestionar plan`.
   - Confirm Stripe Customer Portal is Spanish.
   - Confirm Stripe Customer `preferred_locales` is stamped with `es`.
   - Screenshot slot: Customer Portal Spanish surface.

6. Cancel subscription and verify Pulpo state.
   - Cancel in Stripe Portal.
   - Click return to Pulpo.
   - Confirm `/account/subscription?from=portal` strips the query param.
   - Confirm `Actualizando tu plan...` appears briefly if the metadata refresh is still pending.
   - Confirm display state is `canceling`: copy says `Se cancela el {date}`,
     pill says `Cancelando`, and no "Se renueva" copy appears.
   - Screenshot slot: Pulpo canceling state.

7. Verify emails and telemetry close the loop.
   - Confirm Stripe cancellation email is Spanish.
   - Confirm PostHog sequence:
     `portal.opened` -> `account.sub_portal_clicked` ->
     `stripe.billing_portal_session_created` -> `account.sub_portal_return` ->
     `account.sub_portal_return_state_changed` or a justified stale event.
   - Confirm `account.sub_block_rendered { display: "canceling" }`.
   - Screenshot slot: PostHog event sequence.

## Completion

After the drill:
- Update `last_drill_date` and `next_drill_due` above.
- Paste screenshot links or attach images to the GitHub issue.
- Record any failed step as a follow-up issue before closing the drill issue.
