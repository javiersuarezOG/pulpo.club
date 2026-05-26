// 404 handler for unknown URLs.
//
// Before this function existed, vercel.json's catch-all rewrite
// `/:slug([A-Za-z0-9_-]+) → /web/dist/index.html` returned the SPA
// shell with HTTP 200 on every unmatched path. Google's soft-404
// detector flagged that as a duplicate-content / soft-404 condition
// (every typo lands on the same "page" content with HTTP 200), which
// kept random typo URLs from being de-indexed and diluted authority on
// the real routes.
//
// This function serves the same shell so the SPA still boots and lands
// the user on home via the SPA's unknown-path fallback in
// web/app/lib/url-routing.ts:142-143, but returns HTTP 404. Google
// then de-indexes the bad path correctly.
//
// Reading the shell from disk is fine perf-wise on Vercel — the function
// is cold-started < a few hundred times/day; once warm, the module-level
// cache means the file is read once per instance lifetime.

const fs = require("fs");
const path = require("path");

let cachedShell = null;
function loadShell() {
  if (cachedShell !== null) return cachedShell;
  try {
    const p = path.join(process.cwd(), "web", "dist", "index.html");
    cachedShell = fs.readFileSync(p, "utf8");
  } catch (e) {
    // Build artifact missing — return a minimal stub so the 404 status
    // still gets through. Should never hit in prod since the build
    // command writes web/dist/index.html before the function is invoked.
    cachedShell =
      "<!doctype html><html><head><title>Not found — Pulpo</title>" +
      "<meta name=\"robots\" content=\"noindex,follow\"></head>" +
      "<body><p>Page not found.</p></body></html>";
  }
  return cachedShell;
}

module.exports = (req, res) => {
  res.setHeader("Content-Type", "text/html; charset=utf-8");
  // Short edge cache so a sudden bad-link spike doesn't slam the
  // function, but new build artifacts propagate within minutes.
  res.setHeader("Cache-Control", "public, max-age=60, s-maxage=300");
  res.statusCode = 404;
  res.end(loadShell());
};
