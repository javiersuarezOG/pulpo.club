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

const ALLOWED_PROFILE_KEYS = {
  // Newsletter / personalization categories. Keys are the
  // PreferenceCategoryKey vocabulary defined in
  // web/app/lib/categories.ts — kept in sync manually.
  preferred_categories: {
    isValid: (v) => Array.isArray(v)
      && v.length <= 8
      && v.every((s) => typeof s === "string" && s.length <= 64),
  },
  // Fortnightly newsletter filter spec. Shape mirrored on the client by
  // NewsletterPreference in web/app/lib/user-profile.ts and on the cron
  // side by automation/newsletter/types.Preference.
  newsletter: {
    isValid: isNewsletterPreference,
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
  try {
    const clerk = clerkClient();
    const user = await clerk.users.getUser(userId);
    const currentPublic = (user && user.publicMetadata) || {};
    const currentProfile =
      (currentPublic.profile && typeof currentPublic.profile === "object")
        ? currentPublic.profile
        : {};
    const nextProfile = { ...currentProfile, ...patch };

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
    logApi("clerk.update_profile", {
      status: 500, ms: Date.now() - t0, reason: "write_failed",
      error: err && err.message,
    });
    return res.status(500).json({
      error: "write_failed",
      detail: err && err.message,
    });
  }
};
