// GET /go/<code> — per-post Instagram attribution redirector.
//
// Instagram gives us exactly one clickable link (the bio) and deprecated
// per-post link-click / follow / profile-visit metrics (Jan 2025). So the
// platform will never tell us which post drove a signup. This redirector
// is the only source of that truth: a per-post <code> carries the content
// CATEGORY (the psychological lever) and the intended TIER, we stamp them
// as first-touch UTMs, and 302 to the signup surface. web/app/lib/
// campaign.ts::captureCampaignParams then persists those UTMs and the
// signup event (newsletter.signup / webhook.checkout_completed) fires with
// them attached — so PostHog can attribute signup ← post ← category.
//
// Code format:  ig-d<day>-<category>[-<tier>]
//   ig-d217-scarcity          → day 217, lever "scarcity", tier free
//   ig-d217-investment-pro    → day 217, lever "investment", tier pro
//
// Security: the destination is ALWAYS a fixed same-origin path (never
// derived from user input), so this can't be turned into an open redirect.
// An unknown/garbage code degrades to the homepage with a generic ig UTM.

const posthog = require("../_posthog");

// The 7 content categories (Sebas's inspiration sheet — the strategic
// levers the Growth Hacker will learn to route by audience/tier). Kept as
// an allow-list so a malformed code can never inject an arbitrary utm_term.
const CONTENT_CATEGORIES = new Set([
  "scarcity",
  "authority",
  "social_proof",
  "aspiration",
  "investment",
  "transformation",
  "education",
]);

const TIERS = new Set(["free", "pro"]);

// ig-d<day>-<category>[-<tier>].  Category may contain underscores
// (social_proof); the optional trailing -free/-pro is split off first.
const CODE_RE = /^ig-d(\d{1,4})-([a-z_]+)$/;

// Parse + validate a code into its parts, or null if malformed / unknown
// category. Returns { code, day, category, tier }.
function parseCode(raw) {
  if (!raw || typeof raw !== "string") return null;
  const code = raw.trim().toLowerCase();
  // peel an optional tier suffix
  let tier = "free";
  let rest = code;
  for (const t of TIERS) {
    if (code.endsWith(`-${t}`)) {
      tier = t;
      rest = code.slice(0, -(t.length + 1));
      break;
    }
  }
  const m = CODE_RE.exec(rest);
  if (!m) return null;
  const day = parseInt(m[1], 10);
  const category = m[2];
  if (!CONTENT_CATEGORIES.has(category)) return null;
  return { code: rest + (tier === "free" ? "" : `-${tier}`), day, category, tier };
}

// Build the same-origin destination (path + first-touch UTMs). free → the
// homepage email capture; pro → /start (the checkout entry). Both boot
// captureCampaignParams(), so the UTMs persist to sessionStorage and ride
// the eventual signup event.
function buildDestination(parsed) {
  const params = new URLSearchParams({
    utm_source: "instagram",
    utm_medium: "social",
    utm_campaign: "ig_social_brain",
    utm_content: parsed ? parsed.code : "ig-unknown", // identifies the post
    utm_term: parsed ? parsed.category : "unknown", // the lever
  });
  const path = parsed && parsed.tier === "pro" ? "/start" : "/";
  return `${path}?${params.toString()}`;
}

module.exports = async function handler(req, res) {
  // Vercel maps /go/<code> → req.query.code; keep a URL fallback so a raw
  // curl still resolves the param (matches api/l/[token].js).
  let raw = (req.query && req.query.code) || "";
  if (!raw && req.url) {
    const m = req.url.match(/\/go\/([^/?#]+)/);
    if (m) raw = decodeURIComponent(m[1]);
  }

  const parsed = parseCode(raw);
  const destination = buildDestination(parsed);

  // Click counter (unstitched from the eventual signup Person — that
  // linkage happens via the UTMs on the signup event; this just measures
  // per-post click-through). Never blocks the redirect.
  try {
    posthog.capture("server:ig-router", "ig.link_clicked", {
      code: parsed ? parsed.code : raw.slice(0, 64),
      day: parsed ? parsed.day : null,
      category: parsed ? parsed.category : null,
      tier: parsed ? parsed.tier : null,
      valid: Boolean(parsed),
    });
    await posthog.flush();
  } catch (err) {
    console.warn(`[ig-router] telemetry failed (non-fatal): ${err && err.message}`);
  }

  // 302 (not 301): must not be cached, so every click counts and we can
  // re-route later without a stale browser cache.
  res.statusCode = 302;
  res.setHeader("Location", destination);
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Content-Type", "text/plain; charset=utf-8");
  res.end(`Redirecting to ${destination}`);
};

// Exported for unit tests (pure, no I/O).
module.exports.parseCode = parseCode;
module.exports.buildDestination = buildDestination;
module.exports.CONTENT_CATEGORIES = CONTENT_CATEGORIES;
