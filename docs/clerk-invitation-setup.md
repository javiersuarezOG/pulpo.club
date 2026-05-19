# Clerk invitation email — setup checklist

> **Owner**: Sebas (Clerk Dashboard + DNS access required — neither is
> in this repo).
> **Status**: Open. The three items below are the load-bearing
> deliverability fix for the post-Stripe activation flow. Without
> them, paying users who hit the `anonymous_invitation_created`
> webhook path still get emails sent from Clerk's default
> `accounts.clerk.dev` sender → spam folder → "no email arrived"
> bug report.
> **Tracking**: PR #3 of the post-Stripe activation series. PRs #1
> (#314) and #2 (#317) closed the client-side bugs (gate-bypass
> race, lying modal copy). This doc closes the email side.

## Context — why this exists

Pulpo's post-Stripe activation flow goes:

```
Stripe success_url
  → /account?welcome=1
  → Stripe webhook fires
  → clerk.invitations.createInvitation()
  → Clerk sends activation email
  → user clicks
  → Clerk hosted sign-up
  → /account (signed in, plan=pro)
```

The Pulpo-side code is now correct ([api/stripe/webhook.js](../api/stripe/webhook.js),
[web/app/pages.jsx WelcomeModal](../web/app/pages.jsx)). The
remaining failure mode is the email itself:

- **Copy mismatch.** Clerk's default invitation template doesn't
  reference Pulpo Pro or the just-completed Stripe payment.
  Item A below replaces it with Pulpo-branded EN + ES variants.
- **Sender reputation.** Clerk's default sender domain
  (`accounts.clerk.dev` or similar) has no relationship with
  `pulpo.club`, so receiving providers (Gmail, Outlook,
  Proton, etc.) flag the mail as spam or "promotional." Item B
  configures `mail.pulpo.club` as a custom sender with
  SPF/DKIM/DMARC, raising deliverability dramatically.
- **Wrong Clerk instance.** A screen-share early in this bug's
  triage showed a "Clerk test mode" overlay on the live app —
  suggesting production is talking to Clerk's dev instance.
  Item C is a 30-second verification + fix.

## Item A — Customize the invitation email template

**Where**: Clerk Dashboard → your production app → **Customization**
→ **Emails** → **Invitation** → **Localizations**.

The Pulpo-side code already passes the user's locale to
`clerk.invitations.createInvitation({ locale })` (see
[api/stripe/webhook.js](../api/stripe/webhook.js)'s
`clerkLocaleFromStripe()` and [api/clerk/resend-invitation.js](../api/clerk/resend-invitation.js)).
Clerk auto-selects the matching localization based on this field,
so adding the ES variant under Localizations works without further
code.

### English variant

- **From name**: `Pulpo Club`
- **Subject**: `Your Pulpo Pro subscription is active — set up your account`
- **Preheader** (preview snippet): `One step left: set your password and start exploring.`
- **Body** (HTML — Clerk's editor supports `<p>`, `<a>`, basic markup; substitute the Clerk-provided action URL variable for `{{action_url}}`):

```html
<p>Hi there,</p>

<p>Thanks for joining Pulpo Pro — your subscription is active.</p>

<p>One step left to access your account: set a password so you can
sign in from any device.</p>

<p style="margin: 24px 0;">
  <a href="{{action_url}}"
     style="background:#1a1a1a;color:#ffffff;padding:12px 20px;
            border-radius:8px;text-decoration:none;font-weight:600;
            display:inline-block;">
    Set up my Pulpo Pro account →
  </a>
</p>

<p>This link is unique to your account and expires in 24 hours.
If it expires, request a new one from the activation modal on
<a href="https://pulpo.club/account">pulpo.club/account</a>.</p>

<p>Questions? Reply to this email or write to
<a href="mailto:hello@pulpo.club">hello@pulpo.club</a>.</p>

<p>— The Pulpo Club team</p>
```

- **Plain-text fallback** (Clerk auto-generates if not provided,
  but ensure the action URL is on its own line for older clients):

```
Hi there,

Thanks for joining Pulpo Pro — your subscription is active.

One step left to access your account: set a password so you can
sign in from any device.

Set up my Pulpo Pro account:
{{action_url}}

This link is unique to your account and expires in 24 hours.

Questions? Reply to this email or write to hello@pulpo.club.

— The Pulpo Club team
```

### Spanish variant (add under "Localizations" → `es`)

- **From name**: `Pulpo Club`
- **Subject**: `Tu suscripción de Pulpo Pro está activa — configura tu cuenta`
- **Preheader**: `Solo falta un paso: elige tu contraseña y empieza a explorar.`
- **Body** (HTML — same structure as EN, swap the copy):

```html
<p>Hola,</p>

<p>Gracias por sumarte a Pulpo Pro — tu suscripción está activa.</p>

<p>Solo queda un paso para acceder a tu cuenta: elige una
contraseña para iniciar sesión desde cualquier dispositivo.</p>

<p style="margin: 24px 0;">
  <a href="{{action_url}}"
     style="background:#1a1a1a;color:#ffffff;padding:12px 20px;
            border-radius:8px;text-decoration:none;font-weight:600;
            display:inline-block;">
    Configurar mi cuenta Pulpo Pro →
  </a>
</p>

<p>Este enlace es único para tu cuenta y expira en 24 horas. Si
expira, solicita uno nuevo desde la ventana de activación en
<a href="https://pulpo.club/account">pulpo.club/account</a>.</p>

<p>¿Dudas? Responde a este correo o escribe a
<a href="mailto:hello@pulpo.club">hello@pulpo.club</a>.</p>

<p>— El equipo de Pulpo Club</p>
```

- **Plain-text fallback**:

```
Hola,

Gracias por sumarte a Pulpo Pro — tu suscripción está activa.

Solo queda un paso para acceder a tu cuenta: elige una contraseña
para iniciar sesión desde cualquier dispositivo.

Configurar mi cuenta Pulpo Pro:
{{action_url}}

Este enlace es único para tu cuenta y expira en 24 horas.

¿Dudas? Responde a este correo o escribe a hello@pulpo.club.

— El equipo de Pulpo Club
```

### After saving — verify

1. In the same dashboard, click **"Send test email"** and target
   a **brand-new external email address** (never used with Pulpo).
2. Check that the **inbox** receives it (not spam, not promotions).
   If it's still in spam, Item B (custom domain) hasn't been
   applied yet — that fix is what moves deliverability.
3. Confirm the EN and ES variants render correctly by sending one
   test of each.

## Item B — Custom sending domain (SPF + DKIM + DMARC)

**Where**: Clerk Dashboard → **Customization** → **Emails** →
**Email domain**.

This is the single biggest deliverability lever. Without it,
Clerk's emails come from `accounts.clerk.dev` (no relationship
with `pulpo.club`), which receivers heavily filter. Configuring
a custom domain lets Clerk send as `noreply@mail.pulpo.club`
(or similar), authenticated by Pulpo's DNS records.

### Setup steps

1. **Pick the sending subdomain**. Recommended: `mail.pulpo.club`.
   Don't use the apex `pulpo.club` directly — DKIM keys live on
   a subdomain by convention, and a future operational separation
   (transactional vs marketing email) is cleaner if the
   transactional sender already lives under its own subdomain.
2. **Click "Add domain"** in the Clerk Dashboard. Clerk will
   surface 3 DNS records you need to add. Copy them verbatim —
   the exact values are project-specific (DKIM selector key, etc.).
3. **Add the DNS records** at Pulpo's domain registrar. Typical
   shape (Clerk will surface the exact records — these are
   illustrative):

   | Type | Name (host) | Value | Notes |
   |---|---|---|---|
   | TXT | `mail.pulpo.club` | `v=spf1 include:clerk-mail.com ~all` | SPF — authorizes Clerk to send as `mail.pulpo.club` |
   | TXT | `clerk._domainkey.mail.pulpo.club` | `v=DKIM1; k=rsa; p=…` (long key Clerk provides) | DKIM — cryptographically signs outgoing mail |
   | CNAME | `mail.pulpo.club` | `mail.clerk-mail.com` | Routes Clerk's bounce/reply traffic |

   The exact selector (`clerk`) and the SPF include host
   (`clerk-mail.com`) depend on Clerk's email provider —
   the Dashboard surfaces the precise values.

4. **Also add a DMARC policy at the apex `_dmarc.pulpo.club`**
   (this is separate from Clerk's surfaced records — DMARC is
   Pulpo's policy decision, not Clerk's, but it's the third
   piece needed for major receivers to trust the chain):

   | Type | Name | Value | Notes |
   |---|---|---|---|
   | TXT | `_dmarc.pulpo.club` | `v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@pulpo.club; aspf=s; adkim=s; pct=100` | Quarantine any mail that fails SPF + DKIM; report failures |

   Start with `p=quarantine` (failed mail goes to spam, but
   isn't rejected). After 1-2 weeks of clean DMARC reports,
   tighten to `p=reject`. Don't start at `p=reject` — a typo
   in the SPF record would silently drop all legitimate mail.

5. **Click "Verify"** in the Clerk Dashboard. Each record gets
   a green check when Clerk's verifier sees the DNS update
   propagate (typically 5-15 min, sometimes up to 1 hour).
   Until all three are green, Clerk keeps sending from its
   default sender — no rollback risk.

6. **Test deliverability**. Repeat Item A's "Send test email"
   step with a brand-new external email AFTER all DNS records
   verify. The test mail should now arrive **in the inbox**,
   with the sender showing as `Pulpo Club <noreply@mail.pulpo.club>`
   (or whatever sub-address Clerk uses).

### If deliverability is still bad after B

Some receivers (especially Apple's iCloud and corporate Outlook
365 tenants) take 1-2 weeks of clean sending history to lift
their "new sender" reputation cap. If the spam rate stays high
after a week, fall back to **PR #3.5** (deferred from the
original plan, not yet scoped):

- Switch Clerk's invitation email to "send via webhook" mode
- Stand up a small serverless endpoint that receives Clerk's
  webhook + posts to Pulpo's existing Resend account
  ([api/newsletter.js:27](../api/newsletter.js#L27) already
  uses Resend; no new dep needed)
- Resend's `@pulpo.club` domain has built-up reputation from
  newsletter sending — emails go straight to inbox.

That's a larger change because it puts new code on the sign-up
critical path. Try Item B first; if A + B suffice, PR #3.5
stays deferred.

## Item C — Verify production Clerk is on `pk_live_*`

**Where**: A live browser session on `https://pulpo.club` +
Clerk Dashboard environment switcher.

### 30-second verification

1. Open `https://pulpo.club` in a normal (non-incognito) browser.
2. Open DevTools → **Network** tab → filter for `clerk`.
3. Refresh the page. The Clerk SDK boot calls show up — pick one
   (e.g. `accounts.pulpo.club/v1/client` or similar).
4. Look at the request payload or response — Clerk's publishable
   key is in the request headers / params / page source. It will
   start with either `pk_live_…` (production) or `pk_test_…`
   (dev/test instance).

### What "wrong" looks like

If the live app is using `pk_test_*`:

- Clerk's UI shows a small "Development instance" banner
- Clerk's API has different rate limits + email behavior
- Test-mode emails sometimes show a `[TEST]` prefix and are
  routed differently
- The invitation flow may behave differently from prod

### Fix

1. Vercel → pulpo-club project → **Settings** → **Environment
   Variables**.
2. Verify `VITE_CLERK_PUBLISHABLE_KEY` (Production scope) starts
   with `pk_live_…`. If it starts with `pk_test_…`, replace it
   with the prod key from Clerk Dashboard → **API Keys**
   (under the production instance, not the dev one).
3. Verify `CLERK_SECRET_KEY` (Production scope) is also from the
   production instance (`sk_live_…` not `sk_test_…`).
4. Trigger a new deploy (push any commit to main, or click
   "Redeploy" in Vercel).

### After verifying

Walk a Stripe-sandbox checkout on the live site with a
brand-new email and confirm the invitation email arrives in the
inbox of that brand-new address with the Pulpo-branded copy from
Item A. That single test exercises items A + B + C together — if
it works, the post-Stripe loop is closed end-to-end.

## What "done" looks like

All three items complete + this checklist verified:

- [ ] Item A — EN + ES invitation templates saved + test emails
  arrive with the correct copy
- [ ] Item B — `mail.pulpo.club` verified green in Clerk
  Dashboard; DMARC record live at `_dmarc.pulpo.club` with
  `p=quarantine`
- [ ] Item C — `pk_live_*` confirmed on the live app
- [ ] End-to-end test — Stripe-sandbox checkout with a brand-new
  email lands in inbox + completes the full activation loop

## 2026-05-19 update — current DNS state + the actual ask for Javier

**Read-only `dig` audit on 2026-05-19** revealed the deliverability
infrastructure is in a worst-case configuration, not a missing one:

| Record | State | Implication |
|---|---|---|
| `pulpo.club` TXT (SPF) | **None** | No sender authorization for any third-party. |
| `mail.pulpo.club` | **Doesn't exist** | The sending subdomain Item B specifies isn't set up. |
| `_dmarc.pulpo.club` TXT | `v=DMARC1; p=quarantine; aspf=r; adkim=r; rua=mailto:dmarc_rua@onsecureserver.net` | **Actively hostile.** `p=quarantine` with no protective SPF + DKIM alignment means Gmail/Outlook quarantine any mail claiming to be from `pulpo.club`. The `rua=` reports go to the GoDaddy registrar default mailbox (not a Pulpo-owned address). |
| Nameservers | `ns27.domaincontrol.com`, `ns28.domaincontrol.com` (GoDaddy) | DNS is at GoDaddy; Sebas has direct access. |
| Resend SPF (`send.resend.com` TXT) | `v=spf1 include:amazonses.com ~all` | Resend sends via AWS SES under the hood. Any SPF record needs `include:_spf.resend.com` (Resend will surface the exact include in their Dashboard when a sending domain is added). |

**Ownership realities clarified:**
- **Sebas can:** publish DNS records at GoDaddy directly, create the Clerk webhook endpoint, set Vercel env vars.
- **Javier owns:** Resend Dashboard login + the "Add sending domain" step inside Resend (which is what surfaces the exact records to publish), Clerk plan/billing decisions.

### The pre-written paste-to-Javier ask

```
Hey — post-Stripe activation email isn't arriving for paying users.
Clerk creates the invitation row correctly (audit log confirms it),
but no email lands anywhere (inbox / spam / promotions).

I just shipped /api/clerk/webhook so we get server-side telemetry
on whether Clerk is even attempting the send (clerk.email_attempted
in PostHog). Independent of what that tells us, two things only
you can do:

1. Resend Dashboard → Domains: is pulpo.club or mail.pulpo.club
   already verified there? If yes, paste me the verified domain
   name and I'll route Clerk through it. If no, please add
   mail.pulpo.club and paste me the 4 DNS records Resend surfaces
   (1 SPF TXT + 3 DKIM CNAMEs). I have GoDaddy DNS access so
   once you give me the records I publish them myself, no further
   work for you.

2. Clerk plan check: Dashboard → Settings/Billing — what Clerk
   tier are we on? And is the "Custom email provider" option
   visible (typically under Customization → Emails → Provider or
   User & Authentication → Advanced)? Some Clerk features gate
   behind paid tiers. If it's not visible at our current tier,
   tell me and we'll send activation emails ourselves via our
   existing Resend integration (a ~1-day PR on my side, but
   it's the durable fix).

3. (Optional) _dmarc.pulpo.club currently routes failure reports
   to dmarc_rua@onsecureserver.net (registrar default). Mind if
   I re-point that to a Pulpo-owned mailbox so we get visibility
   into bounces?

Anything you can knock out in the next day or two?
```

### After Javier responds with the Resend records

Once Javier pastes the records, Sebas:

1. Logs into GoDaddy → DNS Management → pulpo.club.
2. Adds the records exactly as Resend surfaced them. Typically:
   - `mail.pulpo.club TXT v=spf1 include:_spf.resend.com ~all`
   - `resend._domainkey.mail.pulpo.club CNAME resend._domainkey.<resend-region>.amazonses.com` (and 2 more CNAMEs)
3. Wait for propagation: `dig +short TXT mail.pulpo.club` should return the SPF; `dig +short CNAME resend._domainkey.mail.pulpo.club` should return Resend's chain. Typically 5-30 min on GoDaddy.
4. Confirm Resend Dashboard marks the domain "Verified."
5. Move to either Item B (configure Clerk to use Resend as custom email provider) or PR #3.5 fallback (Pulpo sends activation emails directly).

### Independent of Javier — what just shipped that helps debug

PR (this one) ships `/api/clerk/webhook` plus extends
`/api/admin/stripe-session-debug` with PostHog hints. After Sebas:

1. Goes to Clerk Dashboard → Webhooks → Add Endpoint
   - URL: `https://pulpo.club/api/clerk/webhook`
   - Subscribe to: `email.created`, `invitation.created`,
     `invitation.accepted`, `invitation.revoked`, `user.created`
   - Copy the signing secret.
2. Sets `CLERK_WEBHOOK_SECRET` in Vercel (all envs).
3. Triggers a fresh Stripe-sandbox checkout.

PostHog will then show, for the test session's email_hash:
- `webhook.received` (Stripe webhook hit our server)
- `webhook.checkout_completed[path=anonymous_invitation_created]`
- `clerk.invitation_created` (Clerk's own confirmation)
- `clerk.email_attempted[delivered_by_clerk=<true|false>]` **← the diagnostic**

If `delivered_by_clerk=true` and the email still doesn't arrive: deliverability problem (Item B / Resend path is the fix).
If `delivered_by_clerk=false` or the event never fires: Clerk-side issue (config / plan tier / Item C).

That single field is the question we've been blind on.
  without going to spam

When all four are checked, the original 2026-05-19 bug report
("no email arrived after Stripe payment") is closed.

## Telemetry to watch after rollout

PR #2 (#317) added the events that let us monitor whether this
fix worked:

- `webhook.received` — fires the moment Stripe delivers. Absence
  = Stripe delivery issue (unrelated to this PR's items).
- `webhook.checkout_completed.invitation_sent` — slicing this
  boolean tells us the % of paying users who got an activation
  email request fired from our side.
- `welcome_modal.invitation_status_resolved` with
  `status=invitation_pending` — fires when the client confirms
  the invitation exists. Drop from `invitation_sent=true` to
  this event means the email was created but the user didn't
  return to the modal (closed tab, redirect failed).
- `signin.completed` with `provider=clerk` — the user completed
  the invitation. Drop from the prior step is the deliverability
  signal — they didn't see/click the email.

PostHog **Funnel F — Activation email delivery** (created by
`scripts/posthog_create_funnels.py`) wraps all four steps. After
this checklist is done, the 2→3 step (status_resolved →
signin_completed) should show >70% conversion. Pre-PR it was
effectively 0% for the existing-user case and unknown otherwise.
