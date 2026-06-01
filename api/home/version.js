// GET /api/home/version
//
// Returns the per-block version registry for the home page, sourced
// directly from `web/app/home/versions.json` at request time. That JSON
// file is the single source of truth — frontend components and this
// endpoint both read the same data so they can never drift.
//
// Why this exists: each home block (hero, shoreline, the six Top-10
// shelves, etc.) evolves on its own cadence. Knowing which version a
// user saw matters for analytics (A/B comparisons, "users on hero_v5
// converted X% higher"), drift detection (CI compares the deployed
// version to the registry to catch component changes that forgot to
// bump VERSION), and debugging (a bug report's screenshot is paired
// with the exact set of block versions that rendered it).
//
// Response shape — mirrors `web/app/home/versions.json` minus the
// internal `_doc` field:
//   {
//     "layout": "v1",
//     "blocks": {
//       "hero": "v4",
//       "hero_v5": "v5",
//       "featured": "v1",
//       "usps": "v1",
//       "shoreline": "v2",
//       "top_beach_terrenos": "v1", ...
//     }
//   }
//
// Cache: Cache-Control: public, max-age=300. Block versions change at
// most a few times per month; 5 minutes is generous and keeps the
// endpoint cheap. A hard refresh or 5-minute wait is acceptable after
// a version bump.
//
// Degraded mode: if versions.json can't be read (deployment drift,
// path mismatch) we return 500 + a diagnostic field, never a
// silently-empty payload (downstream consumers should fail loud, not
// render with "unknown" everywhere).

const fs = require("fs");
const path = require("path");

const VERSIONS_PATH = path.join(
  process.cwd(),
  "web",
  "app",
  "home",
  "versions.json",
);

function logApi(fields) {
  const parts = ["[api]", "home.version"];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    logApi({ status: 405, ms: Date.now() - t0, reason: "method" });
    return res.status(405).json({ error: "method_not_allowed" });
  }

  let raw;
  try {
    raw = fs.readFileSync(VERSIONS_PATH, "utf8");
  } catch (err) {
    logApi({
      status: 500,
      ms: Date.now() - t0,
      reason: "versions_unreadable",
      err_code: err.code || "unknown",
    });
    return res.status(500).json({
      error: "home_version_unavailable",
      diagnostic: `Could not read ${VERSIONS_PATH} — deployment drift?`,
    });
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    logApi({
      status: 500,
      ms: Date.now() - t0,
      reason: "versions_json_invalid",
      err_message: err.message,
    });
    return res.status(500).json({
      error: "home_version_unavailable",
      diagnostic: "versions.json failed to parse",
    });
  }

  // Strip the internal _doc field — it's documentation for editors of
  // the JSON file, not API consumers.
  const { _doc: _ignored, ...payload } = parsed;

  res.setHeader("Cache-Control", "public, max-age=300, s-maxage=300");
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  logApi({
    status: 200,
    ms: Date.now() - t0,
    blocks: Object.keys(payload.blocks || {}).length,
    layout: payload.layout || "unknown",
  });
  return res.status(200).json(payload);
};
