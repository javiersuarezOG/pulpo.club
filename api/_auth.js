// Tiny shared auth helpers for the pulpo.club paywall.
//
// Access model: single shared access code stored as a bcrypt hash in the
// ACCESS_HASH env var. Anyone with the code gets the full data set.
// Generate with: node -e "const b=require('bcryptjs');b.hash('yourcode',10).then(console.log)"
//
// Sessions are HMAC-signed cookies, stateless. Cookie is HttpOnly + Secure +
// SameSite=Lax + 14-day expiry.

const crypto = require("crypto");
const bcrypt = require("bcryptjs");

const COOKIE_NAME = "pulpo_sess";
const SESSION_TTL_SECONDS = 60 * 60 * 24 * 14; // 14 days

function getAccessHash() {
  const h = process.env.ACCESS_HASH || "";
  return h.trim();
}

function getSecret() {
  const s = process.env.SESSION_SECRET;
  if (!s || s.length < 32) {
    // Fail loudly. A weak secret defeats the whole point.
    throw new Error("SESSION_SECRET env var must be set and ≥ 32 chars");
  }
  return s;
}

function b64url(buf) {
  return Buffer.from(buf).toString("base64")
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function b64urlDecode(str) {
  str = str.replace(/-/g, "+").replace(/_/g, "/");
  while (str.length % 4) str += "=";
  return Buffer.from(str, "base64");
}

function sign(payload) {
  const data = b64url(JSON.stringify(payload));
  const mac = crypto.createHmac("sha256", getSecret()).update(data).digest();
  return data + "." + b64url(mac);
}

function verify(token) {
  if (!token || typeof token !== "string") return null;
  const dot = token.lastIndexOf(".");
  if (dot < 1) return null;
  const data = token.slice(0, dot);
  const sigGiven = token.slice(dot + 1);
  const sigExpected = b64url(
    crypto.createHmac("sha256", getSecret()).update(data).digest()
  );
  // constant-time compare
  const a = Buffer.from(sigGiven);
  const b = Buffer.from(sigExpected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  let payload;
  try {
    payload = JSON.parse(b64urlDecode(data).toString("utf8"));
  } catch {
    return null;
  }
  if (!payload || typeof payload !== "object") return null;
  if (typeof payload.e !== "number" || payload.e < Math.floor(Date.now() / 1000)) {
    return null; // expired
  }
  if (typeof payload.u !== "string" || !payload.u) return null;
  return payload;
}

function parseCookies(req) {
  const header = req.headers && (req.headers.cookie || req.headers.Cookie);
  if (!header) return {};
  const out = {};
  for (const piece of header.split(";")) {
    const eq = piece.indexOf("=");
    if (eq < 0) continue;
    const k = piece.slice(0, eq).trim();
    const v = piece.slice(eq + 1).trim();
    if (k) out[k] = decodeURIComponent(v);
  }
  return out;
}

function buildCookie(token, { clear = false } = {}) {
  const parts = [
    `${COOKIE_NAME}=${clear ? "" : token}`,
    "Path=/",
    "HttpOnly",
    "Secure",
    "SameSite=Lax",
  ];
  if (clear) {
    parts.push("Max-Age=0");
  } else {
    parts.push(`Max-Age=${SESSION_TTL_SECONDS}`);
  }
  return parts.join("; ");
}

async function checkPassword(password) {
  const hash = getAccessHash();
  if (!hash) {
    await bcrypt.compare(password || "x", "$2a$10$" + "a".repeat(53));
    return false;
  }
  return bcrypt.compare(password, hash);
}

function issueToken() {
  const exp = Math.floor(Date.now() / 1000) + SESSION_TTL_SECONDS;
  return sign({ u: "member", e: exp });
}

function readSession(req) {
  const cookies = parseCookies(req);
  const tok = cookies[COOKIE_NAME];
  if (!tok) return null;
  return verify(tok);
}

module.exports = {
  COOKIE_NAME,
  checkPassword,
  issueToken,
  readSession,
  buildCookie,
};
