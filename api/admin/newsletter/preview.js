// POST /api/admin/newsletter/preview
//
// Body: { cohort, locale, issue_number, preference: { zones, departments,
//         property_types, categories, min_price_usd, max_price_usd } }
//
// Filters web/data/ranked.json using the same logic as automation/
// newsletter/segments.py (re-implemented in Node — see _filter.js) and
// returns a rendered HTML preview plus a trace of which filter values
// were actually applied. The preview HTML is a simplified admin-only
// template (see _render.js) — not byte-identical to the production
// newsletter renderer.
//
// No auth (the /admin page is open by design). No emails are sent.
//
// Response: { html, picks_total, total_listings, cohort, filter_trace }

const { loadRanked, normalizePreference, applyPreference, selectPicks } = require("./_filter");
const { renderAdminIssue } = require("./_render");

const COHORTS = new Set(["pro_prefs", "free_prefs", "logged_no_prefs", "anonymous"]);
const LOCALES = new Set(["en", "es"]);

async function readJsonBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  try {
    const chunks = [];
    for await (const chunk of req) chunks.push(typeof chunk === "string" ? Buffer.from(chunk) : chunk);
    const raw = Buffer.concat(chunks).toString("utf8");
    if (!raw) return {};
    return JSON.parse(raw);
  } catch {
    return {};
  }
}

module.exports = async (req, res) => {
  if (req.method !== "POST") {
    res.setHeader("Allow", "POST");
    return res.status(405).json({ error: "method_not_allowed" });
  }
  const body = await readJsonBody(req);

  const cohort = COHORTS.has(body.cohort) ? body.cohort : "pro_prefs";
  const locale = LOCALES.has(body.locale) ? body.locale : "en";
  const issueNumber = Number.isInteger(body.issue_number) && body.issue_number > 0
    ? body.issue_number
    : 1;
  const preference = normalizePreference(body.preference);

  const data = loadRanked();
  if (!data || !Array.isArray(data)) {
    return res.status(503).json({ error: "ranked_not_available" });
  }
  // ranked.json may arrive unsorted depending on the producer; force
  // ascending rank order so the slice is deterministic.
  const sorted = [...data].sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999));

  const filtered = applyPreference(sorted, preference);
  const { kept } = selectPicks(filtered, 10);

  const html = renderAdminIssue({
    picks: kept,
    cohort,
    locale,
    issueNumber,
    filterTrace: preference,
  });

  return res.status(200).json({
    html,
    picks_total: kept.length,
    total_listings: data.length,
    cohort,
    filter_trace: preference,
  });
};
