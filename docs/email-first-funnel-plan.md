# Email-first Free funnel — plan & flow audit

Status: **planning** (PR #831 = the top-3 view foundation is built/in-review; this plan sits on top of it).
Decisions locked (Javi): **Free = email-only, no login** (localStorage + Resend); **email unlocks the top-3** (anon sees cards → email unlocks top-3 full detail → Pro unlocks all 10 + catalogue); **one concentrated "Go Pro"** (in /plans, settings, avatar menu) — every other entry just captures email.

---

## 1. The model

Three client states:

| State | How you get there | Can see | Conversion surface |
|---|---|---|---|
| **Anonymous** (no email) | first visit | cards only; click a top-3 → **email-capture modal** | email capture |
| **Free member** (email in localStorage + Resend) | submit email | top-3 full detail (incl. broker link) + weekly Sunday email + avatar/settings | one "Go Pro" (plans/settings/avatar) + soft nudge on rank 4+ |
| **Pro** (Clerk + Stripe) | checkout | everything (all 10 + full catalogue + saves + broker links everywhere) | — |

Goal: lead with email (low-friction value exchange that leverages the newsletter machinery already built), nurture to Pro, concentrate the paywall instead of scattering hard Stripe walls.

---

## 2. Current-state inventory (audit, 2026-06-11)

### 2a. Signup / auth / conversion modals (frontend)
- **FreeMonthModal** (`web/app/components/FreeMonthModal.jsx`, `.free-month-modal`) — the conversion chokepoint. Opened by `app.openFreeMonthModal({trigger})` from **every** conversion CTA. On submit → POST `/api/stripe/start-checkout` (PULPOFREEMONTH pre-applied) → Stripe. Tier: anon + free.
- **SignupModal** (`pages.jsx:3217`) — `mode:"login"` → `AuthChoiceModal` → Clerk `openSignIn` (on) / `LegacySignupModal` (off). `mode:"signup"` is **dead**: the `openSignup` chokepoint (`app.jsx:1112-1135`) force-routes every non-login intent to FreeMonthModal.
- **AuthChoiceModal** (`pages.jsx:3185`) — inside SignupModal login; "Get Pulpo Pro" → FreeMonthModal.
- **LegacySignupModal** (`pages.jsx:3291`) — Clerk-OFF (CI/dev) only; `app.signin({email})` local, no API.
- **WelcomeModal** (`pages.jsx:4151`) — post-Stripe / post-invitation (`?welcome=1`). anon variant = "check inbox for Clerk invitation" + resend/status polling; signed_in variant = auto-dismiss welcome.
- **ProUpsellModal** (`pages.jsx:4538`) — home `/` acquisition on `?code=`/`?upsell=1`/UTM → Stripe.
- **HeroV5 EmailCapture** (`HeroV5.jsx:206-270`) — inline form → POST `/api/newsletter` `{email,source,locale}` → Resend audience. **Sets NO client state** (the disconnect to fix). Only `/api/newsletter` POST in the app.
- **ConsentBanner** — cookie consent only; does not gate auth.
- **Clerk hosted SignUp/SignIn** — `__clerk_ticket` activation + pending set-password + `?login=1`.

### 2b. CTA routing
Central matrix: `routeCtaForState(ctaId, user)` → branch (`stripe_checkout | paywall | free_signup | login_ui | free_month_modal | passthrough`) → `dispatchCentralBranch` (`web/app/lib/cta-routing.ts`). All conversion CTAs → `free_month_modal` for anon+free, `passthrough` for pro. `shelf_card` → passthrough all tiers (gate moved to in-panel detail CTAs). The **`free_signup` branch exists but is dead** (chokepoint reroutes to FreeMonthModal).

### 2c. Route gates (`web/app/lib/route-gates.ts`)
`home/browse/plans` → anonymous; **`saved/account` → minTier `free`**; legal → anonymous; `admin` → anonymous (API-gated). Bypasses: `account` + `?welcome=1`, `account` + `__clerk_ticket`.

### 2d. The critical state truth (`web/app/lib/gating.ts`)
`tierFor`: `!user → "anonymous"`; else `plan ?? "free"`. **"free" tier requires a Clerk-backed `app.user` today.** A newsletter-email subscriber is, to all gating code, **anonymous** (`app.user` stays null; EmailCapture stores nothing). The only producers of a `free`-plan `app.user` today: a churned ex-Pro (Clerk) or the legacy localStorage `signin()` seed.

### 2e. Email templates (one master renderer + 6 wrappers — `automation/newsletter/`)
| id | tier / lifecycle | EN/ES |
|---|---|---|
| `pulpo-pro-general` | Pro weekly | ✅ |
| `pulpo-pro-welcome` | Pro onboarding (1st payment) | ✅ |
| `pulpo-pro-welcome-back` | Pro resubscribe | ✅ |
| `pulpo-free-general` | Free weekly | ✅ |
| `pulpo-free-welcome` | Free onboarding (email signup) | ✅ |
| `pulpo-free-welcome-back` | Free re-acquisition (churned Pro→free OR free resub) | ✅ |
| activation (`api/_activation_email.js`) | transactional (set password) | ✅ |
| unsubscribe page (`api/unsubscribe.js`) | free/pro × en/es | ✅ |
| contact (`api/contact.js`) | internal | n/a |

`variant` switch in `render_html.py` drops the Pro masthead badge + swaps ranks-04-10 CTA to "Sign up to Pro" + Pro-locks the news spotlight for `is_free`. Welcome-back copy is **derived** from welcome copy (can't drift).

### 2f. Email triggers (`api/`, `.github/workflows/`)
- **Free signup** → `/api/newsletter` → Resend `contacts.create` + `fireFreeWelcome` → `/api/internal/free-welcome-send` → `pulpo-free-welcome[-back]`. **Clerk-free, DB-free** ✅
- **Pro welcome** Paths A/B/C + hourly reconcile cron — **all Clerk-keyed** (idempotency stamp in Clerk `publicMetadata.welcome_newsletter_sent_at`).
- **Free welcome / welcome-back** → `api/internal/free-welcome-send.py` — **Clerk-free** ✅ (idempotency = Resend "is_new_contact" at trigger moment; no persistent stamp).
- **Churned Pro→Free welcome-back** → Stripe webhook `subscription.deleted` → `fireFreeWelcomeBack` (Clerk stamp `downgrade_welcome_sub_id`).
- **Activation** → Stripe webhook (new-user checkout) → Clerk invitation `notify:false` → Resend.
- **Weekly Pro** (`pulpo-newsletter.yml`, Sun 16:00, LIVE) / **Weekly Free** (`pulpo-newsletter-free.yml`, Sun 17:00, **STAGED dry-run until `FREE_NEWSLETTER_LIVE=true`**).
- **Unsubscribe** → `api/unsubscribe.js` (HMAC token, Resend audience scan) — **Clerk-free** ✅
- **Resend webhook** → `api/resend-webhook.js` → PostHog (`email_type` discriminator; `KNOWN_EMAIL_TYPES`).

### 2g. The Clerk-assumption map (refactor-critical)
**Good news: the Free email surface is already mostly Clerk-free** — signup, free welcome/welcome-back, weekly free send, unsubscribe all run with NO Clerk account. Every Clerk-assuming trigger is a **Pro-tier path** that correctly never fires for email-only Free.
**The one gap:** the **Free welcome has no reconcile backstop** (Pro has the hourly cron, which enumerates Clerk and can't see email-only Free). Its only delivery attempt is the single best-effort awaited call in `api/newsletter.js`.

---

## 3. The refactor (3 PRs)

### The two-modal split (core principle)
Today the `openSignup` chokepoint force-routes **every** conversion CTA into the FreeMonthModal → Stripe ($9.99). After the refactor there are TWO distinct modals:
- **EmailCaptureModal** — shown to **anonymous** users hitting *any* gated action (open a top-3, save, hero lock, detail-upgrade, USP lock, ProUpsell). Asks for **email only**, "start free like the home hero", unlocks the top-3 + weekly digest. This is where ~all current FreeMonthModal triggers get rerouted.
- **Go Pro modal** (today's FreeMonthModal → Stripe, copy unchanged) — **demoted**: only shown to **free members** who want full access, and only at the concentrated points (`/plans`, settings, avatar) + a soft nudge on rank 4+. Anonymous users never see the $9.99 push as their first interaction.

### PR-A — Free-member state + email-gate the top-3
- **New primitive:** on EmailCapture success, write a localStorage seed (`pulpo-free-member` = `{email, captured_at, locale, provider:"email"}`) and hydrate `app.user = {plan:"free", provider:"email", email}`. `tierFor` already returns `"free"` for `{plan:"free"}` — **no change to tierFor**; the work is producing that `app.user` alongside Clerk hydration, with **Clerk winning when both exist** (preserve the `useState`-seed-then-ClerkUserSync-overwrite order).
- **Re-key the #831 top-3 gate:** top-3 opens for **free-member OR pro**; anonymous (no email) hitting a top-3 → **EmailCaptureModal** (not Stripe).
- **EmailCaptureModal:** the primary anon→free surface. POST `/api/newsletter`; on success set free-member state, close, and **continue the intended action** (open the listing they clicked).
- **Untangle the dead `free_signup`:** route the `openSignup` chokepoint + legacy `mode:"signup"` callers (HeroV2/V4, HomeShelf, FeaturedDeal) to email-capture instead of FreeMonthModal.
- Telemetry: `email_capture_shown/submitted/succeeded`, `free_member_created`, `paywall.shown{tier}`.

### PR-B — funnel surfaces + concentrated Pro CTA + free-member settings
- **Demote FreeMonthModal to the one "Go Pro"** — fired only from `/plans`, settings, and the avatar menu (+ optional *soft* nudge for a free member on rank 4+; not a hard wall).
- **Avatar / header for free member** (`SiteHeader.jsx`, `BottomNav.jsx`): show a member affordance + menu (preferences · Go Pro · manage email), **no Clerk**.
- **Free-member settings surface** (Javi: "don't forget settings"). `/account` is Clerk/Pro today. Build a lightweight free-member preferences surface: **newsletter category chips, locale, frequency, unsubscribe** — persisted to **Resend** (audience side-channel / a small prefs endpoint), **not** Clerk `publicMetadata`. Must obey "NEVER ship a control that lies about persistence" — real Resend consumer wired before the control ships.
- **route-gates / cta-routing:** decide free-member access — `/saved` stays Pro (saves are Pro); `/account` for a free member shows the lightweight settings, not a SignupModal; conversion CTAs for a free member route to Go-Pro, not an auth prompt. Make `non-Pro === (anonymous OR free-member)` everywhere that today assumes `non-Pro === anonymous` (`needsSignup`, `cta-routing`, `route-gates`).

### PR-C — continuity, backstop, go-live
- **Free→Pro linking + attribution (the one real risk):** thread the free member's email into `start-checkout` (it already accepts optional `email` + stamps session/subscription metadata; webhook Path B uses email as the join key). Pre-fills Stripe so the address can't diverge → the eventual Clerk account = the same person as the Resend free contact; pass `posthog_anon_id` + a "converted_from_free" source flag for attribution.
- **Free welcome reconcile backstop:** add a Resend-audience-driven equivalent of the Pro reconcile cron (the one structural gap) so a dropped free welcome isn't silently lost.
- **Flip `FREE_NEWSLETTER_LIVE=true`** so captured emails get the weekly nurture.
- E2E + the full template×trigger matrix (below).

---

## 4. End-to-end verification matrix (free + pro, all templates + triggers)

Run before declaring the refactor done. Dry-run commands are non-sending; live sends are operator-gated.

| Lifecycle event | Template | How to exercise (dry-run / preview) |
|---|---|---|
| Anon submits email | `pulpo-free-welcome` | `POST /api/admin/newsletter/trigger-free-welcome-test {email,variant:"free_welcome",locale}` |
| Free resubscribe | `pulpo-free-welcome-back` | `trigger-free-welcome-test {variant:"free_welcome_back"}` |
| Free weekly | `pulpo-free-general` | `python3 scripts/send_newsletter.py --newsletter pulpo-free-general --only-email you@x` |
| Pro 1st payment | `pulpo-pro-welcome` | `trigger-welcome-test {variant:"welcome"}` |
| Pro resubscribe | `pulpo-pro-welcome-back` | `trigger-welcome-test {variant:"welcome_back"}` |
| Pro weekly | `pulpo-pro-general` | `python3 scripts/build_newsletter_dryrun.py --issue-number N` |
| Churned Pro→free | `pulpo-free-welcome-back` | cancel a sandbox sub → webhook → check dispatch |
| New-user checkout | activation email | run sandbox checkout on a brand-new email → inbox |
| Unsubscribe (free/pro) | confirm page | `GET /api/unsubscribe?...&e=free|pro&l=en|es` |
| Resend lifecycle | (PostHog) | `vitest tests/api/newsletter_resend_webhook.test.js` + contract test |

Plus the **live walk** (Javi, on the preview): anon→email→top-3 unlock; free→Go-Pro→Stripe sandbox→activation email→Clerk signup→Pro; free-member settings persist across reload; unsubscribe round-trip.

---

## 5. Open decisions / risks
- **Free-member settings persistence** — confirm the Resend prefs consumer exists or build it first (no lying controls).
- **Free→Pro email continuity** — the conversion is only attributable if the captured email threads into checkout. This is PR-C's core.
- **Free welcome backstop** — decide whether the Resend-driven reconcile is in-scope now or a fast-follow.
- **`/account` for free members** — lightweight settings vs. upgrade wall. (Leaning: settings, since the whole point is to nurture, not wall.)
- **#831 interaction** — merge #831 (top-3 open to all) first; PR-A tightens top-3 to members (a strictly-more-gated, additive change). `/plans` copy holds verbatim.
