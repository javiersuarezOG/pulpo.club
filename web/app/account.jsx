// Pulpo — Account area (A.3 from PRD addendum).
// Two-column layout: left-nav (sub-sections) + right content. Mobile: stacks.
// Subsections: Profile, Notifications, Manage Subscription, Security (stub).
// Uses same design tokens as the rest of the app — no special chrome.
import React, { useState as aUseState, useEffect as aUseEffect, useMemo as aUseMemo } from "react";
import { t, tr } from "./i18n.jsx";
import { Icon, PulpoLogo, formatPrice, currentLocale } from "./components.jsx";
import { startStripeCheckout } from "./auth/stripe-checkout.js";

function AccountPage({ app }) {
  const [section, setSection] = aUseState(() => app.routeParams.section || "profile");

  // Resync if route params change (e.g. nav from a deep link)
  aUseEffect(() => {
    if (app.routeParams.section && app.routeParams.section !== section) {
      setSection(app.routeParams.section);
    }
  }, [app.routeParams.section]);

  const subs = [
    { key: "profile",       label: t("account.profile", app.locale),       icon: "user" },
    { key: "notifications", label: t("account.notifications", app.locale), icon: "bell" },
    { key: "subscription",  label: t("account.subscription", app.locale),  icon: "sparkle" },
    { key: "security",      label: t("account.security", app.locale),      icon: "lock" },
  ];

  // If user isn't signed in, send them to sign-up. The Account area is auth-only.
  if (!app.user) {
    aUseEffect(() => {
      app.openSignup({ mode: "login" });
      app.go("home");
    }, []);
    return null;
  }

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
        <select
          value={values.country}
          onChange={(e) => setValues(v => ({ ...v, country: e.target.value }))}
        >
          <option value="SV">El Salvador</option>
          <option value="CR">Costa Rica</option>
          <option value="MX">Mexico</option>
          <option value="US">United States</option>
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

  const cats = [
    { key: "newsletter",       title: "Weekly newsletter",        desc: "The main Pulpo digest — new listings, price drops, curated picks." },
    { key: "price_drops",      title: "Price drop alerts",        desc: "Email when a saved listing drops in price." },
    { key: "new_in_zones",     title: "New listings in saved zones", desc: "Get early notice when something new appears in areas you've explored." },
    { key: "platform_updates", title: "Platform updates",         desc: "Occasional product news and feature announcements." },
  ];

  return (
    <div className="account-section">
      <p className="section-intro">{t("account.notif.intro", app.locale)}</p>

      <div className="pref-list">
        {cats.map(c => (
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

      <h3 className="account-subhead">Channels</h3>
      <div className="pref-list">
        <div className="pref-row">
          <div className="pref-text">
            <div className="pref-title">Email</div>
            <div className="pref-desc">Always on — primary product delivery channel.</div>
          </div>
          <span className="pref-locked">Required</span>
        </div>
        <div className="pref-row">
          <div className="pref-text">
            <div className="pref-title">WhatsApp</div>
            <div className="pref-desc">Optional opt-in. Stores your number for future deal alerts.</div>
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
                We'll send deal alerts to {prefs.whatsapp_number}. You can opt out anytime.
              </div>
            )}
          </div>
          <Toggle
            checked={prefs.whatsapp}
            onChange={v => setKey("whatsapp", v)}
            ariaLabel="WhatsApp"
          />
        </div>
      </div>

      {prefs.newsletter && (
        <>
          <h3 className="account-subhead">Newsletter frequency</h3>
          <div className="freq-toggle">
            {["weekly","biweekly"].map(f => (
              <button
                key={f}
                type="button"
                className={prefs.frequency === f ? "active" : ""}
                onClick={() => setKey("frequency", f)}
              >
                {f === "weekly" ? "Weekly" : "Bi-weekly"}
              </button>
            ))}
          </div>
        </>
      )}

      {confirm && <div className="account-inline-confirm">{t("account.notif.saved", app.locale)}</div>}

      <p className="unsub-note">
        You can also unsubscribe from any email using the link at the bottom of each message.
      </p>
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
    { date: "5 May 2026",   desc: "Pulpo Monthly — May 2026",   status: "paid",    amount: "$10.00" },
    { date: "5 Apr 2026",   desc: "Pulpo Monthly — Apr 2026",   status: "paid",    amount: "$10.00" },
    { date: "5 Mar 2026",   desc: "Pulpo Monthly — Mar 2026",   status: "paid",    amount: "$10.00" },
    { date: "5 Feb 2026",   desc: "Pulpo Monthly — Feb 2026",   status: "paid",    amount: "$10.00" },
    { date: "5 Jan 2026",   desc: "Pulpo Monthly — Jan 2026",   status: "paid",    amount: "$10.00" },
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
            <a className="link-btn">Manage plan →</a>
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
                      app.openSignup({ mode: "signup" });
                    } else {
                      app.go("plans");
                    }
                  },
                });
              }}
            >Upgrade to Pro</button>
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

// ============== A.3.4 — Security (stub) ==============
function SecuritySection({ app }) {
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
