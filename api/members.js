// GET /api/members  -> 200 [full ranked listings]   if cookie valid
//                   -> 401 { error: "auth_required" }   otherwise
//
// This is the only path that ever serves the full ranked.json (broker
// contact, exact prices, source URLs). Everything else uses the public
// teaser bundle.

const fs = require("fs");
const path = require("path");
const { readSession } = require("./_auth");

let cachedJson = null;
let cachedMtimeMs = 0;

function loadFull() {
  // ranked.json sits at /web/data/ranked.json relative to repo root.
  // On Vercel, the function bundle includes the repo so __dirname is /var/task/api.
  const candidates = [
    path.join(__dirname, "..", "web", "data", "ranked.json"),
    path.join(process.cwd(), "web", "data", "ranked.json"),
  ];
  for (const p of candidates) {
    try {
      const stat = fs.statSync(p);
      if (cachedJson && cachedMtimeMs === stat.mtimeMs) return cachedJson;
      const text = fs.readFileSync(p, "utf8");
      cachedJson = JSON.parse(text);
      cachedMtimeMs = stat.mtimeMs;
      return cachedJson;
    } catch (_) { /* try next */ }
  }
  return null;
}

module.exports = async (req, res) => {
  const session = readSession(req);
  if (!session) {
    return res.status(401).json({ error: "auth_required" });
  }

  const data = loadFull();
  if (!data) {
    return res.status(503).json({ error: "data_unavailable" });
  }

  // Members API is dynamic; we don't want CDN caching the privileged payload.
  res.setHeader("Cache-Control", "private, no-store");
  return res.status(200).json({
    user: session.u,
    listings: data,
  });
};
