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

const fs = require("fs");
const path = require("path");
const sharp = require("sharp");

const SIZES = {
  "1:1": { width: 1080, height: 1080 },
  "4:5": { width: 1080, height: 1350 },
};

function resolveHeroPath(id) {
  const idx = id.indexOf("__");
  if (idx < 1) return null;
  const source = id.slice(0, idx);
  const sourceId = id.slice(idx + 2);
  // Allow only safe slug chars to prevent path traversal.
  if (!/^[a-z0-9_-]+$/i.test(source) || !/^[a-z0-9_.-]+$/i.test(sourceId)) return null;
  const filename = `${source}_${sourceId}.hero.jpg`;
  const candidates = [
    path.join(__dirname, "..", "..", "web", "photos", filename),
    path.join(process.cwd(), "web", "photos", filename),
    // Pipeline also writes a plain .jpg (card derivative) as fallback.
    path.join(__dirname, "..", "..", "web", "photos", `${source}_${sourceId}.jpg`),
    path.join(process.cwd(), "web", "photos", `${source}_${sourceId}.jpg`),
  ];
  for (const p of candidates) {
    try {
      const stat = fs.statSync(p);
      if (stat.isFile()) return p;
    } catch (_) {
      // try next
    }
  }
  return null;
}

module.exports = async (req, res) => {
  const id = (req.query.id || "").toString();
  const ratio = (req.query.ratio || "1:1").toString();
  const size = SIZES[ratio];
  if (!id || !size) {
    return res.status(400).json({ error: "bad_request", detail: "id and ratio=1:1|4:5 required" });
  }
  const heroPath = resolveHeroPath(id);
  if (!heroPath) {
    return res.status(404).json({ error: "not_found" });
  }
  try {
    // Refuse to upscale: sources below the requested canonical dimensions
    // produce visibly pixelated 1080-wide outputs (see pulpo-social photo-gate
    // Round 1 diagnostic — every passer in the 50-listing cohort was a 3x
    // upscale of a 600x400 thumbnail). The contract requires Meta-sized
    // images, so we 404 here and let pre-filters (e.g. pulpo-social's
    // source_width/source_height check) skip these listings before request.
    const meta = await sharp(heroPath).metadata();
    if ((meta.width ?? 0) < size.width || (meta.height ?? 0) < size.height) {
      return res.status(404).json({
        error: "source_too_small",
        detail: `source ${meta.width}x${meta.height} is below target ${size.width}x${size.height}; refuse to upscale`,
      });
    }
    const buf = await sharp(heroPath)
      .resize(size.width, size.height, { fit: "cover", position: "attention", withoutEnlargement: true })
      .jpeg({ quality: 85, mozjpeg: true })
      .toBuffer();
    res.setHeader("Content-Type", "image/jpeg");
    res.setHeader("Cache-Control", "public, max-age=31536000, immutable");
    res.setHeader("Content-Length", buf.length);
    return res.status(200).send(buf);
  } catch (err) {
    return res.status(500).json({ error: "resize_failed", detail: String(err && err.message) });
  }
};
