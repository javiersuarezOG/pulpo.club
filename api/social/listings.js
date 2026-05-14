// TODO (Phase 2 backlog, tracked in pulpo-social PRD v2 §4.3):
// Schedule automation/photo_quality.py::detect_text_overlay to run against ALL
// existing listings during the nightly pipeline, not just newly scraped ones.
// Once has_text_overlay is populated for >=90% of ranked.json rows, promote
// the null check in passesQualityGate() from "allow null" to "hard reject null".
//
// GET /api/social/listings — internal endpoint for the pulpo-social automation service.
//
// Bearer-token gated (PULPO_INTERNAL_API_KEY). Reads web/data/ranked.json and returns
// a ranked, locale-projected, quality-gated slice suitable for daily Instagram/Facebook posts.
//
// Query params:
//   limit         integer 1..50      default 10
//   category      string             default "all" — matches property_type (land|house|condo)
//   sort          rank|price_drop|newest               default rank
//   exclude_ids   csv of "<source>__<source_id>"       default empty
//   locale        en|es              default en
//
// Response: { listings: [...], total } — total is the count before limit is applied.

const fs = require("fs");
const path = require("path");

let cachedJson = null;
let cachedMtimeMs = 0;

function loadRanked() {
  const candidates = [
    path.join(__dirname, "..", "..", "web", "data", "ranked.json"),
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
    } catch (_) {
      // try next
    }
  }
  return null;
}

function pickLocale(field, locale) {
  if (!field || typeof field !== "object") return null;
  return field[locale] ?? field.en ?? null;
}

function buildLocation(l) {
  return [l.zone, l.municipality, l.department, l.country]
    .filter((p) => p && typeof p === "string")
    .join(", ");
}

function priceDisplay(priceUsd) {
  if (priceUsd == null) return null;
  return "$" + Number(priceUsd).toLocaleString("en-US");
}

function priceDropPct(l) {
  if (!l.is_repriced) return null;
  const prev = Number(l.previous_price);
  const curr = Number(l.price_usd);
  if (!Number.isFinite(prev) || !Number.isFinite(curr) || prev <= curr) return null;
  return (prev - curr) / prev;
}

function passesQualityGate(l) {
  if (!l.hero_photo_path) return false;
  if (l.price_usd == null) return false;
  // data_quality_score is 0..1 and populated for ~all rows; 0.5 is the production threshold
  // already used by featured_listing.py for the "decent enough to feature" pool.
  if ((l.data_quality_score ?? 0) < 0.5) return false;
  // Soft signals — only reject when explicitly flagged.
  if (l.has_text_overlay === true) return false;
  if (l.hero_photo_quality_score != null && l.hero_photo_quality_score < 50) return false;
  return true;
}

function projectListing(l, locale) {
  const id = `${l.source}__${l.source_id}`;
  const baseUrl = process.env.PULPO_PUBLIC_BASE_URL || "https://pulpo.club";
  return {
    id,
    title: pickLocale(l.title_canonical, locale) || l.title || "",
    description: pickLocale(l.short_description_canonical, locale) || "",
    category: l.property_type || null,
    subcategory: l.land_type || null,
    location: buildLocation(l),
    price_usd: l.price_usd,
    price_display: priceDisplay(l.price_usd),
    rank_score: l.rank_score ?? null,
    price_drop_pct: priceDropPct(l),
    image_url: `${baseUrl}/api/social/image?id=${encodeURIComponent(id)}&ratio=1:1`,
    listing_url: `${baseUrl}/listing/${encodeURIComponent(id)}`,
    quality: {
      hero_photo_quality_score: l.hero_photo_quality_score ?? null,
      has_text_overlay: l.has_text_overlay ?? null,
      data_quality_score: l.data_quality_score ?? null,
    },
    created_at: l.first_seen_at ?? null,
    updated_at: l.enriched_at || l.scraped_at || null,
  };
}

function parsePositiveInt(value, def, max) {
  const n = parseInt(value, 10);
  if (!Number.isFinite(n) || n < 1) return def;
  return Math.min(n, max);
}

module.exports = async (req, res) => {
  // --- auth ---
  const expected = process.env.PULPO_INTERNAL_API_KEY;
  if (!expected) {
    return res.status(503).json({ error: "server_misconfigured" });
  }
  const auth = req.headers.authorization || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7).trim() : null;
  if (!token || token !== expected) {
    return res.status(401).json({ error: "auth_required" });
  }

  const data = loadRanked();
  if (!Array.isArray(data)) {
    return res.status(503).json({ error: "data_unavailable" });
  }

  // --- query params ---
  const limit = parsePositiveInt(req.query.limit, 10, 50);
  const category = (req.query.category || "all").toString().toLowerCase();
  const sort = (req.query.sort || "rank").toString();
  const locale = req.query.locale === "es" ? "es" : "en";
  const excludeRaw = (req.query.exclude_ids || "").toString();
  const excludeSet = new Set(
    excludeRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  );

  // --- filter ---
  let filtered = data.filter(passesQualityGate);
  if (category !== "all") {
    filtered = filtered.filter((l) => (l.property_type || "").toLowerCase() === category);
  }
  if (excludeSet.size > 0) {
    filtered = filtered.filter((l) => !excludeSet.has(`${l.source}__${l.source_id}`));
  }

  // --- sort ---
  if (sort === "price_drop") {
    filtered = filtered
      .map((l) => ({ l, pct: priceDropPct(l) }))
      .filter((x) => x.pct != null)
      .sort((a, b) => b.pct - a.pct)
      .map((x) => x.l);
  } else if (sort === "newest") {
    filtered = filtered.slice().sort((a, b) => {
      const ta = Date.parse(a.first_seen_at || "") || 0;
      const tb = Date.parse(b.first_seen_at || "") || 0;
      return tb - ta;
    });
  } else {
    filtered = filtered
      .filter((l) => typeof l.rank_score === "number")
      .sort((a, b) => b.rank_score - a.rank_score);
  }

  const total = filtered.length;
  const sliced = filtered.slice(0, limit).map((l) => projectListing(l, locale));

  res.setHeader("Cache-Control", "private, max-age=60");
  return res.status(200).json({ listings: sliced, total });
};
