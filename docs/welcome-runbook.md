# Pulpo Pro Welcome — runbook

**When to use this:** a Pro user paid but tells you they never got the welcome email, OR the `Pulpo webhook health` workflow Slack-alerts on a welcome-related check.

**Last verified:** 2026-06-01 (end-to-end prod walk)

---

## Architecture (1-paragraph refresher)

Three live dispatch paths, all converging on the same Python dispatcher:

```
Path A (auth_gated)              ─┐
  Stripe checkout webhook         │  → dispatchProWelcome
  with client_reference_id        │      ├─ Vercel Python primary (<5s)
                                  │      └─ GH Actions fallback (~30s)
Path B (anonymous existing)      ─┤             ↓
  Stripe checkout webhook         │       dispatch_welcome.py
  no client_reference_id,         │       (find Clerk user → check stamp
  email matches existing user     │        → render → Resend → stamp)
                                  │
Path C (anonymous invitation)    ─┘
  Clerk user.created webhook (fires AFTER signup completes)
```

**Hourly reconcile cron** (`:15 * * * *` UTC) is the safety net — queries Clerk for `plan=pro && !welcome_newsletter_sent_at && age 1h-7d` and dispatches.

**Idempotency:** Clerk `publicMetadata.welcome_newsletter_sent_at` (ISO-8601 string). Stamped after every successful Resend 2xx. Permanent — locked decision, no resubscribe re-sends.

---

## "User X didn't get their welcome" — debug flow

Five things to check, in order:

### 1. Did they actually pay?

```bash
# Did Stripe see the checkout?
gh workflow list --all | grep stripe
npx vercel logs --since=24h --no-follow --environment=production -n 200 --json \
  | grep -iE "stripe.webhook.*$EMAIL_OR_SESSION_PREFIX"
```

Look for `[api] stripe.webhook status=200 ... path=auth_gated|anonymous_existing_user|anonymous_invitation_created` with their email or session ID.

- **No log line** → they didn't actually complete checkout (or you're looking at the wrong email)
- **Log line shows `path=anonymous_invitation_created` and `welcome=pending:awaits_invitation_acceptance`** → they paid but haven't completed Clerk signup yet. Send them the activation email or have them click the original.

### 2. Did the dispatch fire?

```bash
# Look for the dispatch outcome on the same email
npx vercel logs --since=24h --no-follow --environment=production -n 500 --json \
  | grep -iE "welcome_internal|welcome_dispatched|welcome_skipped|welcome_failed"
```

Expected log line shapes:
- `welcome=internal:sent` → Vercel Python success
- `welcome=skipped:already_sent` → idempotency stamp hit (they ARE in Clerk with the stamp set)
- `welcome=internal:http_500` → Vercel Python dispatcher returned failed
- `welcome=internal_unreachable_falling_back` → Vercel Python timeout/fetch fail; GH Actions taking over
- `welcome=dispatched` → GH Actions fallback succeeded
- `welcome=skipped:filter_skipped` (Clerk webhook) → Path C filter rejected. Check user's `publicMetadata.plan` and `private_metadata.stripeCustomerId` in Clerk dashboard.

### 3. Check Clerk publicMetadata

Open Clerk dashboard → Users → search for the email → click row → look at JSON metadata.

- `publicMetadata.welcome_newsletter_sent_at` is set → welcome WAS dispatched successfully; problem is downstream (Resend bounce, user's mailbox filtering, wrong email address on Clerk)
- `publicMetadata.plan === "pro"` is set → they're correctly Pro. Now check stamp.
- `publicMetadata.plan !== "pro"` → Stripe webhook didn't flip them to Pro. Bigger problem; look at `customer.subscription.updated` events.
- `private_metadata.stripeCustomerId` is set (Path C users only) → they came via Stripe payment. Filter should have accepted them.

### 4. Check Resend dashboard

If the dispatch succeeded but the user didn't receive the email:

1. Go to resend.com/emails
2. Search by recipient email
3. Look at the event timeline: `sent` → `delivered` → (if `bounced` / `complained` / `marked_as_spam`, that's your answer)

If Resend has no record at all, the dispatcher never called Resend → re-trace via Vercel logs.

### 5. Force a manual dispatch (last resort)

```bash
# Resends the welcome even if the stamp is set (force=true, the endpoint default)
curl -X POST https://pulpo.club/api/admin/newsletter/trigger-welcome-test \
  -H "Content-Type: application/json" \
  -d '{"email":"USER@example.com"}'
```

This dispatches the workflow at https://github.com/javiersuarezOG/pulpo.club/actions/workflows/pulpo-pro-welcome.yml — watch the run log for `[welcome] status=...`.

**Effect:** sends another welcome AND re-stamps Clerk. Won't double-send to users who already have the stamp UNLESS you use `force=true` (which the endpoint defaults to — pass `{"force": false}` in the body to respect the stamp).

---

## Slack alerts — what each one means

The `Pulpo webhook health` workflow (`.github/workflows/pulpo-webhook-health.yml`) fires every 6h. These are the welcome-relevant checks:

| Alert | What it means | First diagnostic step |
|---|---|---|
| `Welcome reconcile cron` silent > 2h | GH Actions stopped honoring the hourly cron OR the script is throwing | Check https://github.com/javiersuarezOG/pulpo.club/actions/workflows/pulpo-welcome-reconcile.yml for failures |
| `Welcome dispatch failure rate` > 10% | The dispatcher is returning `status=failed` on more than 1 in 10 attempts | Check Resend status; check `RESEND_API_KEY` valid; check Resend dashboard for bounces |
| `Welcome Vercel Python fallback rate` > 25% | Vercel Python instant path unreachable, GH Actions carrying everything; users still get welcomes but slower (30-75s vs <5s) | Check Vercel dashboard for `api/internal/welcome-send` function errors. Check `PULPO_INTERNAL_TOKEN` env var still set. |
| `Weekly Pro digest send failure rate` > 5% over 8d | The Sunday cron has been failing for >5% of recipients | Check Sunday's `pulpo-newsletter` workflow run logs |

---

## Common edge cases

### "User got TWO welcomes" — duplicate send

**Most likely cause:** operator hit the admin trigger endpoint twice (it defaults `force=true` which bypasses the stamp). Each call dispatches a fresh send.

**Not a system bug** — the dispatcher's `force=false` paths (Stripe webhook, Clerk webhook, reconcile cron) all respect the stamp and won't duplicate.

To verify: check Vercel logs for the admin trigger endpoint:
```bash
npx vercel logs --since=1h --json | grep "admin.newsletter_trigger_welcome_test"
```
If you see two POST entries close in time, that's two manual triggers.

### "User got the welcome but never logged in"

Welcome dispatched correctly; user just hasn't accepted the invitation link.

The activation link in their inbox is from the SEPARATE activation email (sent by the Stripe webhook on Path C, via Resend). The welcome is a different email entirely, sent AFTER they accept the invitation.

This is the canonical Path C sequence:
1. Pay via /start
2. Receive activation email ("Set up your Pulpo Pro account")
3. Click link, complete Clerk signup (set password)
4. **Then** receive the welcome ("Welcome to Pulpo Pro — your first 10")

### "Reconcile cron found 9 eligible orphans but dispatched 0"

This is the **Clerk list-API stale-read quirk** (documented in [[project-welcome-reconcile-cron]] memory).

The reconcile FILTER (`/v1/users` with `created_at` filter) sometimes serves stale publicMetadata from a read replica that lags writes by minutes. The DISPATCHER's per-user fetch (`/v1/users?email_address[]=...`) sees fresh data and correctly skips with `already_sent`.

`found > 0 sent = 0 skipped = N` is the common case after a busy welcome-dispatch window. **Not a leak.** Only worry if `found > 0 AND sent > 0` consistently across multiple ticks after all known orphans should have cleared.

### "Welcome arrived but with no first name in the H1"

The welcome's H1 reads `Welcome, {first_name}.` when Clerk has `first_name` set, falling back to `Welcome aboard.` otherwise.

If a user's H1 reads `Welcome aboard.`, they didn't set a first name during Clerk signup. Not a bug — the fallback is intentional. If you want them to get a personalized welcome, have them update their profile and trigger a manual re-dispatch with `force=true`.

---

## Re-running for a specific user (post-incident)

```bash
# Dry-run first to see what would dispatch
gh workflow run pulpo-welcome-reconcile.yml -f send_mode=no

# Then live for the backlog
gh workflow run pulpo-welcome-reconcile.yml -f send_mode=yes -f max_users=20

# Or target a single user manually
curl -X POST https://pulpo.club/api/admin/newsletter/trigger-welcome-test \
  -H "Content-Type: application/json" \
  -d '{"email":"USER@example.com","force":false}'
```

`force=false` respects the stamp — useful for verifying a user IS already welcomed without sending another email. The endpoint returns `status=skipped:already_sent` in that case.
