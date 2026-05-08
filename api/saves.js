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

const { clerkClient, authenticateClerkRequest } = require("./_clerk");

const FREE_SAVE_CAP = 10;

function planFromMetadata(publicMetadata) {
  return publicMetadata && publicMetadata.plan === "pro" ? "pro" : "free";
}

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
  const plan = planFromMetadata(user.publicMetadata);
  return { user, saves, plan };
}

async function writeSaves(userId, saves) {
  await clerkClient().users.updateUser(userId, {
    privateMetadata: { saves },
  });
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  let userId;
  try {
    userId = await authenticateClerkRequest(req);
  } catch (err) {
    // Surface the message in the response so we can triage from the
    // browser console without needing Vercel runtime logs. Clerk dev
    // keys aren't sensitive; the message is normally just a class
    // name + reason, no PII.
    logApi("saves", {
      status: 500, ms: Date.now() - t0, reason: "auth_throw",
      error_class: err && err.constructor ? err.constructor.name : "Error",
      error: err && err.message,
    });
    return res.status(500).json({
      error: "auth_failed",
      detail: err && err.message,
      class: err && err.constructor ? err.constructor.name : undefined,
    });
  }
  if (!userId) {
    logApi("saves", { status: 401, ms: Date.now() - t0, reason: "unauthenticated" });
    return res.status(401).json({ error: "sign_in_required" });
  }

  if (req.method === "GET") {
    try {
      const { saves, plan } = await readUser(userId);
      logApi("saves", { status: 200, ms: Date.now() - t0, op: "get", count: saves.length });
      return res.status(200).json({ saves, cap: FREE_SAVE_CAP, plan });
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
      const set = new Set(saves);

      if (action === "add") {
        if (!set.has(listingId)) {
          if (plan === "free" && set.size >= FREE_SAVE_CAP) {
            logApi("saves", {
              status: 402, ms: Date.now() - t0, op: "add", reason: "cap_reached", count: set.size,
            });
            return res.status(402).json({
              error: "save_cap_reached",
              cap: FREE_SAVE_CAP,
              plan,
            });
          }
          set.add(listingId);
        }
      } else {
        set.delete(listingId);
      }

      const next = Array.from(set);
      await writeSaves(userId, next);
      logApi("saves", {
        status: 200, ms: Date.now() - t0, op: action, count: next.length, plan,
      });
      return res.status(200).json({ saves: next, cap: FREE_SAVE_CAP, plan });
    } catch (err) {
      logApi("saves", { status: 500, ms: Date.now() - t0, op: action, error: err.message });
      return res.status(500).json({ error: "write_failed" });
    }
  }

  res.setHeader("Allow", "GET, POST");
  logApi("saves", { status: 405, ms: Date.now() - t0, reason: "method", method: req.method });
  return res.status(405).json({ error: "method_not_allowed" });
};
