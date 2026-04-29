// POST /api/login   { username, password }   -> 200 { ok: true } + Set-Cookie
// GET  /api/login                             -> 405
//
// Rate-limit-light: bcrypt itself is the rate limit (cost 10 ≈ 100ms/attempt).
// If brute-force becomes a real concern, front this with Vercel's edge rate
// limiter or upstash. Not worth the complexity at <50 users.

const { checkPassword, issueToken, buildCookie } = require("./_auth");

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  let body = req.body;
  // Vercel auto-parses JSON when content-type is application/json, but the
  // browser fetch in our dashboard sets it explicitly so this is the common path.
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { body = {}; }
  }
  body = body || {};
  const username = (body.username || "").toString().trim().toLowerCase();
  const password = (body.password || "").toString();

  if (!username || !password) {
    return res.status(400).json({ error: "missing_credentials" });
  }

  const ok = await checkPassword(username, password);
  if (!ok) {
    // Generic message — don't leak which half was wrong.
    return res.status(401).json({ error: "invalid_credentials" });
  }

  const token = issueToken(username);
  res.setHeader("Set-Cookie", buildCookie(token));
  return res.status(200).json({ ok: true, username });
};
