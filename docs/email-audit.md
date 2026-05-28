# Email & Invitation Funnel Audit

Date: 2026-05-28
Author: read-only audit per the task brief; full file map of every Resend
usage, conflict verdict, locale-sensitivity findings.

## Verdict

**YES — one confirmed conflict, severity LOW (observability-only).**

Activation and newsletter outbound emails share a single Resend project
and a single Resend lifecycle webhook (`/api/resend-webhook`). The
webhook maps every inbound `email.delivered` / `email.bounced` / etc. to
PostHog events named `newsletter.*` regardless of which Pulpo flow
originated the outbound. Activation-email lifecycle thus lands in
`newsletter.delivered` and inflates newsletter deliverability dashboards.

No correctness, deliverability, suppression, or rate-limit conflict was
found. The fix is additive (parse the `email_type` tag already stamped
by the activation send and surface it as a PostHog prop) and back-compat
with existing dashboards.

## Inventory of Resend usage

| # | File | Flow | `from:` | Client | Audience? |
|---|---|---|---|---|---|
| 1 | `api/_activation_email.js` | invitation | `PULPO_ACTIVATION_FROM_EMAIL` ∥ `Pulpo Club <hello@mail.pulpo.club>` | bare `fetch` to `https://api.resend.com/emails` | no |
| 2 | `api/stripe/webhook.js` (caller of #1) | invitation | (delegated) | (delegated) | no |
| 3 | `api/clerk/resend-invitation.js` (caller of #1) | invitation retry | (delegated) | (delegated) | no |
| 4 | `api/clerk/invitation-status.js` | invitation (read) | — | — | no |
| 5 | `api/clerk/webhook.js` | invitation (Clerk Svix → PostHog) | — | — | no |
| 6 | `api/newsletter.js` | newsletter subscribe | — | `new Resend(key)` (lazy singleton, per-request) | yes — `contacts.create` |
| 7 | `api/unsubscribe.js` | newsletter unsub (RFC 8058 one-click) | — | `new Resend(apiKey)` (per-request) | yes — `contacts.list` + `contacts.update` |
| 8 | `api/resend-webhook.js` | inbound lifecycle → PostHog | — | — (Svix-signed) | no |
| 9 | `api/contact.js` | contact-form forwarder | `RESEND_FROM_NOREPLY` ∥ `Pulpo <noreply@pulpo.club>` | `new Resend(apiKey)` (per-request) | no |
| 10 | `api/admin/newsletter/send.js` | admin test send (≤5 recipients) | `RESEND_FROM_EMAIL` ∥ `Pulpo <hello@mail.pulpo.club>` | `new Resend(apiKey)` (per-request) | no (direct `to:`) |
| 11 | `automation/newsletter/send.py` | newsletter dispatch (Python cron) | `RESEND_FROM_EMAIL` (no default) | `httpx.post` to `https://api.resend.com/emails` | no (direct `to:`) |
| 12 | `automation/newsletter/subscribers.py` | newsletter audience read | — | `httpx.get` to `/audiences/{id}/contacts` | read |
| 13 | `.github/workflows/pulpo-newsletter.yml` | newsletter cron env | — | — | — |
| 14 | `scripts/send_newsletter.py` | newsletter CLI orchestrator | (delegated to #11) | — | reads via #12 |
| 15 | `scripts/build_newsletter_dryrun.py` | dry-run fixtures | — | — | — |

### Env-var topology

| Env | Used by | Shared? |
|---|---|---|
| `RESEND_API_KEY` | every flow | yes — single Resend project key |
| `RESEND_AUDIENCE_ID` | #6 #7 #12 only | newsletter scope |
| `RESEND_FROM_EMAIL` | #10 #11 | newsletter scope |
| `PULPO_ACTIVATION_FROM_EMAIL` | #1 | invitation scope |
| `RESEND_FROM_NOREPLY` | #9 | contact-form scope |
| `RESEND_REPLY_TO_EMAIL` | #10 #11 (optional) | newsletter scope |
| `RESEND_WEBHOOK_SECRET` | #8 | single inbound endpoint |
| `PULPO_UNSUBSCRIBE_SECRET` | #7 + send.py token mint | newsletter scope |

Sending domain: `mail.pulpo.club` and `pulpo.club`, both DNS-verified.
Same Resend tenant; SPF/DKIM/DMARC are common.

### Rate limiters (all in-memory, per-IP, NOT cross-flow shared)

| Endpoint | Limit |
|---|---|
| `/api/newsletter` | 5 / 5 min |
| `/api/contact` | 5 / 5 min |
| `/api/clerk/resend-invitation` | 5 / hr |
| `/api/clerk/invitation-status` | 30 / min |
| `/api/admin/newsletter/send` | 10 / hr |

## The conflict (and only the conflict)

`api/resend-webhook.js` (`EVENT_MAP`):

```
email.sent       → newsletter.sent
email.delivered  → newsletter.delivered
email.bounced    → newsletter.bounced
...
```

`api/_activation_email.js` stamps:

```js
tags: [
  { name: "recipient_hash", value: hash },
  { name: "email_type", value: "activation" },
  ...
],
headers: { "x-pulpo-email-type": "activation", ... },
```

But `pickPostHogProps` in the webhook reads only `recipient_hash` and
`issue_number`. The `email_type` tag is dropped on the floor. Result:
every activation `email.delivered` event becomes a `newsletter.delivered`
PostHog event with `issue_number=null`, indistinguishable from a real
newsletter delivery without inspecting `recipient_hash` against the
hash of a known newsletter subscriber.

Counter-intuitively, `api/stripe/webhook.js:512` documents this routing
explicitly as if it were intended:

> the truer delivered/bounced signal comes from api/resend-webhook
> events (newsletter.sent / .delivered / .bounced)

— meaning the activation flow piggybacks on the newsletter dashboards.
Convenient for observability of activations, but contaminates the
newsletter deliverability numerator.

## Fix (this PR)

Smallest possible — extend `pickPostHogProps` to read the `email_type`
tag and stamp it as a prop on every emitted PostHog event. Existing
event names stay (`newsletter.*`). Dashboards that want to exclude
activations can add a filter `email_type = "newsletter"`; dashboards
that want activation-only can filter `email_type = "activation"`. No
new events, no renames, no migration.

In parallel, `api/_activation_email.js` gains two new PostHog events
per the task spec — `email.invitation.sent` on Resend 200/202, and
`email.send.failed` on any non-2xx — using the existing `posthog-node`
client (`api/_posthog.js`). The Python newsletter dispatcher gets a
sibling `email.send.failed` capture next to the existing
`newsletter.send_failed`. Both flows now emit the cross-flow `email.*`
event family the task asks for, without removing or renaming the
flow-specific events the existing dashboards reference.

## What is NOT in conflict

- **API key sharing** — same `RESEND_API_KEY` across flows is benign;
  Resend's per-key rate limit is well above combined volume (fortnightly
  newsletter cron + per-checkout activations).
- **Sender identity** — distinct `from:` env vars per flow, same verified
  sending domain. No SPF/DKIM/DMARC contention.
- **Audience / suppression list** — invitation flow never reads or writes
  `RESEND_AUDIENCE_ID`. An unsubscribed newsletter contact who later
  buys Pro still gets the activation email. Correct under CAN-SPAM /
  GDPR — transactional bypass.
- **Rate limiters** — five independent, per-flow, per-IP, in-memory
  limits keyed by name.
- **Resend webhook secret** — one inbound endpoint, fine. The label bug
  is downstream PostHog, not the wire.
- **Resend client lifecycle** — newsletter handlers instantiate
  `new Resend` per request; activation uses bare `fetch`. No global
  mutable state to collide.

## Locale-sensitivity findings

Both flows ARE locale-aware:

- **Activation email** — EN + ES templates in `_activation_email.js`;
  locale derived from Stripe Checkout `session.metadata.locale` (stamped
  by `start-checkout.js`) via `clerkLocaleFromStripe` in
  `api/stripe/webhook.js`. Falls back to English on unknown locale.
- **Newsletter dispatch** — per-recipient locale from Clerk
  `publicMetadata.profile.newsletter.locale` via `subscribers.py`'s
  `_locale_for()`. Subject line localized in `send_newsletter.py`.
  Body rendered locale-aware via `build_issue` / `render_html`.

**Closed gap (this PR):** `/api/newsletter` previously accepted only
`{ email, source }` — no `locale`. Anonymous Resend contacts (no
matching Clerk user) defaulted to `"en"` even when they signed up from
the Spanish homepage. This PR adds an optional `locale` to the POST
body, persists it on the Resend contact via the `first_name` field
using the strict prefix `pulpo-locale:<lc>`, and parses it back in
`subscribers.list_audience()` so the anonymous branch of
`join_recipients` returns the right locale. Resend's `first_name` is
not rendered anywhere in our newsletter templates (`display_name`
comes from Clerk's `first_name`), so the side-channel is safe.

Backwards-compat: existing contacts without the prefix continue to
default to `"en"`, identical to pre-PR behavior.
