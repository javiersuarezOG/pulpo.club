// POST /api/clerk/update-profile
//
// Patches the signed-in user's `publicMetadata.profile` blob in Clerk.
// The frontend (web/app/auth/clerk-bundle.jsx → ClerkActionsBinder)
// calls this from `app.updateUserProfile` after the optimistic local
// update, so a Pro user picking newsletter categories on browser A
// sees them in browser B on the next sign-in.
//
// Why backend-only:
//   `publicMetadata` is read on every JWT issuance, so backend workers
//   (newsletter generator, future personalization) can trust it without
//   a per-request Clerk roundtrip. Clerk intentionally blocks frontend
//   SDK writes to `publicMetadata` — the user's own browser can't be
//   trusted to set their plan / preferences. Frontend writes go to
//   `unsafeMetadata` instead, which we don't use. See
//   web/app/lib/README-categories.md.
//
// Auth: Clerk session cookie on the request, verified via
// `authenticateClerkRequest`. No session → 401.
//
// Patch shape: { patch: { …profileFields… } }. Only known keys are
// accepted; anything else is silently dropped. Adding a new
// preference field = add it to ALLOWED_PROFILE_KEYS below + the
// corresponding type in web/app/lib/user-profile.ts.
//
// Response:
//   200 { profile: { …merged profile… } }   — frontend re-syncs from this
//   400 { error: "bad_patch" | "empty_patch" }
//   401 { error: "sign_in_required" }
//   405 { error: "method_not_allowed" }
//   500 { error: "auth_failed" | "write_failed" }

const { clerkClient, authenticateClerkRequest } = require("../_clerk");

// Allow-list of writable keys inside `publicMetadata.profile`. Anything
// not on this list is dropped before write — defends against future
// frontend bugs that accidentally PATCH unintended fields, and gives
// a single grep target when reasoning about what's storable.
//
// Each entry includes a lightweight validator. Keep these cheap (no
// regex over huge strings; nothing async). Detailed validation lives
// on the frontend / inside lib/categories.ts; this is the server-side
// floor.
// Newsletter sub-schema. Each leaf has a bounded check — no regex over
// large strings. Strings cap at 64 chars / arrays at 16 entries so a
// hand-edited Clerk metadata blob can never bloat the cron payload.
const NEWSLETTER_CADENCES = new Set(["fortnight", "monthly", "off"]);
const NEWSLETTER_LOCALES = new Set(["en", "es"]);
const NEWSLETTER_PROPERTY_TYPES = new Set(["land", "house", "condo"]);

function isShortStringArray(v, max) {
  return Array.isArray(v)
    && v.length <= max
    && v.every((s) => typeof s === "string" && s.length <= 64);
}

function isNewsletterPreference(v) {
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;
  const keys = Object.keys(v);
  if (keys.length > 12) return false;       // bounded surface
  if ("zones" in v && !isShortStringArray(v.zones, 16)) return false;
  if ("departments" in v && !isShortStringArray(v.departments, 8)) return false;
  if ("categories" in v && !isShortStringArray(v.categories, 8)) return false;
  if ("property_types" in v) {
    if (!Array.isArray(v.property_types)) return false;
    if (v.property_types.length > 3) return false;
    if (!v.property_types.every((s) => NEWSLETTER_PROPERTY_TYPES.has(s))) return false;
  }
  if ("max_price_usd" in v && v.max_price_usd !== null
      && (typeof v.max_price_usd !== "number" || v.max_price_usd < 0 || v.max_price_usd > 1e10)) {
    return false;
  }
  if ("min_price_usd" in v && v.min_price_usd !== null
      && (typeof v.min_price_usd !== "number" || v.min_price_usd < 0 || v.min_price_usd > 1e10)) {
    return false;
  }
  if ("locale" in v && !NEWSLETTER_LOCALES.has(v.locale)) return false;
  if ("cadence" in v && !NEWSLETTER_CADENCES.has(v.cadence)) return false;
  return true;
}

// ── discover_filters ─────────────────────────────────────────────────
// P2a (2026-05-29): the Discover panel's filter state persists to Clerk
// publicMetadata.profile.discover_filters so it round-trips across
// devices AND drives the weekly newsletter pipeline (replaces the
// older `newsletter` blob in a follow-up PR).
//
// Persisted axes (13) — what the user wants to FIND. Excluded
// (weights, score_min, photos, include_incomplete) are tuning knobs
// for how the user reads the catalogue and stay client-state.
//
// Shape mirrors `makeDefaultFilters()` in web/app/pages.jsx with all
// Set<string> axes serialised to arrays for JSON-safe storage.
const DISCOVER_MASTER_CATEGORIES = new Set(["beach", "lake"]);
const DISCOVER_SUBCATEGORIES = new Set(["homes", "condos", "land"]);
const DISCOVER_FILTER_KEY_LIMIT = 16;          // 13 axes + headroom for future axes

function isDiscoverFilter(v) {
  if (!v || typeof v !== "object" || Array.isArray(v)) return false;
  if (Object.keys(v).length > DISCOVER_FILTER_KEY_LIMIT) return false;
  // Set-shaped axes — every axis is optional; missing key = no opinion.
  if ("zones"          in v && !isShortStringArray(v.zones, 32))          return false;
  if ("land_types"     in v && !isShortStringArray(v.land_types, 8))      return false;
  if ("features"       in v && !isShortStringArray(v.features, 16))       return false;
  if ("infra"          in v && !isShortStringArray(v.infra, 8))           return false;
  if ("status"         in v && !isShortStringArray(v.status, 8))          return false;
  if ("discovery_tags" in v && !isShortStringArray(v.discovery_tags, 16)) return false;
  // Numeric axes with sane bounds.
  if ("price_min" in v && (typeof v.price_min !== "number" || v.price_min < 0 || v.price_min > 1e10)) return false;
  if ("price_max" in v && v.price_max !== null
      && (typeof v.price_max !== "number" || v.price_max < 0 || v.price_max > 1e10)) {
    return false;
  }
  if ("size_min"  in v && (typeof v.size_min  !== "number" || v.size_min  < 0 || v.size_min  > 1e9)) return false;
  if ("readiness" in v && (typeof v.readiness !== "number" || v.readiness < 0 || v.readiness > 4))   return false;
  if ("rank_max"  in v && v.rank_max !== null
      && (typeof v.rank_max !== "number" || v.rank_max < 1 || v.rank_max > 100)) {
    return false;
  }
  // Enum axes.
  if ("master_category" in v && v.master_category !== null
      && !DISCOVER_MASTER_CATEGORIES.has(v.master_category)) {
    return false;
  }
  if ("subcategory" in v && v.subcategory !== null
      && !DISCOVER_SUBCATEGORIES.has(v.subcategory)) {
    return false;
  }
  return true;
}

const ALLOWED_PROFILE_KEYS = {
  // Newsletter / personalization categories. Keys are the
  // PreferenceCategoryKey vocabulary defined in
  // web/app/lib/categories.ts — kept in sync manually.
  preferred_categories: {
    isValid: (v) => Array.isArray(v)
      && v.length <= 8
      && v.every((s) => typeof s === "string" && s.length <= 64),
  },
  // Legacy newsletter filter spec — narrow shape (departments,
  // property_types, max_price_usd). Retained for back-compat while P3
  // migrates the cron to read discover_filters instead.
  newsletter: {
    isValid: isNewsletterPreference,
  },
  // Discover panel filter state (P2a, 2026-05-29). 13 "what to find"
  // axes — zones, types, features, infra, status, price band, size,
  // discovery_tags, ranking, etc. The Discover panel writes here on
  // change; /account/newsletter reads from the same blob so changes
  // round-trip. Tuning controls (weights / score_min / photos /
  // include_incomplete) stay client-state.
  discover_filters: {
    isValid: isDiscoverFilter,
  },
  // ISO 3166-1 alpha-2. The client picker is restricted to the COUNTRIES
  // table; this regex is a junk-input floor — a non-matching 2-letter
  // code won't crash anything, it'd just render as an unknown country on
  // the UI later. Two-letter shape is enough to keep storage tidy.
  country: {
    isValid: (v) => typeof v === "string" && /^[A-Z]{2}$/.test(v),
  },
  // App locale that should follow the user across devices. Same set the
  // newsletter cron uses for per-recipient email locale, so we get the
  // server-side normalization for free.
  language: {
    isValid: (v) => typeof v === "string" && NEWSLETTER_LOCALES.has(v),
  },
};

function logApi(name, fields) {
  const parts = [`[api]`, name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  if (typeof req.body === "string") {
    try { return JSON.parse(req.body); } catch { return {}; }
  }
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
  }
  const raw = Buffer.concat(chunks).toString("utf8");
  if (!raw) return {};
  try { return JSON.parse(raw); } catch { return {}; }
}

// Filters the incoming patch to allowed keys + valid values. Returns
// the cleaned patch and a `dropped` list (logged for triage; never
// returned to the client to avoid leaking server-side validation
// hints). Empty cleaned patch is a 400 — refusing to touch Clerk for
// a no-op keeps the audit trail honest.
function cleanPatch(patch) {
  const out = {};
  const dropped = [];
  if (!patch || typeof patch !== "object" || Array.isArray(patch)) {
    return { out, dropped: ["__not_an_object__"] };
  }
  for (const [k, v] of Object.entries(patch)) {
    const spec = ALLOWED_PROFILE_KEYS[k];
    if (!spec) { dropped.push(`${k}:unknown_key`); continue; }
    if (!spec.isValid(v)) { dropped.push(`${k}:invalid`); continue; }
    out[k] = v;
  }
  return { out, dropped };
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("clerk.update_profile", {
      status: 405, ms: Date.now() - t0, reason: "method", method: req.method,
    });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  let userId;
  try {
    userId = await authenticateClerkRequest(req);
  } catch (err) {
    logApi("clerk.update_profile", {
      status: 500, ms: Date.now() - t0, reason: "auth_throw",
      error_class: err && err.constructor ? err.constructor.name : "Error",
      error: err && err.message,
    });
    return res.status(500).json({
      error: "auth_failed",
      detail: err && err.message,
    });
  }
  if (!userId) {
    logApi("clerk.update_profile", {
      status: 401, ms: Date.now() - t0, reason: "unauthenticated",
    });
    return res.status(401).json({ error: "sign_in_required" });
  }

  const body = await readJsonBody(req);
  const { out: patch, dropped } = cleanPatch(body && body.patch);
  if (dropped.length > 0) {
    logApi("clerk.update_profile", {
      status: 200, ms: Date.now() - t0, dropped: dropped.length, kinds: dropped.join(","),
    });
  }
  if (Object.keys(patch).length === 0) {
    logApi("clerk.update_profile", {
      status: 400, ms: Date.now() - t0, reason: "empty_patch",
    });
    return res.status(400).json({ error: "empty_patch" });
  }

  // Read current publicMetadata so we can shallow-merge the patch into
  // the `profile` sub-object. Without the read step we'd clobber any
  // sibling field (e.g. `plan`) on every write. Clerk's
  // updateUserMetadata REPLACES publicMetadata wholesale.
  let currentPublic = {};
  let nextProfile = null;
  try {
    const clerk = clerkClient();
    const user = await clerk.users.getUser(userId);
    currentPublic = (user && user.publicMetadata) || {};
    const currentProfile =
      (currentPublic.profile && typeof currentPublic.profile === "object")
        ? currentPublic.profile
        : {};
    nextProfile = { ...currentProfile, ...patch };

    await clerk.users.updateUserMetadata(userId, {
      publicMetadata: {
        ...currentPublic,
        profile: nextProfile,
      },
    });

    logApi("clerk.update_profile", {
      status: 200, ms: Date.now() - t0,
      keys: Object.keys(patch).join(","),
    });
    return res.status(200).json({ profile: nextProfile });
  } catch (err) {
    // Clerk SDK errors carry a structured `errors` array ({ code, message,
    // longMessage }) + an HTTP `status`; the bare `err.message` is often just
    // "Unprocessable Entity". Surface the specific message + the serialized
    // publicMetadata size so a stuck account — e.g. metadata over Clerk's
    // ~8 KB cap — is diagnosable at a glance (both logged AND returned).
    const clerkErrors = err && Array.isArray(err.errors) ? err.errors : [];
    const primary = clerkErrors[0] || {};
    const detail = (primary.longMessage || primary.message || (err && err.message) || "unknown").slice(0, 300);
    let bytes = -1;
    try { bytes = JSON.stringify({ ...currentPublic, profile: nextProfile || {} }).length; } catch { /* ignore */ }
    logApi("clerk.update_profile", {
      status: 500, ms: Date.now() - t0, reason: "write_failed",
      clerk_status: (err && err.status) || 0,
      clerk_code: primary.code || "-",
      bytes,
      error: detail,
    });
    return res.status(500).json({
      error: "write_failed",
      reason: primary.code || "clerk_error",
      detail,
      bytes,
    });
  }
};
