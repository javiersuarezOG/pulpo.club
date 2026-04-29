// POST /api/logout  -> clear cookie, 200
const { buildCookie } = require("./_auth");

module.exports = async (req, res) => {
  res.setHeader("Set-Cookie", buildCookie("", { clear: true }));
  return res.status(200).json({ ok: true });
};
