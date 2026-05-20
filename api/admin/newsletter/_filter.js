// Newsletter filter logic — Node port of automation/newsletter/segments.py.
//
// Why a port: the production pipeline is Python (build_issue + render_html),
// but Vercel Node functions don't have Python at runtime. For the admin
// widget's fast iteration loop we re-implement the FILTER step here. The
// admin email is clearly tagged `[PULPO ADMIN TEST]` so its rendered HTML
// won't be confused with the production newsletter (which uses the real
// renderer via the existing pulpo-newsletter GH Actions workflow).
//
// Keep this file in sync with segments.py's CATEGORY_PREDICATES + the
// apply_preference + select_picks logic. If we extend the production
// pipeline, mirror the change here.

const fs = require("fs");
const path = require("path");

let cachedJson = null;
let cachedMtimeMs = 0;

function loadRanked() {
  const candidates = [
    path.join(__dirname, "..", "..", "..", "web", "data", "ranked.json"),
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

// Newsletter cohorts — Node mirror of the Cohort literal in
// automation/newsletter/types.py. Imported by preview.js + send.js so
// validation has a single source on the Node side. The TS counterpart
// at web/app/admin/widgets/newsletter/constants.ts is asserted to
// match this list by tests/api/admin_newsletter_filter.test.js, and
// types.py vs constants.ts is asserted by
// tests/test_newsletter_constants_sync.py. Both directions guarded.
const NEWSLETTER_COHORTS = ["pro_prefs", "free_prefs", "logged_no_prefs", "anonymous"];

// Mirror of CATEGORY_PREDICATES in automation/newsletter/segments.py.
const CATEGORY_PREDICATES = {
  beachfront:        (l) => !!l.is_beachfront || !!l.is_walk_to_beach,
  water_features:    (l) => !!l.has_water_body || !!l.is_beachfront,
  ocean_view:        (l) => !!l.has_ocean_view,
  mountain_view:     (l) => !!l.has_mountain_view,
  flat_buildable:    (l) => !!l.is_flat && !!l.has_paved_access,
  build_ready:       (l) => !!l.has_power && !!l.has_water,
  commercial:        (l) => !!l.is_commercial,
  agricultural:      (l) => !!l.is_agricultural,
  under_50k:         (l) => (l.price_usd ?? 1e12) < 50_000,
  under_100k:        (l) => (l.price_usd ?? 1e12) < 100_000,
  price_drops:       (l) => !!l.is_repriced,
  motivated_sellers: (l) => !!l.is_motivated,
};

function normalizePreference(input) {
  const p = (input && typeof input === "object") ? input : {};
  const arr = (v) => Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  const num = (v) => (typeof v === "number" && Number.isFinite(v)) ? v : null;
  return {
    zones: arr(p.zones),
    departments: arr(p.departments),
    property_types: arr(p.property_types),
    categories: arr(p.categories),
    min_price_usd: num(p.min_price_usd),
    max_price_usd: num(p.max_price_usd),
  };
}

function applyPreference(listings, pref) {
  const zoneSet = new Set(pref.zones);
  const deptSet = new Set(pref.departments.map((d) => d.toLowerCase()));
  const typeSet = new Set(pref.property_types);
  const cats = pref.categories
    .map((k) => CATEGORY_PREDICATES[k])
    .filter(Boolean);

  const kept = [];
  for (const l of listings) {
    if (zoneSet.size && !zoneSet.has(l.zone)) continue;
    if (deptSet.size) {
      const d = (l.department || "").toLowerCase();
      if (!deptSet.has(d)) continue;
    }
    if (typeSet.size && !typeSet.has(l.property_type)) continue;
    const p = l.price_usd;
    if (pref.max_price_usd != null && p != null && p > pref.max_price_usd) continue;
    if (pref.min_price_usd != null && p != null && p < pref.min_price_usd) continue;
    if (cats.length && !cats.every((fn) => fn(l))) continue;
    kept.push(l);
  }
  return kept;
}

// Re-derive cohort gating in JS — must match build_issue.detect_cohort
// behaviour for the `paywall_all` flag and the fallback preference
// branching. We don't have a Recipient dataclass; the admin caller
// passes `cohort` directly so we trust it.
function paywallForCohort(cohort) {
  // `free_prefs` and free-no-prefs flows paywall picks #2+. Pro/agency
  // see all. anonymous gets a welcome flavour but no paywall by default.
  return cohort === "free_prefs";
}

function pickLocale(field, locale) {
  if (!field || typeof field !== "object") return null;
  return field[locale] ?? field.en ?? null;
}

function selectPicks(filtered, topN = 10) {
  // Filter is already sorted ascending by rank when ranked.json is sorted.
  // We slice top-N + a tiny skip-candidate pool — admin preview doesn't
  // need history-aware exclusion since we never wrote a send record.
  const kept = filtered.slice(0, topN);
  const skipCandidates = filtered
    .slice(topN, topN + 5)
    .filter((l) => (l.days_listed ?? 0) >= 90 || (l.data_quality_score ?? 1) < 0.55);
  return { kept, skipCandidates };
}

module.exports = {
  loadRanked,
  normalizePreference,
  applyPreference,
  selectPicks,
  paywallForCohort,
  pickLocale,
  CATEGORY_PREDICATES,
  NEWSLETTER_COHORTS,
};
