// Single source of truth for the newsletter widget's stable enums.
//
// These are mirrored on the server (api/admin/newsletter/_filter.js
// + send.js) and on the Python pipeline side (automation/newsletter/
// types.py for Cohort, web/app/i18n.jsx for LOCALES). Drift between
// them is caught by:
//   - tests/api/admin_newsletter_filter.test.js (Node port vs TS)
//   - tests/test_newsletter_constants_sync.py  (Python pipeline vs TS)
//
// Adding a cohort: edit `NEWSLETTER_COHORTS` here, update the matching
// `Cohort` literal in automation/newsletter/types.py, update the COHORTS
// set in api/admin/newsletter/{preview,send}.js. The pytest + vitest
// guards block the merge until all three sides agree.

import { LOCALES } from "../../../i18n.jsx";

export const NEWSLETTER_COHORTS = [
  "pro_prefs",
  "free_prefs",
  "logged_no_prefs",
  "anonymous",
] as const;

export type NewsletterCohort = typeof NEWSLETTER_COHORTS[number];

// Operator-facing labels. The admin widget itself is EN-only by design
// (see the `// i18n-allow:` markers throughout the admin tree) — these
// are what's shown in the cohort dropdown, not what subscribers see.
export const NEWSLETTER_COHORT_LABEL: Record<NewsletterCohort, string> = {
  pro_prefs:       "Pro + prefs (full picks, no paywall)",
  free_prefs:      "Free + prefs (paywalled below pick #1)",
  logged_no_prefs: "Logged in, no prefs (fallback)",
  anonymous:       "Anonymous email (welcome edition)",
};

// Pulled from i18n.jsx — the only canonical list of locales the app
// supports. Adding "pt", "fr", etc. there auto-extends the widget.
export const NEWSLETTER_LOCALES = LOCALES as readonly string[];

// Property types — currently fetched live from ranked.json by
// /api/admin/newsletter/options. Listed here as the "expected universe"
// for the drift-guard test (mirrors the validation set in
// pulpo/normalize.py and is unlikely to grow).
export const NEWSLETTER_PROPERTY_TYPES = ["land", "house", "condo"] as const;
