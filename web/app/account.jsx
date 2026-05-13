// Pulpo — Account area (A.3 from PRD addendum).
// Two-column layout: left-nav (sub-sections) + right content. Mobile: stacks.
// Subsections: Profile, Notifications, Manage Subscription, Security (stub).
// Uses same design tokens as the rest of the app — no special chrome.
import React, { useState as aUseState, useEffect as aUseEffect, useMemo as aUseMemo } from "react";
import { t, tr } from "./i18n.jsx";
import { Icon, PulpoLogo, formatPrice, currentLocale } from "./components.jsx";
import { startStripeCheckout } from "./auth/stripe-checkout.js";
import { openStripePortal } from "./auth/stripe-portal.js";
import { clerkEnabled } from "./auth/clerk-shell.jsx";
import { COUNTRIES } from "./lib/countries.js";
import { track } from "./telemetry/hook";
import {
  PREFERENCE_CATEGORY_KEYS,
  PREFERENCE_CATEGORY_LABEL_KEY,
  PREFERENCE_CATEGORIES_MAX,
  sanitizePreferredCategories,
} from "./lib/categories";
import { readProfile } from "./lib/user-profile";

function AccountPage({ app }) {
  // Source of truth for the active tab is `app.routeParams.section` — set
  // by the URL parser on cold-load + popstate, and by `app.go("account",
  // { section })` on in-app clicks. Default to "profile" when the URL is
  // bare `/account` (no segment).
  const section = app.routeParams.section || "profile";

  // Section-viewed telemetry. Fires on every resolved tab — cold-load,
  // in-app click, browser back/forward. `_entry` is a private hint set
  // by app.jsx's `go` / popstate listener; absent on cold-load → "url".
  // The dependency on `section` covers tab switching; `_entry` is read
  // off routeParams at fire time so we don't need it in the dep array.
  aUseEffect(() => {
    if (clerkEnabled() && !app.clerkActions) return; // wait for Clerk hydrate
    if (!app.user) return;                            // gate still resolving
    const entry = app.routeParams._entry === "nav_click" ? "nav_click"
      : app.routeParams._entry === "popstate" ? "popstate"
      : "url";
    track("account.section_viewed", { section, entry });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, app.user, app.clerkActions]);

  // Auth gate. The Account area is auth-only — anonymous users get
  // redirected to /home with the Sign-in modal teed up. There's a race
  // we have to respect when Clerk is enabled: on first paint
  // ClerkUserSync hasn't yet committed `setUser`, so `app.user` is
  // briefly null even for genuinely-signed-in users. If we redirect
  // during that window:
  //   1. SignupModal opens with mode="login"
  //   2. Its Clerk effect calls `clerk.openSignIn()`
  //   3. Clerk knows the user IS signed in already → throws
  //      `cannot_render_single_session_enabled`
  //   4. ErrorBoundary catches → "Something went wrong"
  //
  // `app.clerkActions` becoming truthy is a reliable lower bound on
  // Clerk having loaded. Stay on the page (loading shell) until the
  // SDK has hydrated; then check user state.
  //
  // Hooks run unconditionally (Rules of Hooks) — schedule the redirect
  // inside the effect rather than wrapping the hook in `if (!app.user)`.
  // The previous shape violated the rule and was firing the redirect
  // during the Clerk-boot window.
  const clerkBooting = clerkEnabled() && !app.clerkActions;
  // PR section-urls: the App-level route-gate handles opening the
  // sign-in modal for anonymous /account hits, and the URL stays at
  // /account so post-signin the content slot is already correct.
  // We only need this effect to cover the Clerk-boot edge case where
  // the gate hasn't run yet — open the modal as a safety net but DO
  // NOT call app.go("home"), which would change the URL out from under
  // the user.
  aUseEffect(() => {
    if (clerkBooting) return;
    if (app.user) return;
    app.openSignup({ mode: "login" });
  }, [clerkBooting, app.user]);

  if (clerkBooting) {
    return <div className="page page-account account-loading" aria-busy="true" />;
  }
  // /account?welcome=1 — post-Stripe (or post-magic-link) landing.
  // The route gate (route-gates.ts) allowed an anonymous render through
  // for this URL; we show a neutral placeholder that the <WelcomeModal>
  // sits on top of. Refresh strips the param (see app.jsx's effect)
  // so the user only ever sees this state for one render cycle while
  // the modal is up.
  if (!app.user) {
    const isWelcomeLanding = typeof window !== "undefined"
      && new URLSearchParams(window.location.search).get("welcome") === "1";
    if (isWelcomeLanding) {
      return <div className="page page-account account-welcome-preview" aria-busy="true" />;
    }
    return null;
  }

  const subs = [
    { key: "profile",       label: t("account.profile", app.locale),       icon: "user" },
    { key: "notifications", label: t("account.notifications", app.locale), icon: "bell" },
    { key: "subscription",  label: t("account.subscription", app.locale),  icon: "sparkle" },
    { key: "security",      label: t("account.security", app.locale),      icon: "lock" },
  ];

  return (
    <div className="page page-account">
      <div className="account-layout">
        <aside className="account-nav">
          <h1 className="account-nav-title">{t("nav.account", app.locale)}</h1>
          <ul>
            {subs.map(s => (
              <li key={s.key}>
                <button
                  className={section === s.key ? "is-active" : ""}
                  onClick={() => app.go("account", { section: s.key })}
                >
                  <Icon name={s.icon} size={16}/>
                  <span>{s.label}</span>
                </button>
              </li>
            ))}
          </ul>
          <button className="account-back" onClick={() => app.go("home")}>
            {t("account.back", app.locale)}
          </button>
        </aside>

        <main className="account-content">
          {section === "profile"       && <ProfileSection app={app} />}
          {section === "notifications" && <NotificationsSection app={app} />}
          {section === "subscription"  && <SubscriptionSection app={app} />}
          {section === "security"      && <SecuritySection app={app} />}
        </main>
      </div>
    </div>
  );
}

// ============== A.3.1 — Profile ==============
function ProfileSection({ app }) {
  const initial = {
    name: app.user.name || "",
    email: app.user.email || "",
    country: app.user.country || "SV",
    language: app.locale,
  };
  const [values, setValues] = aUseState(initial);
  const [saved, setSaved] = aUseState(false);
  const dirty = JSON.stringify(values) !== JSON.stringify(initial);

  // Country picker is a `<datalist>` combobox: 250-row native `<select>`
  // is unfilterable on mobile (just a long alpha-stride list). Datalist
  // gives free type-to-filter with zero deps. We track the displayed
  // *name* alongside the stored ISO code; on blur, an unrecognised
  // string reverts to the last valid country's name so the form never
  // ends up with a half-typed value silently saving as "".
  const codeToName = (code) => {
    const c = COUNTRIES.find(x => x.code === code);
    return c ? c.name : "";
  };
  const [countryInput, setCountryInput] = aUseState(() => codeToName(initial.country));
  const onCountryInputChange = (typed) => {
    setCountryInput(typed);
    const match = COUNTRIES.find(c => c.name === typed);
    if (match) setValues(v => ({ ...v, country: match.code }));
  };
  const onCountryInputBlur = () => {
    const match = COUNTRIES.find(c => c.name === countryInput);
    if (!match) setCountryInput(codeToName(values.country));
  };

  const onSave = (e) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const initials = (values.name || values.email || "?").trim()[0].toUpperCase();

  return (
    <form className="account-section" onSubmit={onSave}>
      <div className="profile-photo-row">
        <div className="profile-avatar">{initials}</div>
        <div>
          <div className="profile-photo-label">{t("account.profile.photo", app.locale)}</div>
          <button type="button" className="link-btn">{t("account.profile.upload_photo", app.locale)}</button>
        </div>
      </div>

      <FieldRow label={t("account.profile.name", app.locale)}>
        <input
          type="text"
          value={values.name}
          placeholder={t("account.profile.name_placeholder", app.locale)}
          onChange={(e) => setValues(v => ({ ...v, name: e.target.value }))}
        />
      </FieldRow>

      <FieldRow
        label={t("account.profile.email", app.locale)}
        hint={t("account.profile.email_note", app.locale)}
      >
        <input
          type="email"
          value={values.email}
          placeholder="your@email.com"
          onChange={(e) => setValues(v => ({ ...v, email: e.target.value }))}
        />
      </FieldRow>

      <FieldRow label={t("account.profile.country", app.locale)}>
        {/* Full ISO 3166-1 list as a `<datalist>` combobox — type-to-
            filter on mobile and desktop. We show the country *name*
            but persist the ISO code (values.country). */}
        <input
          type="text"
          list="pulpo-country-options"
          value={countryInput}
          onChange={(e) => onCountryInputChange(e.target.value)}
          onBlur={onCountryInputBlur}
          autoComplete="country-name"
          placeholder={t("account.profile.country_placeholder", app.locale)}
        />
        <datalist id="pulpo-country-options">
          {COUNTRIES.map(c => (
            <option key={c.code} value={c.name} />
          ))}
        </datalist>
      </FieldRow>

      <FieldRow label={t("account.profile.lang", app.locale)}>
        <select
          value={values.language}
          onChange={(e) => {
            setValues(v => ({ ...v, language: e.target.value }));
            app.setLocale(e.target.value);
          }}
        >
          <option value="en">English</option>
          <option value="es">Español</option>
        </select>
      </FieldRow>

      {dirty && (
        <div className="account-save-row">
          <button type="submit" className="btn-primary">
            {t("account.profile.save", app.locale)}
          </button>
        </div>
      )}
      {saved && <div className="account-inline-confirm">{t("account.profile.saved", app.locale)}</div>}
    </form>
  );
}

function FieldRow({ label, hint, children }) {
  return (
    <div className="field-row">
      <label className="field-label">{label}</label>
      <div className="field-control">
        {children}
        {hint && <div className="field-hint">{hint}</div>}
      </div>
    </div>
  );
}

// ============== A.3.2 — Notifications ==============
function NotificationsSection({ app }) {
  const [prefs, setPrefs] = aUseState({
    newsletter: true,
    price_drops: true,
    new_in_zones: false,
    platform_updates: false,
    whatsapp: false,
    whatsapp_number: "",
    frequency: "weekly",
  });
  const [confirm, setConfirm] = aUseState(false);

  const flash = () => {
    setConfirm(true);
    setTimeout(() => setConfirm(false), 2000);
  };
  const setKey = (k, v) => { setPrefs(p => ({ ...p, [k]: v })); flash(); };

  // Pro-only deal alerts. Free users see an upgrade prompt instead
  // of these toggles; we keep `platform_updates` accessible to
  // everyone because it's product news, not premium content.
  const isPaid = !!(app.user && app.user.plan && app.user.plan !== "free");

  // Pro notification rows. `price_drops` and `new_in_zones` are wired
  // in the UI table but their delivery features don't exist yet — hide
  // them rather than promise something we can't deliver. To re-enable
  // when the features ship, restore the two rows below; the i18n keys
  // and the local prefs-state defaults are intentionally preserved.
  const proCats = [
    { key: "newsletter",   title: t("account.notif.newsletter.title",   app.locale), desc: t("account.notif.newsletter.desc",   app.locale) },
  ];
  const freeCats = [
    { key: "platform_updates", title: t("account.notif.platform_updates.title", app.locale), desc: t("account.notif.platform_updates.desc", app.locale) },
  ];

  return (
    <div className="account-section">
      <p className="section-intro">{t("account.notif.intro", app.locale)}</p>

      {!isPaid && <NotifProUpsell app={app} />}

      {isPaid && (
        <div className="pref-list">
          {proCats.map(c => (
            <div className="pref-row" key={c.key}>
              <div className="pref-text">
                <div className="pref-title">{c.title}</div>
                <div className="pref-desc">{c.desc}</div>
              </div>
              <Toggle
                checked={prefs[c.key]}
                onChange={v => setKey(c.key, v)}
                ariaLabel={c.title}
              />
            </div>
          ))}
        </div>
      )}

      {/* Category preferences — sits directly under the newsletter toggle.
          Hidden when newsletter is off (spec). Selection persists across
          reloads via app.user.profile; cross-device sync arrives in PR-C. */}
      {isPaid && prefs.newsletter && <PreferredCategoryChips app={app} />}

      <div className="pref-list">
        {freeCats.map(c => (
          <div className="pref-row" key={c.key}>
            <div className="pref-text">
              <div className="pref-title">{c.title}</div>
              <div className="pref-desc">{c.desc}</div>
            </div>
            <Toggle
              checked={prefs[c.key]}
              onChange={v => setKey(c.key, v)}
              ariaLabel={c.title}
            />
          </div>
        ))}
      </div>

      {/* "Channels" block (Email-always-on + WhatsApp opt-in) hidden
          for now — email is the only delivery channel today, and a
          single locked "Email — Required" row reads as noise. Restore
          this whole block when WhatsApp delivery actually ships; i18n
          keys + local prefs-state defaults are intentionally preserved. */}

      {isPaid && prefs.newsletter && (
        <>
          <h3 className="account-subhead">{t("account.notif.frequency", app.locale)}</h3>
          <div className="freq-toggle">
            {["weekly","biweekly"].map(f => (
              <button
                key={f}
                type="button"
                className={prefs.frequency === f ? "active" : ""}
                onClick={() => setKey("frequency", f)}
              >
                {t(f === "weekly" ? "account.notif.freq_weekly" : "account.notif.freq_biweekly", app.locale)}
              </button>
            ))}
          </div>
        </>
      )}

      {confirm && <div className="account-inline-confirm">{t("account.notif.saved", app.locale)}</div>}

      {isPaid && (
        <p className="unsub-note">
          {t("account.notif.unsub_note", app.locale)}
        </p>
      )}
    </div>
  );
}

// Upgrade CTA shown to free / anonymous users in the Notifications
// subsection in place of the Pro-gated toggles. Click → standard Stripe
// checkout flow (or signup → checkout for anonymous users via the
// existing pendingAction chain).
function NotifProUpsell({ app }) {
  const onUpgrade = () => {
    startStripeCheckout({
      onError: (code) => {
        if (code === "sign_in_required") {
          if (app.user) {
            app.showToast(t("plans.checkout_auth_mismatch", app.locale));
          } else {
            app.openSignup({ mode: "signup", pendingAction: "checkout" });
          }
        } else {
          app.go("plans");
        }
      },
    });
  };
  return (
    <div className="notif-upsell">
      <div className="notif-upsell-icon">
        <Icon name="sparkle" size={20} strokeWidth={1.8}/>
      </div>
      <div className="notif-upsell-body">
        <h3>{t("account.notif.upsell.title", app.locale)}</h3>
        <p>{t("account.notif.upsell.body", app.locale)}</p>
        <ul className="notif-upsell-list">
          {/* price_drops + new_in_zones bullets removed alongside the
              matching toggles in NotificationsSection — restore here
              once the delivery features actually ship. */}
          <li>{t("account.notif.newsletter.title", app.locale)}</li>
        </ul>
        <button className="btn-primary" onClick={onUpgrade}>
          {t("account.notif.upsell.cta", app.locale)}
        </button>
      </div>
    </div>
  );
}

// Preferred categories — multi-select pill chips capped at
// PREFERENCE_CATEGORIES_MAX. Selection is mirrored to
// app.user.profile.preferred_categories via `app.updateUserProfile`,
// which persists to localStorage today and (PR-C) Clerk.
//
// Hidden when newsletter is off (parent gates rendering). When unmounted,
// the selection stays in `profile` — toggling newsletter back on
// re-renders the same chips active. Only the UI is conditional.
//
// Categories live in lib/categories.ts (single source of truth across
// the app). See lib/README-categories.md for the lifecycle.
function PreferredCategoryChips({ app }) {
  const profile = readProfile(app.user);
  const selected = aUseMemo(
    () => sanitizePreferredCategories(profile.preferred_categories),
    [profile.preferred_categories],
  );
  const [limitHit, setLimitHit] = aUseState(false);
  const limitHitTimerRef = React.useRef(null);

  // Auto-clear the limit hint after ~3s. Re-firing the click resets
  // the timer so the message stays visible while the user keeps
  // tapping the capped chip.
  const flashLimitHit = (attemptedKey) => {
    setLimitHit(true);
    if (limitHitTimerRef.current) clearTimeout(limitHitTimerRef.current);
    limitHitTimerRef.current = setTimeout(() => setLimitHit(false), 3000);
    track("account.preferred_categories_limit_hit", {
      attempted_category: attemptedKey,
      current_selection: selected,
    });
  };

  aUseEffect(() => () => {
    if (limitHitTimerRef.current) clearTimeout(limitHitTimerRef.current);
  }, []);

  const onToggle = (key) => {
    const isSelected = selected.includes(key);
    let next;
    let action;
    if (isSelected) {
      next = selected.filter((k) => k !== key);
      action = "deselect";
      // Deselecting always clears any visible limit hint — the user
      // just freed up a slot.
      setLimitHit(false);
    } else {
      if (selected.length >= PREFERENCE_CATEGORIES_MAX) {
        flashLimitHit(key);
        return;
      }
      next = [...selected, key];
      action = "select";
    }
    app.updateUserProfile({ preferred_categories: next });
    track("account.preferred_categories_toggled", {
      category: key,
      action,
      selected_count_after: next.length,
      selected_categories_after: next,
    });
  };

  return (
    <div className="notif-categories">
      <h3 className="account-subhead">
        {t("account.notif.pref_cat.heading", app.locale)}
      </h3>
      <p className="notif-categories-intro">
        {t("account.notif.pref_cat.intro", app.locale)}
      </p>
      <div className="chip-grid notif-categories-grid" role="group"
           aria-label={t("account.notif.pref_cat.heading", app.locale)}>
        {PREFERENCE_CATEGORY_KEYS.map((key) => {
          const isSelected = selected.includes(key);
          return (
            <button
              key={key}
              type="button"
              role="switch"
              aria-checked={isSelected}
              data-category-key={key}
              className={`chip ${isSelected ? "is-active" : ""}`}
              onClick={() => onToggle(key)}
            >
              {t(PREFERENCE_CATEGORY_LABEL_KEY[key], app.locale)}
            </button>
          );
        })}
      </div>
      {limitHit && (
        <div className="notif-categories-limit" role="status" aria-live="polite">
          {t("account.notif.pref_cat.limit_hint", app.locale, {
            max: PREFERENCE_CATEGORIES_MAX,
          })}
        </div>
      )}
    </div>
  );
}

function Toggle({ checked, onChange, ariaLabel }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      className={`toggle ${checked ? "on" : ""}`}
      onClick={() => onChange(!checked)}
    >
      <span className="toggle-knob"/>
    </button>
  );
}

// ============== A.3.3 — Manage Subscription ==============
function SubscriptionSection({ app }) {
  // Mock subscription state — in prod this comes from Stripe / billing service.
  const plan = app.user.plan || "free";
  const status = "active"; // 'active' | 'paused' | 'payment_issue'

  const isPaid = plan !== "free";

  // Open the Stripe Customer Portal — Stripe owns the invoice list,
  // so we hand off rather than render fabricated rows that drift out
  // of date the moment the user actually pays.
  const onOpenInvoices = () => {
    openStripePortal({
      onError: (code) => {
        if (code === "sign_in_required") {
          app.showToast(t("plans.checkout_auth_mismatch", app.locale));
        } else if (code === "no_customer") {
          app.showToast(t("account.sub.portal_no_customer", app.locale));
        } else {
          app.showToast(t("account.sub.portal_error", app.locale));
        }
      },
    });
  };

  return (
    <div className="account-section">
      <p className="section-intro">{t("account.sub.intro", app.locale)}</p>

      {/* Block 1 — Active plan */}
      <div className="sub-block">
        <div className="sub-plan-head">
          <div>
            <div className="sub-plan-name">{isPaid ? "Pulpo Monthly" : "Free"}</div>
            <div className="sub-plan-meta">
              {isPaid ? "Renews on 5 Jun 2026" : "Browse the catalogue, no card required."}
            </div>
          </div>
          <span className={`status-pill status-${status}`}>
            {status === "active" ? "Active" : status === "paused" ? "Paused" : "Payment issue"}
          </span>
        </div>
        <div className="sub-plan-status-copy">
          {isPaid
            ? "Your plan is active — renews on 5 Jun 2026."
            : "You're on the free plan. Upgrade for off-market access and weekly alerts."}
        </div>
        <div className="sub-plan-actions">
          {isPaid ? (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                openStripePortal({
                  onError: (code) => {
                    if (code === "sign_in_required") {
                      // Cookie / session mismatch — show the same auth-
                      // mismatch toast we use for the upgrade flow.
                      app.showToast(t("plans.checkout_auth_mismatch", app.locale));
                    } else if (code === "no_customer") {
                      // Pro user without a stripeCustomerId on file —
                      // metadata out of sync, point them at support.
                      app.showToast(t("account.sub.portal_no_customer", app.locale));
                    } else {
                      app.showToast(t("account.sub.portal_error", app.locale));
                    }
                  },
                });
              }}
            >{t("account.sub.manage_plan", app.locale)}</button>
          ) : (
            <button
              className="btn-primary"
              onClick={() => {
                // Stripe Managed Payments redirect. Server creates a
                // Checkout Session for the signed-in Clerk user and
                // returns the hosted URL. On error we fall back to the
                // legacy "see plans" route so the button always does
                // *something* meaningful.
                startStripeCheckout({
                  onError: (code) => {
                    if (code === "sign_in_required") {
                      if (app.user) {
                        // Server says no auth but the client has a
                        // user — Clerk cookie / session mismatch.
                        // Don't loop the modal; surface a real toast
                        // and let the user retry.
                        app.showToast(t("plans.checkout_auth_mismatch", app.locale));
                      } else {
                        // Genuinely anonymous (rare on Account, but
                        // possible if the session expired). Open the
                        // signup modal and chain via pendingAction.
                        app.openSignup({ mode: "signup", pendingAction: "checkout" });
                      }
                    } else {
                      app.go("plans");
                    }
                  },
                });
              }}
            >{t("common.upgrade_to_pro_cta", app.locale)}</button>
          )}
        </div>
      </div>

      {/* Block 2 — Invoices (handed off to Stripe Customer Portal) */}
      <div className="sub-divider" />
      <h3 className="account-subhead">{t("account.sub.invoices_heading", app.locale)}</h3>
      {isPaid ? (
        <p className="section-intro">
          {t("account.sub.invoices_intro", app.locale)}{" "}
          <button type="button" className="link-btn" onClick={onOpenInvoices}>
            {t("account.sub.invoices_cta", app.locale)}
          </button>
        </p>
      ) : (
        <div className="orders-empty">
          {t("account.sub.invoices_empty", app.locale)}
        </div>
      )}

      {/* Block 3 — Quiet help nudge */}
      <p className="sub-nudge">
        <button className="link-btn" onClick={() => app.go("home")}>
          {t("account.sub.discover_nudge", app.locale)}
        </button>
      </p>
    </div>
  );
}

// ============== A.3.4 — Security ==============
function SecuritySection({ app }) {
  // When Clerk is the auth source of truth, password / sessions /
  // connected accounts / 2FA / account-deletion are all managed
  // server-side by Clerk. Mounting our own password form would be
  // dead UI: it would call setTimeout and a fake "Password updated."
  // toast without ever touching the auth provider. Hand off to
  // Clerk's hosted UserProfile modal — it covers every action a
  // user could want here, in one consistent UI.
  //
  // Fall back to the legacy stub form only when Clerk isn't
  // configured (CI, fresh clones, e2e dev server without a Clerk
  // publishable key). The legacy form also doesn't actually change
  // a password — it never did — but it gives shape to the section
  // for the non-Clerk dev path.
  const clerkOn = clerkEnabled();
  const clerkReady = clerkOn && app.clerkActions;

  if (clerkOn) {
    return <ClerkSecuritySection app={app} clerkReady={clerkReady} />;
  }
  return <LegacySecuritySection app={app} />;
}

// Clerk-on path: a single CTA opens the hosted UserProfile modal.
// Sign-out stays as a top-level button for parity with the legacy
// path (Clerk's UserProfile has its own sign-out, but a one-click
// shortcut here is friendlier).
function ClerkSecuritySection({ app, clerkReady }) {
  const openProfile = () => {
    if (!clerkReady) return;
    try {
      app.clerkActions.openUserProfile();
    } catch (err) {
      if (typeof console !== "undefined" && console.warn) {
        console.warn("[pulpo] clerk.openUserProfile failed:", err);
      }
      app.showToast(t("account.security.clerk.error", app.locale));
    }
  };

  const onSignout = () => {
    app.signout();
    app.go("home");
  };

  return (
    <div className="account-section">
      <h3 className="account-subhead">{t("account.security.clerk.heading", app.locale)}</h3>
      <p className="section-intro">{t("account.security.clerk.intro", app.locale)}</p>
      <ul className="security-clerk-list">
        <li>{t("account.security.clerk.feat.password", app.locale)}</li>
        <li>{t("account.security.clerk.feat.sessions", app.locale)}</li>
        <li>{t("account.security.clerk.feat.mfa", app.locale)}</li>
        <li>{t("account.security.clerk.feat.connected", app.locale)}</li>
        <li>{t("account.security.clerk.feat.delete", app.locale)}</li>
      </ul>
      <div className="account-save-row">
        <button
          type="button"
          className="btn-primary"
          onClick={openProfile}
          disabled={!clerkReady}
          aria-busy={!clerkReady}
        >
          {clerkReady
            ? t("account.security.clerk.cta", app.locale)
            : t("account.security.clerk.loading", app.locale)}
        </button>
      </div>

      <div className="sub-divider"/>
      <h3 className="account-subhead">{t("account.security.signout.heading", app.locale)}</h3>
      <p className="section-intro">{t("account.security.signout.intro", app.locale)}</p>
      <button
        className="btn-ghost"
        onClick={onSignout}
        disabled={app.isSigningOut}
        aria-busy={app.isSigningOut || undefined}
      >
        {t("account.security.signout.cta", app.locale)}
      </button>
    </div>
  );
}

// Legacy path — only mounts when Clerk isn't configured (no
// publishable key). Doesn't touch a real auth provider; preserved
// so the Account page still renders something in dev/CI without
// Clerk credentials.
function LegacySecuritySection({ app }) {
  const [pwd, setPwd] = aUseState({ current: "", next: "", confirm: "" });
  const [pwdMsg, setPwdMsg] = aUseState("");
  const [showSignoutModal, setShowSignoutModal] = aUseState(false);
  const [showDeleteModal, setShowDeleteModal] = aUseState(false);
  const [deleteText, setDeleteText] = aUseState("");

  const matches = pwd.next.length >= 6 && pwd.next === pwd.confirm;
  const canSubmit = pwd.current && pwd.next && matches;

  return (
    <div className="account-section">
      <h3 className="account-subhead">Password</h3>
      <form
        className="security-form"
        onSubmit={(e) => {
          e.preventDefault();
          if (!canSubmit) return;
          setPwd({ current: "", next: "", confirm: "" });
          setPwdMsg("Password updated.");
          setTimeout(() => setPwdMsg(""), 3000);
        }}
      >
        <FieldRow label="Current password">
          <input
            type="password"
            value={pwd.current}
            onChange={(e) => setPwd(p => ({ ...p, current: e.target.value }))}
          />
        </FieldRow>
        <FieldRow label="New password" hint={pwd.next ? (pwd.next.length < 6 ? "Must be at least 6 characters." : "Looks good.") : null}>
          <input
            type="password"
            value={pwd.next}
            onChange={(e) => setPwd(p => ({ ...p, next: e.target.value }))}
          />
        </FieldRow>
        <FieldRow label="Confirm new password" hint={pwd.confirm && !matches ? "Doesn't match." : null}>
          <input
            type="password"
            value={pwd.confirm}
            onChange={(e) => setPwd(p => ({ ...p, confirm: e.target.value }))}
          />
        </FieldRow>
        <div className="account-save-row">
          <button type="submit" className="btn-primary" disabled={!canSubmit}>Update password</button>
        </div>
        {pwdMsg && <div className="account-inline-confirm">{pwdMsg}</div>}
      </form>

      <div className="sub-divider"/>
      <h3 className="account-subhead">Sign out</h3>
      <p className="section-intro">Sign out of all devices you're currently logged in on.</p>
      <button className="btn-ghost" onClick={() => setShowSignoutModal(true)}>
        Sign out of all devices
      </button>

      <div className="sub-divider"/>
      <h3 className="account-subhead destructive">Delete account</h3>
      <p className="section-intro">Permanently delete your account and saved listings. This cannot be undone.</p>
      <button className="link-btn destructive-link" onClick={() => setShowDeleteModal(true)}>
        Delete my account
      </button>

      {showSignoutModal && (
        <ConfirmModal
          title="Sign out of all devices?"  /* i18n-allow: LegacySecuritySection only renders when Clerk is OFF (no VITE_CLERK_PUBLISHABLE_KEY) — tracked for full i18n in legacy-cleanup PR */
          body="This will sign you out everywhere. You'll need to log in again on each device."
          confirmLabel="Sign out everywhere"
          onConfirm={() => { setShowSignoutModal(false); app.signout(); app.go("home"); }}
          onCancel={() => setShowSignoutModal(false)}
        />
      )}

      {showDeleteModal && (
        <ConfirmModal
          title="Delete your account?"  /* i18n-allow: LegacySecuritySection — see signout dialog above */
          body="This removes your profile, saved listings, and notification preferences. To confirm, type DELETE below."
          destructive
          confirmLabel="Delete account"
          confirmDisabled={deleteText !== "DELETE"}
          extra={
            <input
              type="text"
              className="confirm-input"
              placeholder="Type DELETE to confirm"  /* i18n-allow: LegacySecuritySection — see signout dialog above */
              value={deleteText}
              onChange={(e) => setDeleteText(e.target.value)}
            />
          }
          onConfirm={() => { setShowDeleteModal(false); app.showToast("Request received — we'll be in touch."); }}
          onCancel={() => { setShowDeleteModal(false); setDeleteText(""); }}
        />
      )}
    </div>
  );
}

function ConfirmModal({ title, body, confirmLabel, onConfirm, onCancel, destructive, confirmDisabled, extra }) {
  return (
    <div className="modal-backdrop" onClick={onCancel}>
      <div className="modal modal-confirm" onClick={(e) => e.stopPropagation()}>
        <h2 className="confirm-title">{title}</h2>
        <p className="confirm-body">{body}</p>
        {extra}
        <div className="confirm-actions">
          <button className="btn-ghost" onClick={onCancel}>Cancel</button>
          <button
            className={`btn-primary ${destructive ? "destructive" : ""}`}
            disabled={confirmDisabled}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export { AccountPage };
