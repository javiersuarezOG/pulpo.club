// POST /api/login   { code }   -> 200 { ok: true } + Set-Cookie
// GET  /api/login              -> 405

const { checkPassword, issueToken, buildCookie } = require("./_auth");

// Grep-able single-line log so Vercel Runtime Logs can be filtered.
// No PII — only request shape + outcome + duration. Real PostHog auth
// events (signup.completed) fire from the FE side.
function logApi(name, { status, ms, extra }) {
  const parts = [`[api]`, name, `status=${status}`, `ms=${ms}`];
  if (extra) {
    for (const [k, v] of Object.entries(extra)) parts.push(`${k}=${v}`);
  }
  console.log(parts.join(" "));
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    logApi("login", { status: 405, ms: Date.now() - t0, extra: { reason: "method" } });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { body = {}; }
  }
  body = body || {};
  const code = (body.code || "").toString();

  if (!code) {
    logApi("login", { status: 400, ms: Date.now() - t0, extra: { reason: "no_code" } });
    return res.status(400).json({ error: "missing_code" });
  }

  const ok = await checkPassword(code);
  if (!ok) {
    logApi("login", { status: 401, ms: Date.now() - t0, extra: { reason: "bad_code" } });
    return res.status(401).json({ error: "invalid_code" });
  }

  const token = issueToken();
  res.setHeader("Set-Cookie", buildCookie(token));
  logApi("login", { status: 200, ms: Date.now() - t0 });
  return res.status(200).json({ ok: true });
};
