// GET /api/admin/newsletter/recent-triggers
//
// Returns the last 20 admin.newsletter_test_triggered events the
// matching POST endpoint (./trigger-preview.js) fired. Powers the
// "Recent test sends" log in the /admin/newsletter widget so every
// operator on any device sees the same history.
//
// Read path is a server-side HogQL query against PostHog. The two
// required env vars are:
//
//   POSTHOG_PERSONAL_API_KEY — personal API key from PostHog → Account →
//                              Personal API keys. Scope: read events.
//   POSTHOG_PROJECT_ID       — numeric project ID from PostHog → Project
//                              settings → General → Project ID.
//
// When EITHER env var is missing, the endpoint returns 200 with
// `{ events: [], unavailable_reason: "..." }` so the widget can fall
// back to its localStorage-only log. The 200 keeps the widget UX
// clean (no error toast on a missing config); the reason string surfaces
// in the response so DevTools makes the missing config visible to the
// operator who's looking for the cross-device feature.
//
// Auth: deliberately none beyond rate-limiting + the read-only event-
// data scope of the personal API key. The trigger-preview POST is the
// same posture; reading its event stream back is no more sensitive.
// Rate limit: 30 reads per IP per minute — light enough that polling
// the widget on every focus event is safe, capped low enough that a
// stuck-loop in the widget can't flood PostHog.

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");

const POSTHOG_HOST = (process.env.POSTHOG_HOST || "https://eu.posthog.com").trim();
const EVENT_NAME = "admin.newsletter_test_triggered";
const EVENT_LIMIT = 20;

const limiter = makeRateLimiter({
  windowMs: 60 * 1000,
  maxAttempts: 30,
  name: "admin_newsletter_recent_triggers",
});

function logApi(name, fields) {
  const parts = ["[api]", name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

module.exports = async (req, res) => {
  const t0 = Date.now();

  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi("admin.newsletter_recent_triggers", { status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_newsletter_recent_triggers");
  }

  const apiKey = (process.env.POSTHOG_PERSONAL_API_KEY || "").trim();
  const projectId = (process.env.POSTHOG_PROJECT_ID || "").trim();
  if (!apiKey || !projectId) {
    // Graceful degrade — the widget falls back to localStorage. The
    // reason is intentionally human-readable: DevTools is the only
    // place a missing-config operator will see it.
    logApi("admin.newsletter_recent_triggers", {
      status: 200, ms: Date.now() - t0, reason: "env_missing",
      key: apiKey ? "ok" : "missing",
      project: projectId ? "ok" : "missing",
    });
    return res.status(200).json({
      events: [],
      unavailable_reason: !apiKey
        ? "POSTHOG_PERSONAL_API_KEY not set in Vercel env — server-side cross-device log unavailable. Falling back to localStorage."
        : "POSTHOG_PROJECT_ID not set in Vercel env — server-side cross-device log unavailable. Falling back to localStorage.",
    });
  }

  // HogQL — read the last N admin.newsletter_test_triggered events.
  // Properties live at the top level of the SELECT so the response
  // shape is the array of column values the widget will map to objects.
  const hogql = `
    SELECT
      timestamp,
      properties.to AS to,
      properties.locale AS locale,
      properties.by AS by,
      properties.result AS result,
      properties.detail AS detail,
      properties.issue_number AS issue_number
    FROM events
    WHERE event = '${EVENT_NAME}'
    ORDER BY timestamp DESC
    LIMIT ${EVENT_LIMIT}
  `.trim();

  let ph;
  try {
    ph = await fetch(`${POSTHOG_HOST}/api/projects/${encodeURIComponent(projectId)}/query/`, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${apiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        query: { kind: "HogQLQuery", query: hogql },
      }),
    });
  } catch (err) {
    logApi("admin.newsletter_recent_triggers", {
      status: 502, ms: Date.now() - t0, reason: "posthog_fetch_failed",
      error: (err && err.message) || "(no message)",
    });
    return res.status(502).json({
      error: "posthog_query_failed",
      detail: (err && err.message) || "(no message)",
    });
  }

  if (!ph.ok) {
    const detail = await ph.text().catch(() => "");
    logApi("admin.newsletter_recent_triggers", {
      status: ph.status, ms: Date.now() - t0, reason: "posthog_non_2xx",
    });
    return res.status(ph.status).json({
      error: "posthog_query_rejected",
      posthog_status: ph.status,
      detail: detail.slice(0, 500),
    });
  }

  const payload = await ph.json().catch(() => null);
  // HogQL returns { columns: [...names], results: [[col1, col2, ...], ...] }
  // — map back to objects so the widget doesn't have to know the column order.
  const columns = Array.isArray(payload?.columns) ? payload.columns : null;
  const rows = Array.isArray(payload?.results) ? payload.results : [];
  const events = columns
    ? rows.map((row) => {
      const out = {};
      for (let i = 0; i < columns.length; i++) {
        out[columns[i]] = row[i];
      }
      return {
        at: out.timestamp || null,
        to: out.to || null,
        locale: out.locale || null,
        by: out.by || null,
        result: out.result || null,
        detail: out.detail || null,
        issue_number: out.issue_number || null,
      };
    })
    : [];

  logApi("admin.newsletter_recent_triggers", {
    status: 200, ms: Date.now() - t0, count: events.length,
  });

  // Tight client-side cache. The log is low-churn (a few triggers a
  // week) but we don't want a stale 30s cache to hide a just-fired
  // test — 5s is enough to coalesce multiple widget mounts on the
  // same page-load.
  res.setHeader("Cache-Control", "private, max-age=5");
  return res.status(200).json({ events });
};
