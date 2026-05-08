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

function AccountPage({ app }) {
  const [section, setSection] = aUseState(() => app.routeParams.section || "profile");

  // Resync if route params change (e.g. nav from a deep link)
  aUseEffect(() => {
    if (app.routeParams.section && app.routeParams.section !== section) {
      setSection(app.routeParams.section);
    }
  }, [app.routeParams.section]);

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
  aUseEffect(() => {
    if (clerkBooting) return;
    if (app.user) return;
    app.openSignup({ mode: "login" });
    app.go("home");
  }, [clerkBooting, app.user]);

  if (clerkBooting) {
    return <div className="page page-account account-loading" aria-busy="true" />;
  }
  if (!app.user) return null;

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
                  onClick={() => setSection(s.key)}
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
          <button type="button" className="link-btn">Upload photo</button>
        </div>
      </div>

      <FieldRow label={t("account.profile.name", app.locale)}>
        <input
          type="text"
          value={values.name}
          placeholder="Your name"
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
        {/* Full ISO 3166-1 list — Pulpo's user base isn't restricted
            to the previous 4-country whitelist. The select still
            supports type-ahead (browser native) so finding a country
            in a long list is fast. */}
        <select
          value={values.country}
          onChange={(e) => setValues(v => ({ ...v, country: e.target.value }))}
        >
          {COUNTRIES.map(c => (
            <option key={c.code} value={c.code}>{c.name}</option>
          ))}
        </select>
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

  const proCats = [
    { key: "newsletter",   title: t("account.notif.newsletter.title",   app.locale), desc: t("account.notif.newsletter.desc",   app.locale) },
    { key: "price_drops",  title: t("account.notif.price_drops.title",  app.locale), desc: t("account.notif.price_drops.desc",  app.locale) },
    { key: "new_in_zones", title: t("account.notif.new_in_zones.title", app.locale), desc: t("account.notif.new_in_zones.desc", app.locale) },
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

      <h3 className="account-subhead">{t("account.notif.channels", app.locale)}</h3>
      <div className="pref-list">
        <div className="pref-row">
          <div className="pref-text">
            <div className="pref-title">{t("account.notif.email", app.locale)}</div>
            <div className="pref-desc">{t("account.notif.email_desc", app.locale)}</div>
          </div>
          <span className="pref-locked">{t("account.notif.required", app.locale)}</span>
        </div>
        {isPaid && (
          <div className="pref-row">
            <div className="pref-text">
              <div className="pref-title">{t("account.notif.whatsapp", app.locale)}</div>
              <div className="pref-desc">{t("account.notif.whatsapp_desc", app.locale)}</div>
              {prefs.whatsapp && (
                <input
                  type="tel"
                  className="pref-inline-input"
                  placeholder="+503 7000 0000"
                  value={prefs.whatsapp_number}
                  onChange={(e) => setPrefs(p => ({ ...p, whatsapp_number: e.target.value }))}
                />
              )}
              {prefs.whatsapp && prefs.whatsapp_number && (
                <div className="pref-confirm">
                  {t("account.notif.whatsapp_confirm", app.locale, { number: prefs.whatsapp_number })}
                </div>
              )}
            </div>
            <Toggle
              checked={prefs.whatsapp}
              onChange={v => setKey("whatsapp", v)}
              ariaLabel={t("account.notif.whatsapp", app.locale)}
            />
          </div>
        )}
      </div>

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
          <li>{t("account.notif.newsletter.title", app.locale)}</li>
          <li>{t("account.notif.price_drops.title", app.locale)}</li>
          <li>{t("account.notif.new_in_zones.title", app.locale)}</li>
        </ul>
        <button className="btn-primary" onClick={onUpgrade}>
          {t("account.notif.upsell.cta", app.locale)}
        </button>
      </div>
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

  const orders = [
    { date: "5 May 2026",   desc: "Pulpo Monthly — May 2026",   status: "paid",    amount: "€10.00" },
    { date: "5 Apr 2026",   desc: "Pulpo Monthly — Apr 2026",   status: "paid",    amount: "€10.00" },
    { date: "5 Mar 2026",   desc: "Pulpo Monthly — Mar 2026",   status: "paid",    amount: "€10.00" },
    { date: "5 Feb 2026",   desc: "Pulpo Monthly — Feb 2026",   status: "paid",    amount: "€10.00" },
    { date: "5 Jan 2026",   desc: "Pulpo Monthly — Jan 2026",   status: "paid",    amount: "€10.00" },
  ];

  const isPaid = plan !== "free";

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

      {/* Block 2 — Order history */}
      <div className="sub-divider" />
      <h3 className="account-subhead">Order history</h3>
      {isPaid ? (
        <>
          <div className="orders-table-wrap">
            <table className="orders-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Description</th>
                  <th>Status</th>
                  <th className="num">Amount</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((o, i) => (
                  <tr key={i}>
                    <td>{o.date}</td>
                    <td>{o.desc}</td>
                    <td>
                      <span className={`status-pill status-${o.status === "paid" ? "active" : o.status === "failed" ? "payment_issue" : "paused"}`}>
                        {o.status === "paid" ? "Paid" : o.status === "failed" ? "Payment Failed" : "Pending"}
                      </span>
                    </td>
                    <td className="num">{o.amount}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {/* Mobile cards */}
          <div className="orders-cards">
            {orders.map((o, i) => (
              <div className="order-card" key={i}>
                <div className="order-card-line1">
                  <span>{o.date}</span>
                  <span>{o.desc}</span>
                </div>
                <div className="order-card-line2">
                  <span className={`status-pill status-active`}>Paid</span>
                  <span className="num">{o.amount}</span>
                </div>
              </div>
            ))}
          </div>
        </>
      ) : (
        <div className="orders-empty">
          No orders yet. Your billing history will appear here once your first payment is processed.
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
      <button className="btn-ghost" onClick={onSignout}>
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
          title="Sign out of all devices?"
          body="This will sign you out everywhere. You'll need to log in again on each device."
          confirmLabel="Sign out everywhere"
          onConfirm={() => { setShowSignoutModal(false); app.signout(); app.go("home"); }}
          onCancel={() => setShowSignoutModal(false)}
        />
      )}

      {showDeleteModal && (
        <ConfirmModal
          title="Delete your account?"
          body="This removes your profile, saved listings, and notification preferences. To confirm, type DELETE below."
          destructive
          confirmLabel="Delete account"
          confirmDisabled={deleteText !== "DELETE"}
          extra={
            <input
              type="text"
              className="confirm-input"
              placeholder="Type DELETE to confirm"
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
