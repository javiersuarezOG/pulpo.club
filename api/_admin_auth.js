// Shared bearer-token auth for /api/admin/* endpoints.
//
// Pulpo has no Clerk-side admin role; the admin surface is gated by a
// single shared secret (`PULPO_ADMIN_DEBUG_TOKEN`) set in Vercel env.
// Sebas types it once on /admin in the browser; the client stashes it
// in localStorage and threads it on every admin request as
// `Authorization: Bearer <token>`. The server compares with a
// constant-time check to avoid timing leaks.
//
// Why a shared secret + not Clerk roles:
//   - No DB to store role assignments.
//   - The /admin surface predates the launch and was deliberately
//     "open by design" for fast iteration. This module is the smallest
//     possible upgrade — adds the gate without restructuring auth.
//   - Sebas is the only admin in the launch window. When that changes,
//     swap this for a `publicMetadata.role === "admin"` Clerk check
//     and the call sites stay identical.
//
// Calling convention: handlers call `requireAdminAuth(req, res)` at
// the top. Returns `true` if the request is authorized; if not, it
// has already sent a 401 and returned `false` — the handler should
// `return` immediately.

const crypto = require("crypto");

const ENV_NAME = "PULPO_ADMIN_DEBUG_TOKEN";

function readBearerToken(req) {
  const header = req && req.headers
    && (req.headers.authorization || req.headers.Authorization);
  if (!header || typeof header !== "string") return "";
  if (!header.startsWith("Bearer ")) return "";
  return header.slice(7).trim();
}

function tokensMatch(given, expected) {
  if (!given || !expected) return false;
  const a = Buffer.from(given);
  const b = Buffer.from(expected);
  if (a.length !== b.length) return false;
  try {
    return crypto.timingSafeEqual(a, b);
  } catch {
    return false;
  }
}

function requireAdminAuth(req, res) {
  const expected = process.env[ENV_NAME] || "";
  if (!expected) {
    // Env var not configured — return 503 so the operator can tell
    // "feature disabled" apart from "wrong token." Matches the
    // graceful-degrade convention used by /api/newsletter etc.
    res.status(503).json({ error: "admin_not_configured" });
    return false;
  }
  const given = readBearerToken(req);
  if (!tokensMatch(given, expected)) {
    res.status(401).json({ error: "unauthorized" });
    return false;
  }
  return true;
}

module.exports = { requireAdminAuth, readBearerToken, tokensMatch, ENV_NAME };
