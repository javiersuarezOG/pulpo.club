// /api/saves
//
// GET   — returns the signed-in user's saved listing IDs as
//         { saves: string[], cap: number, plan: "free" | "pro" }.
// POST  — { listing_id: string, action: "add" | "remove" }
//         enforces the 10-save cap on free plan, returns 402 with
//         { error: "save_cap_reached", cap } when exceeded. On
//         success returns the new saves[] (so the client doesn't
//         have to second-guess the server).
//
// Storage: Clerk user privateMetadata.saves[]. Keeping this in
// Clerk avoids a separate DB while we're at small scale; the plan
// flags this as a known scaling limit and budgets a future move to
// Vercel Postgres in PR-11. When that time comes the API surface
// here doesn't change.
//
// Auth: Clerk session cookie on the request; verified via
// `authenticateClerkRequest`. No session → 401.

const fs = require("fs");
const path = require("path");
const { clerkClient, authenticateClerkRequest } = require("./_clerk");
const { effectivePlan } = require("./_plan");
const { makeRateLimiter, send429 } = require("./_rate_limit");
const withTiming = require("./_perf");

const FREE_SAVE_CAP = 10;

// ── Storage shape (post-favorites-backend, 2026-05-29) ─────────────
//
// `privateMetadata.saves[]` is a MIXED array of:
//   • Legacy bare ID strings  → "remax__001461165132"
//   • Enriched objects        → { id, saved_at, price_at_save_usd?,
//                                  source? }
//
// All read paths normalize to the enriched shape via `_normalizeSave`.
// External callers (GET response, frontend Set membership) get the
// bare-ID array via `_extractIds` — the enrichment is invisible to
// the SPA. The newsletter Python pipeline reads the raw mixed array
// out of Clerk and runs its own normalizer for week-over-week diffs.
//
// When the user saves a NEW listing, we enrich on the write path by
// looking up the listing's current price + source in ranked.json. If
// the lookup fails (stale ID, transient FS error), we still persist a
// minimal `{id, saved_at}` so the save itself never fails.
//
// `ranked.json` is read once per Vercel cold start and cached in
// `_rankedIndex` for the lifetime of the lambda instance. 6.4MB file,
// ~100ms first read; subsequent saves use the indexed lookup.

let _rankedIndex = null;
function rankedIndex() {
  if (_rankedIndex) return _rankedIndex;
  try {
    const filepath = path.join(process.cwd(), "web", "data", "ranked.json");
    const arr = JSON.parse(fs.readFileSync(filepath, "utf8"));
    const map = new Map();
    for (const l of arr) {
      if (!l || !l.source || !l.source_id) continue;
      map.set(`${l.source}__${l.source_id}`, l);
    }
    _rankedIndex = map;
  } catch (err) {
    // FS / parse failure shouldn't kill the save endpoint — fall back
    // to an empty index so the save still persists, just without
    // enrichment metadata. Logged so we notice if it happens in prod.
    console.log(`[api] saves ranked_index_load_failed error=${err && err.message}`);
    _rankedIndex = new Map();
  }
  return _rankedIndex;
}

function _normalizeSave(entry) {
  if (typeof entry === "string") return { id: entry };
  if (entry && typeof entry === "object" && typeof entry.id === "string") {
    return entry;
  }
  return null;
}

function _extractIds(saves) {
  const out = [];
  for (const e of saves || []) {
    const n = _normalizeSave(e);
    if (n) out.push(n.id);
  }
  return out;
}

function _hasId(saves, id) {
  return _extractIds(saves).includes(id);
}

function _removeById(saves, id) {
  return (saves || []).filter((e) => {
    const n = _normalizeSave(e);
    return n && n.id !== id;
  });
}

function _enrichForSave(id) {
  // Build the enriched save record for a newly-added listing. Looks
  // the listing up in ranked.json so the price + source is captured
  // at save time — the newsletter pipeline later uses this to compute
  // "↓ Price dropped $X since you saved it".
  const entry = { id, saved_at: new Date().toISOString() };
  const listing = rankedIndex().get(id);
  if (listing) {
    if (typeof listing.price_usd === "number" && listing.price_usd > 0) {
      entry.price_at_save_usd = listing.price_usd;
    }
    if (typeof listing.source === "string") entry.source = listing.source;
  }
  return entry;
}

// 30 writes / 60s per user (or per IP for unauthenticated requests, which
// 401 quickly anyway). Generous for legit use — a user couldn't realistically
// click the heart icon 30 times in a minute — but cuts off a script-driven
// loop within seconds. Keyed primarily on userId so a shared-IP household
// doesn't share a bucket.
const savesLimiter = makeRateLimiter({
  windowMs: 60_000,
  maxAttempts: 30,
  name: "saves",
});

function logApi(name, fields) {
  const parts = [`[api]`, name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

async function readUser(userId) {
  const clerk = clerkClient();
  const user = await clerk.users.getUser(userId);
  const saves = Array.isArray(user.privateMetadata && user.privateMetadata.saves)
    ? user.privateMetadata.saves
    : [];
  const plan = effectivePlan(user);
  return { user, saves, plan };
}

async function writeSaves(userId, saves) {
  await clerkClient().users.updateUser(userId, {
    privateMetadata: { saves },
  });
}

// PR-perf-5a — wrap with withTiming so every response carries
// Server-Timing + X-Vercel-Region. The client's timedApiFetch reads
// both and tags `perf.api_call` events with the region — lets the
// Geo Latency dashboard tell apart "saves endpoint is slow from
// Europe because it lives in iad1" from "saves endpoint is slow
// everywhere".
module.exports = withTiming(async (req, res) => {
  const t0 = Date.now();

  let userId;
  try {
    userId = await authenticateClerkRequest(req);
  } catch (err) {
    // Log internally with class + message for triage, but return a
    // generic error to the client — leaking the exception class to the
    // browser is an information-disclosure smell flagged in the
    // reliability audit.
    logApi("saves", {
      status: 500, ms: Date.now() - t0, reason: "auth_throw",
      error_class: err && err.constructor ? err.constructor.name : "Error",
      error: err && err.message,
    });
    return res.status(500).json({ error: "auth_failed" });
  }
  if (!userId) {
    logApi("saves", { status: 401, ms: Date.now() - t0, reason: "unauthenticated" });
    return res.status(401).json({ error: "sign_in_required" });
  }

  // Rate limit AFTER auth so unauthenticated brute-force traffic hits
  // 401 first (cheaper) and authenticated callers get a per-user bucket
  // rather than fighting their IP-mates for slots.
  const rl = savesLimiter.hit(userId);
  if (!rl.allowed) {
    logApi("saves", {
      status: 429, ms: Date.now() - t0, reason: "rate_limited",
      retry_after_s: Math.ceil(rl.retryAfterMs / 1000),
    });
    return send429(res, rl, "saves");
  }

  if (req.method === "GET") {
    try {
      const { saves, plan } = await readUser(userId);
      // External contract: saves[] is a flat string-ID array. Internal
      // storage may be mixed (legacy strings + enriched objects); we
      // extract IDs here so the SPA Set membership logic stays simple.
      const ids = _extractIds(saves);
      logApi("saves", { status: 200, ms: Date.now() - t0, op: "get", count: ids.length });
      return res.status(200).json({ saves: ids, cap: FREE_SAVE_CAP, plan });
    } catch (err) {
      logApi("saves", { status: 500, ms: Date.now() - t0, op: "get", error: err.message });
      return res.status(500).json({ error: "lookup_failed" });
    }
  }

  if (req.method === "POST") {
    let body = req.body;
    if (typeof body === "string") {
      try { body = JSON.parse(body); } catch { body = {}; }
    }
    body = body || {};
    const listingId = (body.listing_id || "").toString();
    const action = (body.action || "").toString();
    if (!listingId) {
      logApi("saves", { status: 400, ms: Date.now() - t0, reason: "missing_listing_id" });
      return res.status(400).json({ error: "missing_listing_id" });
    }
    if (action !== "add" && action !== "remove") {
      logApi("saves", { status: 400, ms: Date.now() - t0, reason: "bad_action" });
      return res.status(400).json({ error: "bad_action" });
    }

    try {
      const { saves, plan } = await readUser(userId);
      let next = Array.isArray(saves) ? [...saves] : [];

      if (action === "add") {
        // Two-state model (2026-06-08): saving is a Pro capability. The
        // never-paid free account is gone; a non-Pro `plan` here is a
        // canceled/ever-paid member. They cannot ADD saves — the UI gates
        // this, and we enforce it server-side too (defense in depth against
        // a direct POST). `remove` stays open below so a canceled member
        // can still tidy listings they saved while active. The old
        // free-tier 10-cap is retired: Pro is uncapped, non-Pro is blocked.
        const isActivePro = plan === "pro" || plan === "agency";
        if (!isActivePro) {
          logApi("saves", { status: 403, ms: Date.now() - t0, op: "add", reason: "pro_required", plan });
          return res.status(403).json({ error: "pro_required", plan });
        }
        if (!_hasId(next, listingId)) {
          // Server-side enrichment: look up ranked.json so the saved
          // entry carries price_at_save_usd + saved_at. The newsletter
          // pipeline uses these to compute "↓ Price dropped $X" deltas.
          next.push(_enrichForSave(listingId));
        }
      } else {
        next = _removeById(next, listingId);
      }

      await writeSaves(userId, next);
      const ids = _extractIds(next);
      logApi("saves", {
        status: 200, ms: Date.now() - t0, op: action, count: ids.length, plan,
      });
      // Response still carries bare IDs — frontend Set logic untouched.
      return res.status(200).json({ saves: ids, cap: FREE_SAVE_CAP, plan });
    } catch (err) {
      logApi("saves", { status: 500, ms: Date.now() - t0, op: action, error: err.message });
      return res.status(500).json({ error: "write_failed" });
    }
  }

  res.setHeader("Allow", "GET, POST");
  logApi("saves", { status: 405, ms: Date.now() - t0, reason: "method", method: req.method });
  return res.status(405).json({ error: "method_not_allowed" });
});
