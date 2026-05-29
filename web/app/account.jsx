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
import {
  readProfile,
  readNewsletterPreference,
  NEWSLETTER_CADENCES,
  NEWSLETTER_LOCALES,
  NEWSLETTER_PROPERTY_TYPES,
} from "./lib/user-profile";
import { splitFullName, joinFullName } from "./lib/name-split";
import { routeCtaForState, trackCtaRouted, dispatchCentralBranch } from "./lib/cta-routing";
import { readFeatureFlag } from "./lib/feature-flag";
import { deriveSubscriptionState, graceDaysLeft } from "./lib/subscription";
import {
  pollPortalReturnState,
  subscriptionRefreshSnapshot,
} from "./lib/portal-return-refresh";

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
    // /account?welcome=1 bypass — symmetric with the page-render
    // branch below. Without this, an anonymous post-Stripe landing
    // would trigger the SignupModal on top of the WelcomeModal,
    // which is the Sebas-2026-05-19 bug.
    //
    // Consume welcomeModalState from the app bag rather than re-reading
    // window.location.search. The parent (app.jsx) initializes
    // welcomeModalState SYNCHRONOUSLY from URL via useState's
    // initializer and then strips ?welcome=1 from the URL in a
    // separate effect. When Clerk is ON in prod, this auth-gate effect
    // returns early on its first mount (clerkBooting=true) and re-fires
    // only AFTER the URL has been stripped — so a live URL read here
    // would always see the stripped URL and fail the bypass, popping
    // SignupModal on top of WelcomeModal. welcomeModalState survives
    // the strip and is the correct source of truth.
    if (app.welcomeModalState) return;
    // Activation-ticket landing — app.jsx's clerkTicketHandledRef
    // effect opens Clerk's hosted SignUp modal directly. Don't open
    // our SignupModal in parallel; SignupModal calls clerk.openSignIn
    // when mode==="login", which stacks a second Clerk portal on top
    // of the SignUp one — the 2026-05-20 double-modal / infinite-
    // spinner bug. Symmetric with the welcomeModalState bypass above.
    // Re-read URL here because hasClerkTicket lives on App, not the
    // page; same pattern as the route-gates.ts welcome=1 bypass.
    if (typeof window !== "undefined" &&
        new URLSearchParams(window.location.search).has("__clerk_ticket")) {
      return;
    }
    // Pending invitation sign-up takes priority — app.jsx's dedicated
    // effect opens clerk.openSignUp() for password creation. Don't
    // stack our SignupModal on top; see 2026-05-20 post-activation
    // flow bug.
    if (app.clerkActions && typeof app.clerkActions.pendingSignUp === "function" && app.clerkActions.pendingSignUp()) return;
    app.openSignup({ mode: "login" });
  }, [clerkBooting, app.user, app.welcomeModalState, app.clerkActions]);

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
    // Same source of truth as the auth-gate effect above. URL re-read
    // would race the welcome-effect URL strip and miss the placeholder
    // in production (Clerk-ON), leaving the WelcomeModal floating over
    // a `return null` empty page instead of the loading shell.
    if (app.welcomeModalState) {
      return <div className="page page-account account-welcome-preview" aria-busy="true" />;
    }
    // Activation-ticket landing — Clerk's hosted SignUp modal is
    // opening on top of this page. Render a neutral placeholder rather
    // than null so closing the Clerk modal doesn't leave the user
    // staring at a blank viewport. Symmetric with the welcome-preview
    // branch above. URL re-read is safe here — the auth-gate effect
    // above also re-reads, and __clerk_ticket survives until Clerk's
    // SDK consumes it (no app-side URL strip).
    if (typeof window !== "undefined" &&
        new URLSearchParams(window.location.search).has("__clerk_ticket")) {
      return <div className="page page-account account-welcome-preview" aria-busy="true" />;
    }
    return null;
  }

  // 2026-05-29: renamed `notifications` → `newsletter`. The tab always
  // managed the newsletter filter; ACCOUNT_SECTION_KEYS aliases the old
  // slug in url-routing.ts so existing bookmarks survive.
  const subs = [
    { key: "profile",      label: t("account.profile", app.locale),      icon: "user" },
    { key: "newsletter",   label: t("account.newsletter", app.locale),   icon: "bell" },
    { key: "subscription", label: t("account.subscription", app.locale), icon: "sparkle" },
    { key: "security",     label: t("account.security", app.locale),     icon: "lock" },
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
          {section === "profile"      && <ProfileSection app={app} />}
          {section === "newsletter"   && <NotificationsSection app={app} />}
          {section === "subscription" && <SubscriptionSection app={app} />}
          {section === "security"     && <SecuritySection app={app} />}
        </main>
      </div>
    </div>
  );
}

// ============== A.3.1 — Profile ==============
// Wires the four real persistence surfaces:
//   • firstName / lastName  →  Clerk SDK  (clerk.user.update)
//   • imageUrl              →  Clerk SDK  (clerk.user.setProfileImage)
//   • country / language    →  /api/clerk/update-profile  (publicMetadata.profile)
// Every visible control has a downstream consumer — see CLAUDE.md
// "NEVER ship a UI control that lies about persistence".
const PHOTO_MAX_BYTES = 2 * 1024 * 1024; // 2 MB
const PHOTO_MIME_ALLOWED = new Set(["image/jpeg", "image/png", "image/webp"]);

function ProfileSection({ app }) {
  const profile = readProfile(app.user);
  const initial = aUseMemo(() => ({
    firstName: app.user.firstName || app.user.name || "",
    lastName: app.user.lastName || "",
    // Country starts empty when the user hasn't explicitly picked one.
    // The previous default (ACTIVE_COUNTRY.code, "SV" on pulpo.club)
    // pre-filled the field with El Salvador for every Mexican / Costa
    // Rican / Argentinian user who'd never told us where they were —
    // misleading and Sebas's call to drop. Empty = "not set"; save
    // path skips the country leg when the field is empty.
    country: (typeof profile.country === "string" && profile.country) || "",
    language: (typeof profile.language === "string" && profile.language) || app.locale,
  }), [app.user.firstName, app.user.lastName, app.user.name, profile.country, profile.language, app.locale]);

  const [fullName, setFullName] = aUseState(() => joinFullName(initial));
  const [country, setCountry] = aUseState(initial.country);
  const [language, setLanguage] = aUseState(initial.language);
  const [saving, setSaving] = aUseState(false);
  const [saved, setSaved] = aUseState(false);
  const [uploading, setUploading] = aUseState(false);
  const fileRef = React.useRef(null);

  // Re-sync local form when Clerk hydration changes the underlying user.
  // Without this, the form keeps stale values after a successful save +
  // ClerkUserSync re-render.
  aUseEffect(() => {
    setFullName(joinFullName(initial));
    setCountry(initial.country);
    setLanguage(initial.language);
  }, [initial]);

  const { firstName, lastName } = splitFullName(fullName);
  const dirty =
    firstName !== initial.firstName ||
    lastName !== initial.lastName ||
    country !== initial.country ||
    language !== initial.language;

  const flashSaved = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  const onSave = async (e) => {
    e.preventDefault();
    if (!dirty || saving) return;
    const identityDirty = firstName !== initial.firstName || lastName !== initial.lastName;
    const metadataDirty = country !== initial.country || language !== initial.language;
    const dirtyKeys = [];
    if (identityDirty) dirtyKeys.push("identity");
    if (country !== initial.country) dirtyKeys.push("country");
    if (language !== initial.language) dirtyKeys.push("language");
    const keys = dirtyKeys.join(",");
    track("account.profile_save_started", { keys });

    // No-consumer guard. If we got here with identity changes but no
    // Clerk action wired, we're about to silently swallow the user's
    // save. Emit a dedicated event so the regression is visible in
    // telemetry instead of disappearing into local state.
    if (identityDirty && !(app.clerkActions && typeof app.clerkActions.updateIdentity === "function")) {
      track("account.profile_save_no_consumer", { keys });
      app.showToast(t("account.profile.sync_failed", app.locale));
      return;
    }

    setSaving(true);
    const startedAt = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    let ok = true;

    // 1. Identity (firstName / lastName) → Clerk SDK direct write.
    if (identityDirty) {
      try {
        await app.clerkActions.updateIdentity({ firstName, lastName });
      } catch (err) {
        ok = false;
        const elapsed_ms = Math.max(0, Math.round(
          ((typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now()) - startedAt,
        ));
        track("account.profile_save_failed", {
          keys,
          reason: (err && err.code) || (err && err.message) || "unknown",
          status: (err && err.status) || 0,
          elapsed_ms,
        });
        // Keep the legacy event firing too — existing dashboards depend
        // on it. The new _save_failed is the structured replacement.
        track("account.profile_sync_failed", {
          keys: "identity",
          reason: (err && err.code) || (err && err.message) || "unknown",
          status: (err && err.status) || 0,
        });
        app.showToast(t("account.profile.sync_failed", app.locale));
      }
    }

    // 2. Profile metadata (country / language) → /api/clerk/update-profile
    // via the existing optimistic+rollback path. Fire-and-forget from
    // here — rollback toast + profile_sync_failed live inside
    // updateUserProfile already.
    if (ok && metadataDirty) {
      const patch = {};
      // Empty country = the user cleared the picker; don't write empty
      // strings to Clerk — the backend allowlist regex rejects them
      // (^[A-Z]{2}$). Only persist actual selections. If a user wants
      // to remove their saved country we'd need a separate delete path;
      // skipping is fine for the v1 use case where "I picked the wrong
      // country" is just "pick the right one and save."
      if (country !== initial.country && country) patch.country = country;
      if (language !== initial.language) patch.language = language;
      if (Object.keys(patch).length > 0) app.updateUserProfile(patch);
      // Reflect language locally before the round-trip resolves so the
      // page chrome flips immediately.
      if (language !== initial.language) app.setLocale(language);
    }
    setSaving(false);
    if (ok) {
      const elapsed_ms = Math.max(0, Math.round(
        ((typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now()) - startedAt,
      ));
      track("account.profile_save_succeeded", { keys, elapsed_ms });
      flashSaved();
    }
  };

  const onUploadClick = () => {
    if (uploading) return;
    if (fileRef.current) fileRef.current.value = ""; // allow re-picking the same file
    if (fileRef.current) fileRef.current.click();
  };

  const onFileChange = async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    const size_kb = Math.round(file.size / 1024);
    const mime = file.type || "unknown";
    if (!PHOTO_MIME_ALLOWED.has(file.type)) {
      track("account.profile_photo_upload_rejected", { reason: "wrong_type", size_kb, mime });
      app.showToast(t("account.profile.upload_wrong_type", app.locale));
      return;
    }
    if (file.size > PHOTO_MAX_BYTES) {
      track("account.profile_photo_upload_rejected", { reason: "too_big", size_kb, mime });
      app.showToast(t("account.profile.upload_too_big", app.locale));
      return;
    }
    if (!(app.clerkActions && typeof app.clerkActions.setProfileImage === "function")) {
      track("account.profile_save_no_consumer", { keys: "imageUrl" });
      app.showToast(t("account.profile.upload_failed", app.locale));
      return;
    }
    track("account.profile_photo_upload_started", { mime, size_kb });
    setUploading(true);
    const startedAt = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    try {
      await app.clerkActions.setProfileImage(file);
      const elapsed_ms = Math.max(0, Math.round(
        ((typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now()) - startedAt,
      ));
      track("account.profile_photo_upload_succeeded", { elapsed_ms });
    } catch (err) {
      const elapsed_ms = Math.max(0, Math.round(
        ((typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now()) - startedAt,
      ));
      track("account.profile_photo_upload_failed", {
        reason: (err && err.code) || (err && err.message) || "unknown",
        status: (err && err.status) || 0,
        elapsed_ms,
      });
      track("account.profile_sync_failed", {
        keys: "imageUrl",
        reason: (err && err.code) || (err && err.message) || "unknown",
        status: (err && err.status) || 0,
      });
      app.showToast(t("account.profile.upload_failed", app.locale));
    } finally {
      setUploading(false);
    }
  };

  const onRemovePhoto = async () => {
    if (uploading) return;
    if (!(app.clerkActions && typeof app.clerkActions.setProfileImage === "function")) {
      track("account.profile_save_no_consumer", { keys: "imageUrl_remove" });
      return;
    }
    track("account.profile_photo_removed", {});
    setUploading(true);
    try {
      await app.clerkActions.setProfileImage(null);
    } catch (err) {
      track("account.profile_sync_failed", {
        keys: "imageUrl_remove",
        reason: (err && err.code) || (err && err.message) || "unknown",
        status: (err && err.status) || 0,
      });
      app.showToast(t("account.profile.upload_failed", app.locale));
    } finally {
      setUploading(false);
    }
  };

  const onOpenSecurity = () => {
    track("account.profile_email_change_clicked", {});
    if (app.clerkActions && typeof app.clerkActions.openUserProfile === "function") {
      app.clerkActions.openUserProfile();
    } else {
      app.go("account", { section: "security" });
    }
  };

  const initials = ((fullName || app.user.email || "?").trim()[0] || "?").toUpperCase();
  const imageUrl = app.user.imageUrl || "";
  const hasImage = !!imageUrl;

  return (
    <form className="account-section" onSubmit={onSave}>
      <div className="profile-photo-row">
        <div className="profile-avatar" aria-busy={uploading || undefined}>
          {hasImage
            ? <img src={imageUrl} alt="" />
            : <span aria-hidden="true">{initials}</span>}
        </div>
        <div className="profile-photo-actions">
          <div className="profile-photo-label">{t("account.profile.photo", app.locale)}</div>
          <button
            type="button"
            className="link-btn"
            onClick={onUploadClick}
            disabled={uploading}
            aria-busy={uploading || undefined}
          >
            {uploading
              ? t("account.profile.uploading", app.locale)
              : t("account.profile.upload_photo", app.locale)}
          </button>
          {hasImage && !uploading && (
            <button
              type="button"
              className="link-btn link-btn-muted"
              onClick={onRemovePhoto}
            >
              {t("account.profile.remove_photo", app.locale)}
            </button>
          )}
          <div className="profile-photo-helper">{t("account.profile.upload_helper", app.locale)}</div>
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            onChange={onFileChange}
            aria-hidden="true"
            tabIndex={-1}
          />
        </div>
      </div>

      <FieldRow label={t("account.profile.name", app.locale)}>
        <input
          type="text"
          value={fullName}
          placeholder={t("account.profile.name_placeholder", app.locale)}
          onChange={(e) => setFullName(e.target.value)}
          autoComplete="name"
        />
      </FieldRow>

      <FieldRow
        label={t("account.profile.email", app.locale)}
        hint={t("account.profile.email_note", app.locale)}
      >
        {/* Read-only display — NO <input>. Email change is genuinely
            Clerk's job (verification flow + reachability); we hand the
            user off to Clerk's hosted UserProfile via the inline link. */}
        <div className="field-readonly-row">
          <div className="field-readonly-value">{app.user.email || ""}</div>
          <button type="button" className="link-btn link-btn-muted" onClick={onOpenSecurity}>
            {t("account.profile.email_change_link", app.locale)}
          </button>
        </div>
      </FieldRow>

      <FieldRow label={t("account.profile.country", app.locale)}>
        <CountryCombobox
          value={country}
          onChange={setCountry}
          placeholder={t("account.profile.country_placeholder", app.locale)}
          ariaLabel={t("account.profile.country", app.locale)}
          locale={app.locale}
        />
      </FieldRow>

      <FieldRow label={t("account.profile.lang", app.locale)}>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
        >
          <option value="en">English</option>
          <option value="es">Español</option>
        </select>
      </FieldRow>

      {dirty && (
        <div className="account-save-row">
          <button
            type="submit"
            className="btn-primary"
            disabled={saving}
            aria-busy={saving || undefined}
          >
            {saving
              ? t("account.profile.saving", app.locale)
              : t("account.profile.save", app.locale)}
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

// Country picker — accessible combobox with list autocomplete.
// Replaces the previous `<input list>` + `<datalist>` because the native
// datalist UX is inconsistent across browsers (Safari/macOS in particular
// hides the list until the user types a partial match). This implementation
// follows the WAI-ARIA Authoring Practices "combobox with list autocomplete"
// pattern: arrow keys navigate, Enter selects, Escape closes, click-outside
// dismisses, the list is always visible on focus.
//
// Mobile-first: the dropdown is a real positioned element rather than a
// native picker, so type-to-filter works on touch the same as on desktop.
// 250 rows render OK without virtualization (Chrome devtools puts the
// initial mount under 8ms on an iPhone 12 emulation); revisit if we add
// flags/icons to each row.
function CountryCombobox({ value, onChange, placeholder, ariaLabel, locale }) {
  const codeToName = React.useCallback((code) => {
    const c = COUNTRIES.find((x) => x.code === code);
    return c ? c.name : "";
  }, []);
  const [query, setQuery] = React.useState(() => codeToName(value));
  const [open, setOpen] = React.useState(false);
  const [highlight, setHighlight] = React.useState(0);
  const inputRef = React.useRef(null);
  const listRef = React.useRef(null);
  const containerRef = React.useRef(null);
  const listId = React.useId();

  // Re-sync display when the parent's value flips (e.g. form resets after
  // Clerk hydration). We bind to `value`, not the derived name, so this
  // doesn't trample mid-typing edits.
  React.useEffect(() => {
    setQuery(codeToName(value));
  }, [value, codeToName]);

  // Locale-aware case-insensitive substring match. Accent-insensitive via
  // NFD + diacritic strip so "Mexico" finds "México" and vice versa.
  const norm = React.useCallback((s) => {
    try {
      return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
    } catch {
      return s.toLowerCase();
    }
  }, []);
  const filtered = React.useMemo(() => {
    const q = norm(query.trim());
    if (!q) return COUNTRIES;
    return COUNTRIES.filter((c) => norm(c.name).includes(q));
  }, [query, norm]);

  // Reset highlight whenever the filter changes so arrow-down lands on
  // the first visible row, not an out-of-range index.
  React.useEffect(() => {
    setHighlight(0);
  }, [filtered.length]);

  // Scroll the highlighted option into view as the user navigates with
  // the keyboard. `scrollIntoView({ block: "nearest" })` is the minimal
  // disturbance — it only scrolls when the option is outside the visible
  // window.
  React.useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-idx="${highlight}"]`);
    if (el && typeof el.scrollIntoView === "function") {
      el.scrollIntoView({ block: "nearest" });
    }
  }, [highlight, open]);

  // Close on outside click. Pointerdown over mousedown so iOS Safari's
  // delayed click doesn't race the focus state.
  React.useEffect(() => {
    if (!open) return;
    const onDocPointer = (e) => {
      if (!containerRef.current) return;
      if (!containerRef.current.contains(e.target)) {
        setOpen(false);
        // On dismiss, revert query to the canonical name for `value`
        // so the field never shows a half-typed string after blur.
        setQuery(codeToName(value));
      }
    };
    document.addEventListener("pointerdown", onDocPointer);
    return () => document.removeEventListener("pointerdown", onDocPointer);
  }, [open, value, codeToName]);

  const commit = (code) => {
    onChange(code);
    setQuery(codeToName(code));
    setOpen(false);
    if (inputRef.current) inputRef.current.focus();
  };

  const onKeyDown = (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      setHighlight((h) => Math.min(h + 1, Math.max(0, filtered.length - 1)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (!open) { setOpen(true); return; }
      setHighlight((h) => Math.max(0, h - 1));
    } else if (e.key === "Enter") {
      if (open && filtered[highlight]) {
        e.preventDefault();
        commit(filtered[highlight].code);
      }
    } else if (e.key === "Escape") {
      if (open) {
        e.preventDefault();
        setOpen(false);
        setQuery(codeToName(value));
      }
    } else if (e.key === "Home") {
      if (open) { e.preventDefault(); setHighlight(0); }
    } else if (e.key === "End") {
      if (open) { e.preventDefault(); setHighlight(Math.max(0, filtered.length - 1)); }
    }
  };

  const onClear = () => {
    onChange("");
    setQuery("");
    setHighlight(0);
    setOpen(true);
    if (inputRef.current) inputRef.current.focus();
  };

  const activeId = open && filtered[highlight]
    ? `${listId}-opt-${filtered[highlight].code}`
    : undefined;
  // Locale-aware "Clear" affordance — same vocabulary as Browse's filter
  // chips clear button so the user pattern carries over.
  const clearLabel = locale === "es" ? "Limpiar" : "Clear";

  return (
    <div className="country-combobox" ref={containerRef}>
      <div className="country-combobox-input-row">
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={activeId}
          aria-label={ariaLabel}
          value={query}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          onChange={(e) => { setQuery(e.target.value); if (!open) setOpen(true); }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
        />
        {query && (
          <button
            type="button"
            className="country-combobox-clear"
            onClick={onClear}
            aria-label={clearLabel}
          >
            ×
          </button>
        )}
      </div>
      {open && filtered.length > 0 && (
        <ul
          ref={listRef}
          id={listId}
          role="listbox"
          className="country-combobox-list"
        >
          {filtered.map((c, idx) => (
            <li
              key={c.code}
              id={`${listId}-opt-${c.code}`}
              role="option"
              aria-selected={idx === highlight}
              data-idx={idx}
              className={`country-combobox-option ${idx === highlight ? "is-active" : ""}${c.code === value ? " is-selected" : ""}`}
              // mousedown — fires before the input's blur, so the click
              // commit goes through without the outside-click dismiss
              // racing it.
              onMouseDown={(e) => { e.preventDefault(); commit(c.code); }}
              onMouseEnter={() => setHighlight(idx)}
            >
              {c.name}
            </li>
          ))}
        </ul>
      )}
      {open && filtered.length === 0 && (
        <div className="country-combobox-empty" role="status">
          {locale === "es" ? "Sin resultados" : "No matches"}
        </div>
      )}
    </div>
  );
}

// ============== A.3.2 — Notifications ==============
// The on/off toggle, platform-updates toggle, and frequency picker that
// used to live here have been REMOVED. The backend cron in
// .github/workflows/pulpo-newsletter.yml runs weekly (Monday 14:00 UTC)
// and `automation/newsletter/subscribers._preference_from_profile` does
// not read `cadence`. Wiring those controls to publicMetadata would have
// shipped a UI that lies — toggle off, reload, you still get emails.
// Per the CLAUDE.md "NEVER ship a UI control that lies about persistence"
// guardrail, we keep only the controls that have a real consumer:
// PreferredCategoryChips + NewsletterFilterChips. Restore the toggles
// once PR-NL-4 wires per-user cadence honoring (see plan).
function NotificationsSection({ app }) {
  const isPaid = !!(app.user && app.user.plan && app.user.plan !== "free");

  return (
    <div className="account-section">
      <p className="section-intro">{t("account.notif.intro", app.locale)}</p>

      {!isPaid && <NotifProUpsell app={app} />}

      {isPaid && (
        <p className="section-intro account-cadence-note">
          {t("account.notif.cadence_note", app.locale)}
        </p>
      )}

      {/* Preferred categories stay above the filter — they tag what
          gets surfaced in the editor's voice (PR-B). */}
      {isPaid && <PreferredCategoryChips app={app} />}
      {/* P2b — the Discover FilterPanel, bound to the same
          publicMetadata.profile.discover_filters blob BrowsePage
          persists to (P2a). Changes here round-trip with /browse so
          the user maintains a single filter spec across both surfaces. */}
      {isPaid && <NewsletterFilterPanelBlock app={app} />}
    </div>
  );
}

// ── NewsletterFilterPanelBlock (P2b, 2026-05-29) ─────────────────────
// Wraps the BrowsePage `<FilterPanel>` in an /account/newsletter chrome
// (heading, intro, live count) and binds it to the same
// `publicMetadata.profile.discover_filters` blob the Discover panel
// writes (see web/app/lib/use-discover-filter.ts). Pro users only —
// the Pro upsell renders above when isPaid=false.
//
// Hydration:
//   • Mount-time: seed in-memory filter state from Clerk via
//     storageToDiscover(readDiscoverFilter(app.user)). Falls back to
//     makeDefaultFilters() when the user has no persisted blob (cold
//     start) so the FilterPanel renders against a known shape.
//
// Persistence:
//   • useDiscoverFilterPersist (same hook BrowsePage uses) mirrors
//     filter changes back to Clerk on the standard 800ms debounce.
//     Skip-if-equal guards against the post-write re-render burning a
//     second round-trip.
//
// Live count:
//   • applyFilters against the catalog yields the result count —
//     same function the Discover panel uses, so the number rendered
//     here matches what /browse would show for the same filter.
function NewsletterFilterPanelBlock({ app }) {
  // Hydrate once from Clerk. Subsequent re-renders driven by the
  // FilterPanel's own setFilters; we don't re-read Clerk on every
  // render because that would clobber in-progress edits.
  const [filters, setFilters] = aUseState(() => {
    const stored = readDiscoverFilter(app.user);
    return { ...makeDefaultFilters(), ...storageToDiscover(stored) };
  });

  // Mirror changes back to Clerk via the same debounced hook the
  // Discover panel uses. Skip-if-equal is the load-bearing guard
  // against the mount-time hydration round-trip burning a write.
  useDiscoverFilterPersist(app, filters);

  // Live count — apply the in-memory filter against the catalog. The
  // useListings hook returns an empty array until the JSON resolves,
  // so the count renders as 0 during the initial load (acceptable —
  // the FilterPanel still works on a zero-listings catalog).
  const listings = useListings();
  const count = aUseMemo(
    () => applyFilters(listings, filters).length,
    [listings, filters],
  );

  return (
    <div className="account-newsletter-filter">
      <h3 className="account-subhead">
        {t("account.notif.newsletter_filter.heading", app.locale)}
      </h3>
      <p className="notif-categories-intro">
        {t("account.notif.newsletter_filter.intro", app.locale)}
      </p>
      <div className="account-newsletter-filter-panel">
        <FilterPanel
          filters={filters}
          setFilters={setFilters}
          count={count}
          app={app}
        />
      </div>
    </div>
  );
}

// Upgrade CTA shown to free / anonymous users in the Notifications
// subsection in place of the Pro-gated toggles. Click → standard Stripe
// checkout flow (or signup → checkout for anonymous users via the
// existing pendingAction chain).
function NotifProUpsell({ app }) {
  const onUpgrade = () => {
    // Wave-1 routing: the old path fired startStripeCheckout
    // unconditionally and only fell back to signup on a Stripe 401,
    // which flashed a redirect attempt before showing the modal.
    // Now anon → login_ui, free → paywall (/plans), paid → no-op.
    const flagEnabled = readFeatureFlag("cta_routing_v2", true);
    if (!flagEnabled) {
      startStripeCheckout({
        locale: app.locale,
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
      return;
    }
    const branch = routeCtaForState("newsletter_activation", app?.user);
    trackCtaRouted("newsletter_activation", app?.user, branch, true);
    if (branch === "passthrough") return; // paid → UI already shows toggles
    void dispatchCentralBranch(branch, app);
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
           data-chip-group="preferred-categories"
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

// Vocabulary lives next to the renderer (the cron is the consumer); we
// surface the same labels in the account UI. Departments are the six
// Salvadoran coastal / lake departments where Pulpo has continuous
// listing coverage. Anything else gets a "request a region" CTA in
// a future PR — out of scope here.
const NEWSLETTER_DEPARTMENT_KEYS = [
  "La Libertad",
  "La Paz",
  "La Unión",
  "Usulután",
  "Sonsonate",
  "Santa Ana",
];

const NEWSLETTER_PRICE_BANDS = [
  { key: "none",    max: null,    label_en: "No cap",     label_es: "Sin tope"   },
  { key: "50k",     max:  50_000, label_en: "Under $50k", label_es: "Hasta $50k" },
  { key: "100k",    max: 100_000, label_en: "Under $100k", label_es: "Hasta $100k" },
  { key: "250k",    max: 250_000, label_en: "Under $250k", label_es: "Hasta $250k" },
  { key: "500k",    max: 500_000, label_en: "Under $500k", label_es: "Hasta $500k" },
  { key: "1m",      max: 1_000_000, label_en: "Under $1M", label_es: "Hasta $1M" },
];

// Newsletter filter chip groups — persists to `profile.newsletter` via
// the same updateUserProfile path that PreferredCategoryChips uses. The
// fortnightly cron reads the same blob off Clerk publicMetadata to slice
// ranked.json per-recipient (automation/newsletter/build_issue.py).
//
// Each toggle writes the full `newsletter` sub-object back — partial
// patches would race against the cleanPatch validator on the server,
// which expects a complete object shape.
function NewsletterFilterChips({ app }) {
  const pref = readNewsletterPreference(app.user);
  const selectedDepts   = Array.isArray(pref.departments)    ? pref.departments    : [];
  const selectedTypes   = Array.isArray(pref.property_types) ? pref.property_types : [];
  const selectedMax     = pref.max_price_usd ?? null;
  const selectedLocale  = NEWSLETTER_LOCALES.includes(pref.locale) ? pref.locale : "en";

  const write = (patch) => {
    const next = { ...pref, ...patch };
    // Strip null/empty fields so the stored blob stays compact and the
    // server validator's "no opinion" path (missing key) is preferred
    // over an explicit null we'd have to defend.
    const cleaned = {};
    for (const [k, v] of Object.entries(next)) {
      if (v === null || v === undefined) continue;
      if (Array.isArray(v) && v.length === 0) continue;
      cleaned[k] = v;
    }
    app.updateUserProfile({ newsletter: cleaned });
    track("account.newsletter_pref_changed", {
      changed_keys: Object.keys(patch),
      departments_count: (cleaned.departments || []).length,
      property_types_count: (cleaned.property_types || []).length,
      has_max_price: cleaned.max_price_usd != null,
    });
  };

  const toggleDept = (d) => {
    const next = selectedDepts.includes(d)
      ? selectedDepts.filter((x) => x !== d)
      : [...selectedDepts, d];
    write({ departments: next });
  };

  const toggleType = (typ) => {
    const next = selectedTypes.includes(typ)
      ? selectedTypes.filter((x) => x !== typ)
      : [...selectedTypes, typ];
    write({ property_types: next });
  };

  const setMaxPrice = (band) => {
    write({ max_price_usd: band.max });
  };

  return (
    <div className="notif-categories">
      <h3 className="account-subhead">
        {t("account.notif.newsletter_filter.heading", app.locale)}
      </h3>
      <p className="notif-categories-intro">
        {t("account.notif.newsletter_filter.intro", app.locale)}
      </p>

      <div className="account-subhead-mini">
        {t("account.notif.newsletter_filter.departments", app.locale)}
      </div>
      <div className="chip-grid notif-categories-grid" role="group"
           data-chip-group="newsletter-departments"
           aria-label={t("account.notif.newsletter_filter.departments", app.locale)}>
        {NEWSLETTER_DEPARTMENT_KEYS.map((d) => {
          const isSelected = selectedDepts.includes(d);
          return (
            <button
              key={d}
              type="button"
              role="switch"
              aria-checked={isSelected}
              className={`chip ${isSelected ? "is-active" : ""}`}
              onClick={() => toggleDept(d)}
            >
              {d}
            </button>
          );
        })}
      </div>

      <div className="account-subhead-mini">
        {t("account.notif.newsletter_filter.property_types", app.locale)}
      </div>
      <div className="chip-grid notif-categories-grid" role="group"
           data-chip-group="newsletter-property-types"
           aria-label={t("account.notif.newsletter_filter.property_types", app.locale)}>
        {NEWSLETTER_PROPERTY_TYPES.map((typ) => {
          const isSelected = selectedTypes.includes(typ);
          return (
            <button
              key={typ}
              type="button"
              role="switch"
              aria-checked={isSelected}
              className={`chip ${isSelected ? "is-active" : ""}`}
              onClick={() => toggleType(typ)}
            >
              {t(`account.notif.newsletter_filter.type.${typ}`, app.locale)}
            </button>
          );
        })}
      </div>

      <div className="account-subhead-mini">
        {t("account.notif.newsletter_filter.price_band", app.locale)}
      </div>
      <div className="chip-grid notif-categories-grid" role="group"
           data-chip-group="newsletter-price-band"
           aria-label={t("account.notif.newsletter_filter.price_band", app.locale)}>
        {NEWSLETTER_PRICE_BANDS.map((b) => {
          const isSelected = selectedMax === b.max;
          return (
            <button
              key={b.key}
              type="button"
              role="switch"
              aria-checked={isSelected}
              className={`chip ${isSelected ? "is-active" : ""}`}
              onClick={() => setMaxPrice(b)}
            >
              {app.locale === "es" ? b.label_es : b.label_en}
            </button>
          );
        })}
      </div>

      <div className="account-subhead-mini">
        {t("account.notif.newsletter_filter.locale", app.locale)}
      </div>
      <div className="freq-toggle">
        {NEWSLETTER_LOCALES.map((lc) => (
          <button
            key={lc}
            type="button"
            className={selectedLocale === lc ? "active" : ""}
            onClick={() => write({ locale: lc })}
          >
            {t(`account.notif.newsletter_filter.locale.${lc}`, app.locale)}
          </button>
        ))}
      </div>
    </div>
  );
}

// ============== A.3.3 — Manage Subscription ==============
function SubscriptionSection({ app }) {
  const lc = app.locale;
  // Live subscription view (real publicMetadata via clerk-bundle's
  // hydration). The "status" pill below + the grace banner both source
  // from this single derivation so they can't disagree.
  const subState = deriveSubscriptionState(app.user);
  const plan = subState.effective;
  // display drives every per-state UI branch in this section. Keep raw
  // subscription_status in scope too — the grace banners still key off
  // the raw lifecycle field.
  const display = subState.display;
  const [refreshingPortalState, setRefreshingPortalState] = React.useState(false);
  const subSnapshotRef = React.useRef(subscriptionRefreshSnapshot(subState));
  React.useEffect(() => {
    subSnapshotRef.current = subscriptionRefreshSnapshot(subState);
  }, [display, subState.cancel_at_period_end, subState.status, subState.canceled_at]);

  const isPaid = plan !== "free";
  const inGrace = subState.in_grace;
  const graceDays = graceDaysLeft(app.user);
  // Locale-aware date formatter shared across grace / period_end /
  // canceled_at rendering. Inputs are Unix ms or null; null returns "".
  const fmtDate = (ms) => (typeof ms === "number" && ms > 0)
    ? new Date(ms).toLocaleDateString(lc === "es" ? "es-SV" : "en-US", {
        day: "numeric", month: "long", year: "numeric",
      })
    : "";
  const graceDateStr = fmtDate(subState.grace_period_ends_at);
  const periodEndStr = fmtDate(subState.current_period_end);
  const canceledAtStr = fmtDate(subState.canceled_at);

  // A user who CURRENTLY has Pro OR who has ever paid (sub canceled or
  // past_due) keeps the Stripe Customer Portal accessible so they can
  // download invoices long after their plan ended. Only never-paid
  // users see the empty-state copy.
  const everPaid = isPaid
    || subState.status === "canceled"
    || subState.status === "past_due"
    || subState.current_period_end !== null;

  // Telemetry — fire once per display-state transition so we can detect
  // bad display copy (e.g. "Renews on" leaking onto a canceling user)
  // in PostHog without reaching for a Playwright crawl. Pairs with the
  // vitest unit assertions on deriveSubscriptionState's display field.
  React.useEffect(() => {
    track("account.sub_block_rendered", {
      display,
      plan,
      raw_status: subState.status,
      cancel_at_period_end: subState.cancel_at_period_end,
      in_grace: inGrace,
      has_period_end: subState.current_period_end !== null,
      ever_paid: everPaid,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [display]);

  // Post-portal-return refresh. Stripe webhook updates publicMetadata
  // server-side as soon as the user clicks Cancel / Update card / etc,
  // but Clerk's React `useUser()` caches the user object and never
  // re-polls. Without this, the user lands back on /account/subscription
  // and sees pre-cancel state ("Renews on…") until they hard-refresh.
  //
  // `?from=portal` is the signal — set on the billing-portal session's
  // return_url. On mount with that flag we:
  //   1. Strip the param from the URL so a refresh doesn't loop.
  //   2. Call clerk.user.reload() to pull the latest publicMetadata.
  //      ClerkUserSync rehydrates app.user as soon as the SDK's
  //      reactive user object updates, and this section re-renders
  //      with the fresh display state.
  //   3. Fire telemetry so we can verify in PostHog that returns from
  //      the portal actually surface the new state.
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("from") !== "portal") return;
    // Strip the flag before the reload completes so back/forward
    // navigation doesn't replay it.
    params.delete("from");
    const search = params.toString();
    const next = `${window.location.pathname}${search ? `?${search}` : ""}`;
    try { window.history.replaceState({}, "", next); } catch { /* ignore */ }
    const initial = subscriptionRefreshSnapshot(subState);
    track("account.sub_portal_return", { had_period_end: subState.current_period_end !== null });
    let cancelled = false;
    setRefreshingPortalState(true);
    pollPortalReturnState({
      initial,
      getSnapshot: () => subSnapshotRef.current,
      reloadUser: app.clerkActions && typeof app.clerkActions.reloadUser === "function"
        ? app.clerkActions.reloadUser
        : undefined,
    }).then((result) => {
      if (cancelled) return;
      if (result.changed) {
        track("account.sub_portal_return_state_changed", {
          from_display: result.from.display,
          to_display: result.to.display,
          attempts_to_change: result.attempts,
          ms_to_change: result.waited_ms,
        });
      } else {
        track("account.sub_portal_return_stale", {
          display: result.from.display,
          attempts: result.attempts,
          waited_ms: result.waited_ms,
        });
      }
      setRefreshingPortalState(false);
    }).catch(() => {
      if (cancelled) return;
      track("account.sub_portal_return_stale", {
        display: initial.display,
        attempts: 0,
        waited_ms: 0,
      });
      setRefreshingPortalState(false);
    });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [app.clerkActions]);

  // Open the Stripe Customer Portal — Stripe owns the invoice list,
  // so we hand off rather than render fabricated rows that drift out
  // of date the moment the user actually pays.
  const onOpenInvoices = () => {
    track("account.sub_portal_clicked", { locale: app.locale, display });
    openStripePortal({
      locale: app.locale,
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

      {/* Grace-period warning banner — rendered only when the user is
         currently in the 14-day window after a failed payment. Goes
         above the plan card so it's the first thing the user sees on
         this page. Linking to the Stripe Customer Portal is the one
         action that actually resolves it. */}
      {inGrace && (
        <div className="sub-grace-banner" role="alert" data-testid="sub-grace-banner">
          <div className="sub-grace-banner-body">
            <div className="sub-grace-banner-head">
              {t("account.sub.grace.head", lc)}
            </div>
            <div className="sub-grace-banner-copy">
              {t("account.sub.grace.copy", lc, {
                days: graceDays,
                date: graceDateStr,
              })}
            </div>
          </div>
          <button
            type="button"
            className="btn-primary sub-grace-banner-cta"
            onClick={onOpenInvoices}
            data-testid="sub-grace-banner-cta"
          >
            {t("account.sub.grace.cta_update_card", lc)}
          </button>
        </div>
      )}

      {/* Reactivate notice — past_due but grace has expired. We key
         off subscription_status (raw lifecycle field) rather than the
         derived plan because hydration overwrites plan with the
         effective value, so a grace-expired user reads as plan="free"
         everywhere downstream. status="past_due" + !in_grace is the
         exact "Pro was active, payment failed, grace closed" window. */}
      {subState.status === "past_due" && !inGrace && (
        <div className="sub-grace-banner sub-grace-banner-expired" role="alert" data-testid="sub-grace-banner-expired">
          <div className="sub-grace-banner-body">
            <div className="sub-grace-banner-head">
              {t("account.sub.grace_expired.head", lc)}
            </div>
            <div className="sub-grace-banner-copy">
              {t("account.sub.grace_expired.copy", lc)}
            </div>
          </div>
          <button
            type="button"
            className="btn-primary sub-grace-banner-cta"
            onClick={onOpenInvoices}
            data-testid="sub-grace-banner-reactivate-cta"
          >
            {t("account.sub.grace_expired.cta_reactivate", lc)}
          </button>
        </div>
      )}

      {/* Block 1 — Active plan. Pro identity here uses the same gold
         "Pro" pill the SiteHeader renders next to the wordmark, so a
         signed-in Pro user sees the same brand mark on the chrome and
         in the subscription block.

         Display state drives every per-branch label below — see
         lib/subscription.ts deriveSubscriptionState.display. Never
         hardcode date strings here; the post-2026-05-27 PR-#509-followup
         bug shipped "Renews on 5 Jun 2026" literal placeholders that
         told canceled customers their subscription would renew. */}
      <div className="sub-block">
        <div className="sub-plan-head">
          <div>
            <div className="sub-plan-name">
              {isPaid ? (
                <span className="sub-plan-name-pro">
                  Pulpo <span className="pulpo-logo-pro">Pro</span>
                </span>
              ) : "Free"}
            </div>
            <div className="sub-plan-meta">
              {display === "active" && periodEndStr
                && t("account.sub.plan_meta.renews_on", lc, { date: periodEndStr })}
              {display === "canceling" && periodEndStr
                && t("account.sub.plan_meta.cancels_on", lc, { date: periodEndStr })}
              {display === "canceled"
                && t("account.sub.plan_meta.ended_on", lc, { date: canceledAtStr || periodEndStr })}
              {(display === "grace" || display === "past_due") && /* grace banner handles its own copy */ null}
              {!isPaid && display === "active" && !subState.current_period_end
                && t("account.sub.plan_meta.free", lc)}
              {/* Defensive fallback — should never fire, but if a future
                 state slips through the branches above we want something
                 readable rather than a blank meta row. */}
              {isPaid && display === "active" && !periodEndStr
                && t("account.sub.plan_meta.free", lc)}
            </div>
            {refreshingPortalState && (
              <div className="sub-plan-refreshing" aria-live="polite">
                {t("account.sub.refreshing", lc)}
              </div>
            )}
          </div>
          <span
            className={`status-pill status-${
              display === "active" ? "active"
              : display === "canceling" ? "canceling"
              : display === "canceled" ? "canceled"
              : display === "grace" ? "paused"
              : "payment_issue"
            }`}
            data-testid="sub-status-pill"
          >
            {display === "active" && t("account.sub.pill.active", lc)}
            {display === "canceling" && t("account.sub.pill.canceling", lc)}
            {display === "canceled" && t("account.sub.pill.canceled", lc)}
            {(display === "grace" || display === "past_due") && t("account.sub.pill.past_due", lc)}
          </span>
        </div>
        <div className="sub-plan-status-copy">
          {display === "active" && isPaid && periodEndStr
            && t("account.sub.status_copy.active", lc, { date: periodEndStr })}
          {display === "canceling"
            && t("account.sub.status_copy.canceling", lc, { date: periodEndStr })}
          {display === "canceled"
            && t("account.sub.status_copy.canceled", lc, { date: canceledAtStr || periodEndStr })}
          {!isPaid && display === "active"
            && t("account.sub.status_copy.free", lc)}
        </div>
        <div className="sub-plan-actions">
          {/* Active or canceling: Stripe portal (manage / re-enable
             renewal). Canceled or free: upgrade CTA. */}
          {(display === "active" || display === "canceling") ? (
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                track("account.sub_portal_clicked", { locale: app.locale, display });
                openStripePortal({
                  locale: app.locale,
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
          ) : display === "canceled" ? (
            <button
              className="btn-primary"
              onClick={() => {
                track("account.sub_resubscribe_clicked", {});
                startStripeCheckout({
                  locale: app.locale,
                  onError: (code) => {
                    if (code === "sign_in_required") {
                      app.showToast(t("plans.checkout_auth_mismatch", app.locale));
                    } else {
                      app.go("plans");
                    }
                  },
                });
              }}
            >{t("account.sub.reactivate", app.locale)}</button>
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
                  locale: app.locale,
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

      {/* Block 2 — Invoices (handed off to Stripe Customer Portal).
         Gated on `everPaid` rather than `isPaid` so a canceled user
         can still pull historical receipts after dropping back to Free.
         The billing-portal endpoint self-heals stripeCustomerId via
         email lookup if missing, so the link is always safe to render
         for ever-paid users. */}
      <div className="sub-divider" />
      <h3 className="account-subhead">{t("account.sub.invoices_heading", app.locale)}</h3>
      {everPaid ? (
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
