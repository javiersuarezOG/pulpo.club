// GET /api/social/image — public on-demand resizer for Meta's Graph API.
//
// Meta fetches images server-side without our secret, so this endpoint is intentionally public.
// It is content-addressed (id + ratio) and the underlying hero JPEGs are immutable per source_id,
// so we cache aggressively at the edge.
//
// Query params:
//   id      "<source>__<source_id>"   required
//   ratio   "1:1" | "4:5"             default "1:1"
//
// Output dimensions: 1080x1080 (1:1) or 1080x1350 (4:5). Format: JPEG, quality 85.
//
// Candidate-resolution order (plan v2):
//   1. <file>.hires.jpg  — broker native resolution. Skipped when a
//      .quarantine marker exists or PULPO_HIRES_SERVE=0.
//   2. <file>.hero.jpg   — legacy 1920x1080 derivative.
//   3. <file>.jpg        — legacy 600x400 thumbnail.
// First existing candidate wins. The X-Pulpo-Image-Source response header
// reports which tier served the response so operators (and pulpo-social's
// photo gate logs) can audit coverage in production.
//
// ── Storage model (2026-05-19, after PR #312 size cliff) ──────────────
// Photos are NOT bundled into the serverless function. Vercel's Node File
// Tracer would otherwise include all of web/photos/ (~250 MB) and
// web/photos-hires/ (~600 MB) into this function's bundle, exceeding the
// hard 300 MB Vercel function-size limit. Instead, web/photos/** and
// web/photos-hires/** are deployed as STATIC assets (see vercel.json
// rewrites + functions.excludeFiles for this file) and fetched from the
// deployment's own CDN URL at request time. ~50 ms RTT per fetch — paid
// in full to the Vercel edge cache so warm callers see no penalty after
// the first hit per (id, ratio).

const sharp = require("sharp");

const SIZES = {
  "1:1": { width: 1080, height: 1080 },
  "4:5": { width: 1080, height: 1350 },
};

const HIRES_SERVE_DISABLED = process.env.PULPO_HIRES_SERVE === "0";

// Resolve the CDN base URL to fetch deployed static assets from.
// PULPO_PUBLIC_BASE_URL takes precedence when set (lets local `vercel dev`
// or non-Vercel hosts override). Default is the production alias — the
// only URL guaranteed NOT to be behind Vercel Deployment Protection (SSO).
//
// VERCEL_URL deliberately NOT used here: it resolves to the
// deployment-specific URL (e.g. `pulpo-club-abc.vercel.app`) which
// Vercel auto-protects with SSO on this project. The function fetching
// its own deployment URL gets a 401 SSO challenge, the response isn't
// a JPEG, and every tier in resolveImage() falls through → 404.
// Diagnosed via debug deploy on PR #315 / branch
// fix/api-social-image-debug (2026-05-19 15:14 UTC).
function cdnBaseUrl() {
  if (process.env.PULPO_PUBLIC_BASE_URL) return process.env.PULPO_PUBLIC_BASE_URL;
  return "https://pulpo.club";
}

// Single GET against the deployment CDN. Returns the Buffer on 200, null
// on any other status (including 404). Caller treats null as "this tier
// is missing; try the next one." Errors don't propagate — the next tier
// is just as valid a code path as a missing file would have been when we
// used fs.readFileSync.
async function fetchAsset(url) {
  try {
    const resp = await fetch(url);
    if (!resp.ok) return null;
    const arr = await resp.arrayBuffer();
    return Buffer.from(arr);
  } catch (_) {
    return null;
  }
}

// HEAD against the deployment CDN. Returns true when the asset exists,
// false otherwise. Used to check for .quarantine sidecar markers without
// pulling the (potentially large) parent .hires.jpg blob.
async function assetExists(url) {
  try {
    const resp = await fetch(url, { method: "HEAD" });
    return resp.ok;
  } catch (_) {
    return false;
  }
}

async function resolveImage(id) {
  const idx = id.indexOf("__");
  if (idx < 1) return null;
  const source = id.slice(0, idx);
  const sourceId = id.slice(idx + 2);
  // Allow only safe slug chars to prevent path traversal even though
  // these go into a URL not a filesystem path — keeps the API surface
  // identical to the prior fs-based code so callers see no shape change.
  if (!/^[a-z0-9_-]+$/i.test(source) || !/^[a-z0-9_.-]+$/i.test(sourceId)) return null;

  const base = cdnBaseUrl();

  // Tier 1: hires.jpg (broker native, plan v2). Skip when quarantined or
  // when serving is disabled.
  if (!HIRES_SERVE_DISABLED) {
    const hiresName = `${source}_${sourceId}.hires.jpg`;
    const hiresUrl = `${base}/photos-hires/${hiresName}`;
    const quarantined = await assetExists(`${hiresUrl}.quarantine`);
    if (!quarantined) {
      const buf = await fetchAsset(hiresUrl);
      if (buf) return { buffer: buf, source: "hires" };
    }
  }

  // Tier 2: legacy hero.jpg.
  const heroUrl = `${base}/photos/${source}_${sourceId}.hero.jpg`;
  const heroBuf = await fetchAsset(heroUrl);
  if (heroBuf) return { buffer: heroBuf, source: "hero" };

  // Tier 3: legacy thumbnail.
  const thumbUrl = `${base}/photos/${source}_${sourceId}.jpg`;
  const thumbBuf = await fetchAsset(thumbUrl);
  if (thumbBuf) return { buffer: thumbBuf, source: "jpg" };

  return null;
}

module.exports = async (req, res) => {
  const id = (req.query.id || "").toString();
  const ratio = (req.query.ratio || "1:1").toString();
  const size = SIZES[ratio];
  if (!id || !size) {
    return res.status(400).json({ error: "bad_request", detail: "id and ratio=1:1|4:5 required" });
  }
  const resolved = await resolveImage(id);
  if (!resolved) {
    return res.status(404).json({ error: "not_found" });
  }
  try {
    // Refuse to upscale: sources below the requested canonical dimensions
    // produce visibly pixelated 1080-wide outputs (see pulpo-social photo-gate
    // Round 1 diagnostic — every passer in the 50-listing cohort was a 3x
    // upscale of a 600x400 thumbnail). The contract requires Meta-sized
    // images, so we 404 here and let pre-filters (e.g. pulpo-social's
    // source_width/source_height check) skip these listings before request.
    const meta = await sharp(resolved.buffer).metadata();
    if ((meta.width ?? 0) < size.width || (meta.height ?? 0) < size.height) {
      return res.status(404).json({
        error: "source_too_small",
        detail: `source ${meta.width}x${meta.height} is below target ${size.width}x${size.height}; refuse to upscale`,
      });
    }
    const buf = await sharp(resolved.buffer)
      .resize(size.width, size.height, { fit: "cover", position: "attention", withoutEnlargement: true })
      .jpeg({ quality: 85, mozjpeg: true })
      .toBuffer();
    res.setHeader("Content-Type", "image/jpeg");
    res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    res.setHeader("Content-Length", buf.length);
    // Observability: which derivative actually served this response.
    // Visible in pulpo-social photo-gate logs + browser devtools.
    res.setHeader("X-Pulpo-Image-Source", resolved.source);
    return res.status(200).send(buf);
  } catch (err) {
    return res.status(500).json({ error: "resize_failed", detail: String(err && err.message) });
  }
};
