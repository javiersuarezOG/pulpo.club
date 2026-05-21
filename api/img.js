// GET /api/img — on-demand image optimizer for listing photos.
//
// Mirrors the storage/fetch pattern from api/social/image.js (photos
// live as static assets at /photos/* and /photos-hires/*; the function
// fetches them from the deployment CDN rather than bundling them, so
// the function payload stays under Vercel's 300 MB limit).
//
// Differences from /api/social/image:
//   - Caller-driven width via ?w= (whitelisted to 400 / 800 / 1600)
//     instead of fixed 1080/1080.
//   - Content-negotiated format: emit WebP when the request advertises
//     `Accept: image/webp` (every modern browser), JPEG otherwise.
//   - Path-based source via ?src=<filename> (no <source>__<source_id>
//     id parsing — direct filename from web/photos/* or
//     web/photos-hires/*).
//
// Why this exists (PR-perf-4): cuts ~50% off the per-image wire size
// (WebP at q=78 vs source JPEG q=85), serves the right pixel density
// per viewport (no 1600-wide image to a 320 px mobile card), and
// caches at the Vercel edge with 1-year immutability. The frontend
// Photo component (web/app/components.jsx) reads
// `image_optimization_v2` PostHog feature flag; when on, it builds
// /api/img URLs with a srcset and lets the browser pick the right
// candidate. Flag-gated so we can roll back without a deploy.
//
// Cache shape:
//   - Edge: Cache-Control: public, max-age=31536000, immutable
//   - Vary on Accept (so WebP/JPEG fork doesn't collapse into one
//     cache entry — browsers that can't read WebP must get JPEG)
//
// Safety:
//   - Path traversal guard: src must match /^[a-z0-9_.-]+$/i (no
//     slashes, no ..).
//   - Width whitelist: 400 | 800 | 1600. Any other w returns 400.
//   - Format guarded: only webp/jpeg ever emitted (no SVG / AVIF
//     downgrade path — keeps the surface small).

const sharp = require("sharp");

const ALLOWED_WIDTHS = new Set([400, 800, 1600]);
const PHOTO_ROOTS = ["photos", "photos-hires"];

function cdnBaseUrl() {
  if (process.env.PULPO_PUBLIC_BASE_URL) return process.env.PULPO_PUBLIC_BASE_URL;
  return "https://pulpo.club";
}

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

function acceptsWebp(req) {
  const accept = (req.headers && req.headers.accept) || "";
  return /image\/webp/i.test(String(accept));
}

module.exports = async (req, res) => {
  const src = (req.query.src || "").toString();
  const wRaw = (req.query.w || "").toString();
  const root = (req.query.root || "photos").toString();
  const width = Number.parseInt(wRaw, 10);

  if (!src || !/^[a-z0-9_.-]+$/i.test(src)) {
    return res.status(400).json({ error: "bad_src" });
  }
  if (!ALLOWED_WIDTHS.has(width)) {
    return res.status(400).json({
      error: "bad_width",
      detail: `w must be one of ${[...ALLOWED_WIDTHS].join(", ")}`,
    });
  }
  if (!PHOTO_ROOTS.includes(root)) {
    return res.status(400).json({ error: "bad_root" });
  }

  const base = cdnBaseUrl();
  const url = `${base}/${root}/${src}`;
  const buf = await fetchAsset(url);
  if (!buf) {
    return res.status(404).json({ error: "not_found", detail: `no asset at ${root}/${src}` });
  }

  const wantWebp = acceptsWebp(req);
  try {
    let pipe = sharp(buf).resize(width, undefined, {
      fit: "inside",
      withoutEnlargement: true,
    });
    let mime;
    if (wantWebp) {
      pipe = pipe.webp({ quality: 78, effort: 4 });
      mime = "image/webp";
    } else {
      pipe = pipe.jpeg({ quality: 82, mozjpeg: true });
      mime = "image/jpeg";
    }
    const out = await pipe.toBuffer();
    res.setHeader("Content-Type", mime);
    res.setHeader("Content-Length", out.length);
    // 1y immutable — the underlying photo file is content-keyed by
    // source_id and never rewritten in place (the pipeline produces
    // new filenames for new listings). Pair with Vary: Accept so the
    // WebP/JPEG split doesn't collapse into one cache entry on the
    // browser side.
    res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    res.setHeader("Vary", "Accept");
    res.setHeader("X-Pulpo-Image-Format", wantWebp ? "webp" : "jpeg");
    return res.status(200).send(out);
  } catch (err) {
    return res.status(500).json({ error: "resize_failed", detail: String(err && err.message) });
  }
};
