// Shared Svix webhook helpers.
//
// Svix signs webhook payloads with an HMAC-SHA256 over the canonical
// string `${id}.${timestamp}.${body}`. Used by every webhook provider
// that delegates signing to Svix — Resend (newsletter), Clerk (auth),
// and likely future ones. Centralising the verifier keeps the security
// contract in one place and makes it testable independent of any one
// caller.
//
// Originally lived inline in api/resend-webhook.js. Extracted when
// api/clerk/webhook.js was added so the two handlers share one
// constant-time signature path instead of two near-identical copies
// drifting apart.

const crypto = require("crypto");

const TIMESTAMP_TOLERANCE_S = 300;          // ±5 minutes
const MAX_BODY_SIZE = 64 * 1024;            // 64 KB

// Vercel may have already parsed JSON; we need the RAW string for HMAC,
// so this routes parsed bodies back through JSON.stringify as a fallback
// (key-order-stable). The configured Vercel function MUST set
// `bodyParser: false` for any handler that depends on this helper.
async function readRawBody(req) {
  if (typeof req.body === "string") {
    return req.body.slice(0, MAX_BODY_SIZE);
  }
  if (req.body && typeof req.body === "object") {
    try { return JSON.stringify(req.body); } catch { return ""; }
  }
  const chunks = [];
  let total = 0;
  for await (const chunk of req) {
    const buf = typeof chunk === "string" ? Buffer.from(chunk) : chunk;
    chunks.push(buf);
    total += buf.length;
    if (total > MAX_BODY_SIZE) break;
  }
  return Buffer.concat(chunks).toString("utf8").slice(0, MAX_BODY_SIZE);
}

// Svix sends one or more signatures space-separated; format is
// `v1,<base64>` per signature. Verify if any one matches.
//
// `secret` accepts both Svix's `whsec_<base64>` form and a raw base64 /
// utf8 string. Constant-time compare on the HMAC. Timestamp freshness
// gate of ±5 minutes blocks replay attacks beyond that window.
function verifySvixSignature({ secret, svixId, svixTimestamp, svixSignature, body }) {
  if (!secret || !svixId || !svixTimestamp || !svixSignature || !body) return false;

  const ts = Number.parseInt(svixTimestamp, 10);
  if (!Number.isFinite(ts)) return false;
  const nowS = Math.floor(Date.now() / 1000);
  if (Math.abs(nowS - ts) > TIMESTAMP_TOLERANCE_S) return false;

  // Secret can be passed as `whsec_<base64>` (Svix convention) or as a
  // raw base64 / hex string. Try base64 first; fall back to raw bytes.
  let secretBytes;
  const stripped = secret.startsWith("whsec_") ? secret.slice(6) : secret;
  try {
    secretBytes = Buffer.from(stripped, "base64");
    if (secretBytes.length === 0) secretBytes = Buffer.from(secret, "utf8");
  } catch {
    secretBytes = Buffer.from(secret, "utf8");
  }

  const toSign = `${svixId}.${svixTimestamp}.${body}`;
  const expected = crypto
    .createHmac("sha256", secretBytes)
    .update(toSign)
    .digest("base64");

  const candidates = svixSignature.split(" ").map(s => s.trim()).filter(Boolean);
  for (const c of candidates) {
    const idx = c.indexOf(",");
    if (idx < 0) continue;
    const sig = c.slice(idx + 1);
    if (sig.length === 0) continue;
    if (sig.length !== expected.length) continue;
    try {
      if (crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(expected))) {
        return true;
      }
    } catch {
      continue;
    }
  }
  return false;
}

module.exports = {
  verifySvixSignature,
  readRawBody,
  TIMESTAMP_TOLERANCE_S,
  MAX_BODY_SIZE,
};
