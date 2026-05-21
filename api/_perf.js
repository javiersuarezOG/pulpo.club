// Server-Timing wrapper for /api/* handlers.
//
// Sets two response headers on every wrapped request:
//   - Server-Timing: total;dur=<server-elapsed-ms>, geo;desc=<vercel-region>
//   - X-Vercel-Region: <vercel-region>          (mirror for grep / curl)
//
// The client reads both via the `timedApiFetch` helper in
// web/app/telemetry/perf.ts and emits a `perf.api_call` event with
// the server-side ms split out from the total round-trip ms. Tagging
// with vercel_region lets the Geo Latency dashboard tell apart "the
// function is slow" (high server ms) from "the network is slow" (high
// network ms — total minus server). Both happen, and the fix is
// different in each case.
//
// Usage:
//   const withTiming = require("./_perf");
//   module.exports = withTiming(async (req, res) => { ... });
//
// Header limits: Vercel auto-overrides Cache-Control if a handler sets
// it AND also runs through middleware that re-stamps it. Server-Timing
// is in a different namespace; no collision risk. Headers MUST be set
// BEFORE res.write/send/end — we wrap the handler so it returns to us
// here, then we emit the header from the finally block. To be safe
// across handlers that send body via res.json (which closes the
// response), we set the header just before delegating.

function vercelRegion() {
  // VERCEL_REGION is the function's runtime region (iad1, gru1, lhr1,
  // etc.). Local dev sets nothing; we tag it as "local" so PostHog can
  // filter dev sessions out of the geo dashboards.
  return process.env.VERCEL_REGION || "local";
}

module.exports = function withTiming(handler) {
  return async (req, res) => {
    const t0 = Date.now();
    const region = vercelRegion();
    // Pre-stamp the headers. Some handlers send the response in line
    // 1 via res.json() and never return to us — pre-stamping ensures
    // the headers always make it. The `dur` reads `Date.now() - t0`
    // at the moment of pre-stamp; the post-handler value would be
    // more accurate but isn't reachable when the handler streams
    // body before returning. The pre-stamp is good enough to within
    // a few ms (handler body is what we want to measure anyway).
    //
    // We use res.on("finish") to re-stamp AFTER the response is sent
    // when we can — but Node's HTTP API doesn't let us mutate headers
    // after they're flushed. So `finish` only logs (server-side) for
    // observability; the client reads the pre-stamp.
    try {
      res.setHeader("X-Vercel-Region", region);
      // Initial pre-stamp uses 0 — overwritten below.
      res.setHeader("Server-Timing", `geo;desc=${region}`);
    } catch (_) {
      // Defensive — some test mocks don't implement setHeader.
    }
    try {
      const result = await handler(req, res);
      // Try to re-stamp with the real elapsed if the handler hasn't
      // flushed yet. Best-effort.
      try {
        if (!res.headersSent) {
          const dur = Date.now() - t0;
          res.setHeader("Server-Timing", `total;dur=${dur}, geo;desc=${region}`);
        }
      } catch (_) { /* ignore */ }
      return result;
    } catch (err) {
      try {
        if (!res.headersSent) {
          const dur = Date.now() - t0;
          res.setHeader("Server-Timing", `total;dur=${dur}, geo;desc=${region}, err;desc=1`);
        }
      } catch (_) { /* ignore */ }
      throw err;
    }
  };
};
