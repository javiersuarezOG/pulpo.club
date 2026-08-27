// api/v1/_http.js — the small HTTP helpers every v1 handler uses.
//
// CommonJS, like every other function in this repo. Not a style choice:
// Vercel compiles TypeScript functions only for files inside api/, and
// that restriction is TRANSITIVE — nothing in a .ts function's
// dependency graph may reach outside api/ at any depth. Since these
// handlers need the shared core, they cannot be TypeScript. See
// docs/api-v1.md for the probe table that established this.
//
// The logic worth type-checking lives in shared/, which is still
// TypeScript; these files are HTTP plumbing.

/** 405 with the `Allow` header the repo's other handlers all set. */
function methodNotAllowed(res, allow) {
  res.setHeader("Allow", allow);
  return res.status(405).json({ error: "method_not_allowed" });
}

/** Structured one-line log matching the `[api] <name> k=v` format the
 *  rest of the API emits, so existing log queries keep working. */
function logApi(name, fields) {
  const parts = Object.entries(fields).map(([k, v]) => `${k}=${v}`);
  console.log(`[api] ${name} ${parts.join(" ")}`);
}

module.exports = { methodNotAllowed, logApi };
