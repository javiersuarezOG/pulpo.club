# Two-state user model — Phase 1 audit

**Goal:** collapse three states → two.
- **Today:** anonymous · signed-up-free (Clerk account, no payment) · Pro (paid).
- **Target:** **Free** (no account, no login — email-only newsletter capture) · **Pro** (paid, can log in).
- **Rule:** logging in is Pro-only. The "create a free account without paying" path is removed. Free = an email in a Resend audience, never a Clerk identity.

**Key reframing:** the new "Free" is essentially **today's anonymous state**. The middle state (signed-in-free Clerk account) is deleted. So: anonymous → becomes "Free"; Pro stays; the middle disappears.

---

## 1. Where the three-state model is encoded

### Frontend — tier resolution + caps
`web/app/lib/gating.ts`
- `Tier = "anonymous" | "free" | "pro" | "agency"` (the three-state model, literally).
- `tierFor(user)`: null → `anonymous`; plan pro/agency → that; **else → `free`** (this default IS the middle state).
- `isPaid(user)` = pro/agency. `needsSignup(user)` = anonymous.
- Caps by tier: USPs visible (anon 1, free 2, pro ∞), gallery thumbs (anon 2, free 2, pro ∞), `canSeeOffMarketSource` = `isPaid` only.

### Frontend — route gates
`web/app/lib/route-gates.ts`
- `home`, `browse`, `plans`, legal pages, `admin` → anonymous OK.
- `saved`, `account` → `minTier: "free"` (**the middle state's reason to exist on the route layer**). Anonymous hitting these opens the SignupModal.
- Listing **detail** has NO route gate — it's open to all, gated *inside the component* by soft caps + the off-market hard lock.
- Bypasses: `?welcome=1` (post-Stripe) and `?__clerk_ticket=` (activation) skip the gate.

### Frontend — login/signup flow
- **SignupModal** (`pages.jsx`): Clerk ON → calls `openSignUp()` / `openSignIn()`. **`openSignUp()` creates a FREE account** (no payment).
- **Free-account entry points (all to be removed/redirected):** heart/save button (`components.jsx:771`), home hero CTAs (`HeroV4/HeroV2/HomeShelf/FeaturedDeal`), `/saved` + `/account` route gates for anonymous, detail teaser save/share.
- **LegacySignupModal**: only when Clerk OFF; copy "Free account. No credit card." → deletable (Clerk always on in prod).
- **WelcomeModal**: post-`?welcome=1`; anon variant (check email) + signed-in variant (auto-dismiss). Post-payment landing — **keep**.
- **Login (sign-in) entry points:** SiteHeader account icon, `/start` "Log in" link, WelcomeModal "sign in existing" / "forgot password". Sign-in creates no account — **keep, but only Pro accounts will exist.**
- **Post-payment Pro path (critical, must keep working):** `/start` → `POST /api/stripe/start-checkout` → Stripe → `checkout.session.completed` webhook creates Clerk invitation **born with `plan:"pro"`** → activation email → `/account?__clerk_ticket=` → password set → `/account?welcome=1` signed-in Pro.

### Backend — user state (no DB; Clerk is the store)
- Plan lives in Clerk `publicMetadata.plan` ("pro"/"agency"/"free"/unset). `api/_plan.js` defaults non-pro/agency → "free".
- **What creates the middle state (plan=free Clerk account):**
  1. **Direct Clerk sign-up** (not via Stripe) → plan unset → resolves "free". *This is the path the refactor closes.*
  2. **Subscription cancel/delete** → `api/stripe/webhook.js:~1120` explicitly writes `plan:"free"`.
- Plan **writes**: every paid path writes `plan:"pro"` (webhook ~714/774/894/1076/1105/1246/1290). Only ~1120 writes `"free"`.
- Reads of "free" (`api/saves.js` free-save-cap=10; `api/_plan.js`; `subscribers.py`) all **default** non-Pro to "free" → they survive (semantically "non-Pro").

### Backend — subscriber / newsletter capture (the path to KEEP)
- `api/newsletter.js` + `api/_resend_audience.js`: **email-only, zero Clerk** — creates a Resend contact (`first_name: "pulpo-locale:<lc>"` side-channel), no account, no password. Confirmed independent of the refactor.
- `automation/newsletter/subscribers.py` joins Resend × Clerk: a free subscriber with no Clerk match stays `tier="free", has_account=False`. The `free_only` audience path (just added) becomes **anonymous-Resend-only** under the new model (no free Clerk users to match) — still correct, comments need updating.

### Templates (the Free render target)
- Free newsletter = the **free-tier templates in PR #778** (`pulpo-free-general` / `-welcome` / `-welcome-back`). This is exactly what the Free state's only account-action (email capture) points at. **Dependency confirmed: #778 is the Free render target.**

---

## 2. What the middle state controls + every entry point into it

**Controls (distinct-from-both behaviors):**
- Route access to `/saved` + `/account` (`minTier:"free"`).
- Server-synced saves with a **10-item cap** (`api/saves.js`), vs anonymous (local-only) and Pro (unlimited).
- `/account` rendering: newsletter upsell card + "free plan" subscription copy.
- Soft caps on listing detail (USPs 2 / gallery 2) — but these are **shared with anonymous**, so not middle-state-specific.

**Entry points INTO the middle state (account creation without paying):**
1. Heart/save while anonymous → `openSignUp()`.
2. Home hero / shelf / featured CTAs → `openSignUp()`.
3. `/saved` or `/account` while anonymous → route gate → SignupModal (signup mode).
4. Detail teaser save/share while anonymous → `openSignUp()`.
5. (Disabled today) Plans-page "Sign up free" button.
6. Any direct hit on Clerk's hosted sign-up.

---

## 3. Behavior changes the target model requires (not just deletions)

1. **Listing detail becomes Pro-only to OPEN.** Today it's open-to-all with soft caps. The target says Free "cannot open an individual listing." → Phase 2 must add a **hard gate**: Free clicking a result is blocked (wall / go-Pro), not shown a capped detail. *This is the biggest functional change, not a removal.*
2. **Save = Pro-only.** Remove the anonymous-stash + free-cap machinery; saving prompts Pro checkout.
3. **Login = Pro-only.** Remove all `openSignUp()` (free-account) entry points; keep `openSignIn()`. Close public Clerk sign-up so no new free accounts can be minted (Clerk config + remove the calls).
4. **Newsletter capture** stays as the email-only field — it's the Free user's sole account-like action. Already wired (#778 templates render it).

---

## 4. Removal / change / keep (for Phase 2 — not done yet)

| Area | Action |
|---|---|
| `gating.ts` tiers | Collapse to anonymous(=Free) vs pro/agency; drop the `free` middle. |
| `route-gates.ts` `saved`/`account` | `minTier: "free"` → `"pro"` (gate to paid). |
| Listing detail | Add hard Pro gate on open (new behavior). |
| Save/favorites | Remove anon-stash + free-cap path; CTA → Stripe checkout. |
| Free-account entry points (#1–6 above) | Remove or redirect to `/start`. |
| `openSignUp()` calls | Remove (except the invitation/activation flow); close public Clerk sign-up. |
| `LegacySignupModal` | Delete. |
| `api/stripe/webhook.js:~1120` (`plan:"free"` write) | Remove (no free accounts to drop to). |
| `subscribers.py` free-Clerk assumptions | Keep logic; update comments (free = anonymous Resend now). |
| Newsletter capture, Stripe→Pro invitation, WelcomeModal, sign-in | **Keep unchanged.** |

---

## 5. Decisions — RESOLVED (2026-06-08, Javi)

1. **Canceled Pro / "ever-paid": KEEP LOGIN IF EVER-PAID.** Accounts exist iff you paid at least once; a canceled subscriber can still log in to manage billing / resubscribe, with Pro *features* gated on active status. The only thing deleted is the **never-paid free account**. → Don't tear out the `everPaid` logic; the `plan:"free"` write on cancel can stay or become a `canceled` status, but the account + login persist.
2. **Listing detail for Free: HARD WALL ON CLICK.** A Free (anonymous) user clicking a result does NOT open the detail — show a "Go Pro to view listings" wall / route to `/start`. No capped teaser. This is the biggest new gate to build in Phase 2.
3. **Close public sign-up: YES — INVITATION-ONLY.** Restrict Clerk to invitation-only sign-up (dashboard config) so accounts are minted ONLY by the post-Stripe invitation flow, AND remove the frontend `openSignUp()` entry points. Belt-and-suspenders.

---

## 6. Dependency / sequencing

1. **Phase 1 audit** — this document. ✅
2. **Merge the free templates (PR #778)** — they are the Free state's render target (confirmed §1/Templates). Merge next, before Phase 2.
3. **Phase 2 implement** — only after #778 is on the working branch. FE changes get shown via a preview link before finalizing (per Javi's instruction).
