// GET /api/admin/newsletter/health
//
// Per-template deliverability health for the /admin/newsletter widget.
// One server-side HogQL query aggregates the last 7 days of dispatch
// events, bucketed into one row per template family:
//
//   Pro · Weekly         newsletter.send_succeeded/_failed  (tier=pro/agency)
//   Free · Weekly        newsletter.send_succeeded/_failed  (tier=free/anon)
//   Pro · Welcome        newsletter.welcome_sent/_skipped/_failed
//   Pro · Welcome-back   newsletter.welcome_back_sent/_skipped/_failed
//   Free · Welcome       newsletter.free_welcome_sent/_skipped/_failed
//   Free · Welcome-back  newsletter.free_welcome_back_sent/_skipped/_failed (+ _dispatched)
//   Activation           email.invitation.sent
//
// Per row: { sent, skipped, failed, last_sent_at, dry_run } so the widget
// can render a status dot — green (sending), amber (only dry-run / only
// skips / idle), red (failures). `dry_run` true means the pipeline ran but
// PULPO_NEWSLETTER_DRY_RUN gated the real send (deployed, not yet live).
//
// Read path mirrors ./recent-triggers.js: auth-light (no PII in the
// aggregate — only counts), rate-limited, graceful-degrades to
// { unavailable_reason } when the PostHog read env vars are missing.

const { makeRateLimiter, send429, ipFromRequest } = require("../../_rate_limit");

const POSTHOG_HOST = (process.env.POSTHOG_HOST || "https://eu.posthog.com").trim();
const WINDOW_DAYS = 7;

// event → { family, bucket }. send_succeeded/_failed are split by tier in
// the bucketer below (one event, two families).
const SENT = "sent", SKIPPED = "skipped", FAILED = "failed";
const EVENT_MAP = {
  "newsletter.welcome_sent":              { family: "pro-welcome",       bucket: SENT },
  "newsletter.welcome_skipped":           { family: "pro-welcome",       bucket: SKIPPED },
  "newsletter.welcome_failed":            { family: "pro-welcome",       bucket: FAILED },
  "newsletter.welcome_back_sent":         { family: "pro-welcome-back",  bucket: SENT },
  "newsletter.welcome_back_skipped":      { family: "pro-welcome-back",  bucket: SKIPPED },
  "newsletter.welcome_back_failed":       { family: "pro-welcome-back",  bucket: FAILED },
  "newsletter.free_welcome_sent":         { family: "free-welcome",      bucket: SENT },
  "newsletter.free_welcome_skipped":      { family: "free-welcome",      bucket: SKIPPED },
  "newsletter.free_welcome_failed":       { family: "free-welcome",      bucket: FAILED },
  "newsletter.free_welcome_back_sent":    { family: "free-welcome-back", bucket: SENT },
  "newsletter.free_welcome_back_dispatched": { family: "free-welcome-back", bucket: SENT },
  "newsletter.free_welcome_back_skipped": { family: "free-welcome-back", bucket: SKIPPED },
  "newsletter.free_welcome_back_failed":  { family: "free-welcome-back", bucket: FAILED },
  "email.invitation.sent":                { family: "activation",        bucket: SENT },
  // send_succeeded/_failed handled separately (tier split).
};

// Template families, in display order. label is the admin-card label.
const FAMILIES = [
  { id: "pro-weekly",        label: "Pro · Weekly" },
  { id: "free-weekly",       label: "Free · Weekly" },
  { id: "pro-welcome",       label: "Pro · Welcome" },
  { id: "pro-welcome-back",  label: "Pro · Welcome-back" },
  { id: "free-welcome",      label: "Free · Welcome" },
  { id: "free-welcome-back", label: "Free · Welcome-back" },
  { id: "activation",        label: "Activation" },
];

const QUERY_EVENTS = [
  ...Object.keys(EVENT_MAP),
  "newsletter.send_succeeded",
  "newsletter.send_failed",
];

const limiter = makeRateLimiter({
  windowMs: 60 * 1000,
  maxAttempts: 30,
  name: "admin_newsletter_health",
});

function logApi(name, fields) {
  const parts = ["[api]", name];
  for (const [k, v] of Object.entries(fields)) parts.push(`${k}=${v}`);
  console.log(parts.join(" "));
}

function blankRow() {
  return { sent: 0, skipped: 0, failed: 0, last_sent_at: null, dry_run: null };
}

// dry_run from PostHog can be boolean true/false or the strings "true"/"1".
function isDryTrue(v) {
  return v === true || v === "true" || v === "1" || v === 1;
}

module.exports = async (req, res) => {
  const t0 = Date.now();
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const rl = limiter.hit(ipFromRequest(req));
  if (!rl.allowed) {
    logApi("admin.newsletter_health", { status: 429, ms: Date.now() - t0 });
    return send429(res, rl, "admin_newsletter_health");
  }

  const families = {};
  for (const f of FAMILIES) families[f.id] = { ...f, ...blankRow() };

  const apiKey = (process.env.POSTHOG_PERSONAL_API_KEY || "").trim();
  const projectId = (process.env.POSTHOG_PROJECT_ID || "").trim();
  if (!apiKey || !projectId) {
    logApi("admin.newsletter_health", {
      status: 200, ms: Date.now() - t0, reason: "env_missing",
      key: apiKey ? "ok" : "missing", project: projectId ? "ok" : "missing",
    });
    return res.status(200).json({
      window_days: WINDOW_DAYS,
      families: Object.values(families),
      unavailable_reason: !apiKey
        ? "POSTHOG_PERSONAL_API_KEY not set in Vercel env — health unavailable."
        : "POSTHOG_PROJECT_ID not set in Vercel env — health unavailable.",
    });
  }

  // One aggregate pass: count + last-timestamp per (event, tier, dry_run).
  // tier + dry_run only carry meaning on send_succeeded/_failed but are
  // harmless (null) on the others.
  const inList = QUERY_EVENTS.map((e) => `'${e}'`).join(", ");
  const hogql = `
    SELECT
      event,
      properties.tier AS tier,
      properties.dry_run AS dry_run,
      count() AS n,
      max(timestamp) AS last_at
    FROM events
    WHERE event IN (${inList})
      AND timestamp > now() - INTERVAL ${WINDOW_DAYS} DAY
    GROUP BY event, tier, dry_run
  `.trim();

  let ph;
  try {
    ph = await fetch(`${POSTHOG_HOST}/api/projects/${encodeURIComponent(projectId)}/query/`, {
      method: "POST",
      headers: { "Authorization": `Bearer ${apiKey}`, "Content-Type": "application/json" },
      body: JSON.stringify({ query: { kind: "HogQLQuery", query: hogql } }),
    });
  } catch (err) {
    logApi("admin.newsletter_health", { status: 502, ms: Date.now() - t0, reason: "posthog_fetch_failed" });
    return res.status(502).json({ error: "posthog_query_failed", detail: (err && err.message) || "" });
  }
  if (!ph.ok) {
    const detail = await ph.text().catch(() => "");
    logApi("admin.newsletter_health", { status: ph.status, ms: Date.now() - t0, reason: "posthog_non_2xx" });
    return res.status(ph.status).json({ error: "posthog_query_rejected", posthog_status: ph.status, detail: detail.slice(0, 300) });
  }

  const payload = await ph.json().catch(() => null);
  const columns = Array.isArray(payload?.columns) ? payload.columns : [];
  const rows = Array.isArray(payload?.results) ? payload.results : [];
  const idx = (name) => columns.indexOf(name);
  const iEvent = idx("event"), iTier = idx("tier"), iDry = idx("dry_run"), iN = idx("n"), iLast = idx("last_at");

  // Track, per family, whether ANY counted "sent" row was a real (non-dry)
  // send. A family is dry_run=true only if it had sends and ALL were dry.
  const sentSeen = {}, realSentSeen = {};
  for (const f of FAMILIES) { sentSeen[f.id] = false; realSentSeen[f.id] = false; }

  for (const row of rows) {
    const event = row[iEvent];
    const tier = (row[iTier] || "").toString().toLowerCase();
    const dry = row[iDry];
    const n = Number(row[iN]) || 0;
    const lastAt = row[iLast] || null;

    // Resolve the family + bucket.
    let famId = null, bucket = null;
    if (event === "newsletter.send_succeeded" || event === "newsletter.send_failed") {
      if (tier === "pro" || tier === "agency") {
        famId = "pro-weekly";
      } else if (tier === "free" || tier === "anon" || tier === "anonymous") {
        famId = "free-weekly";
      } else {
        // Unknown / missing tier — do NOT silently default to Free. That
        // bucketed tier-less send_failed events under Free · Weekly and hid
        // failed Pro campaigns (launch audit P1). Attribute the ambiguous
        // event to Pro · Weekly so a mis-tagged failure surfaces on the
        // high-stakes family instead of vanishing. The producer now always
        // stamps tier (scripts/send_newsletter.py), so this branch is a
        // belt-and-suspenders for legacy/malformed events only.
        famId = "pro-weekly";
      }
      bucket = event === "newsletter.send_failed" ? FAILED : SENT;
    } else {
      const m = EVENT_MAP[event];
      if (!m) continue;
      famId = m.family; bucket = m.bucket;
    }
    const fam = families[famId];
    if (!fam) continue;

    fam[bucket] += n;
    if (bucket === SENT) {
      sentSeen[famId] = true;
      if (!isDryTrue(dry)) realSentSeen[famId] = true;
      if (lastAt && (!fam.last_sent_at || lastAt > fam.last_sent_at)) fam.last_sent_at = lastAt;
    }
  }

  for (const f of FAMILIES) {
    // dry_run flag: true only when there were sends and none were real.
    families[f.id].dry_run = sentSeen[f.id] ? !realSentSeen[f.id] : null;
  }

  logApi("admin.newsletter_health", { status: 200, ms: Date.now() - t0, families: FAMILIES.length });
  res.setHeader("Cache-Control", "private, max-age=20");
  return res.status(200).json({ window_days: WINDOW_DAYS, families: Object.values(families) });
};
