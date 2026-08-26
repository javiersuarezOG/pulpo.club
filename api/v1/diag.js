// Temporary diagnostic. CommonJS, so it always loads — which lets it
// report why the TypeScript functions do not.
const fs = require("fs");
const path = require("path");

module.exports = (req, res) => {
  const out = { __dirname, cwd: process.cwd(), node: process.version };

  try { out.core = typeof require("../_core.js"); }
  catch (e) { out.coreError = `${e.code || ""} ${e.message}`.trim(); }

  try { out.bundle = Object.keys(require("../../shared/dist/api-core.cjs")).length + " exports"; }
  catch (e) { out.bundleError = `${e.code || ""} ${e.message}`.trim(); }

  for (const rel of ["..", "../..", "../../shared", "../../shared/dist"]) {
    try { out[`ls ${rel}`] = fs.readdirSync(path.join(__dirname, rel)).slice(0, 30); }
    catch (e) { out[`ls ${rel}`] = `ERR ${e.code}`; }
  }
  res.status(200).json(out);
};
