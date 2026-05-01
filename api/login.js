// POST /api/login   { code }   -> 200 { ok: true } + Set-Cookie
// GET  /api/login              -> 405

const { checkPassword, issueToken, buildCookie } = require("./_auth");

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  let body = req.body;
  if (typeof body === "string") {
    try { body = JSON.parse(body); } catch { body = {}; }
  }
  body = body || {};
  const code = (body.code || "").toString();

  if (!code) {
    return res.status(400).json({ error: "missing_code" });
  }

  const ok = await checkPassword(code);
  if (!ok) {
    return res.status(401).json({ error: "invalid_code" });
  }

  const token = issueToken();
  res.setHeader("Set-Cookie", buildCookie(token));
  return res.status(200).json({ ok: true });
};
