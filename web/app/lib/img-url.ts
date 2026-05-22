// Image-URL helper. Builds /api/img URLs for local photos and leaves
// broker URLs alone.
//
// Why: PR-perf-4's /api/img endpoint serves WebP at the right pixel
// density per viewport, but ONLY for assets under /photos/* or
// /photos-hires/* (we don't proxy broker URLs — that would shift the
// request fan-out from "the broker's CDN" to "our serverless function",
// blowing up our compute bill without a real win since the broker
// CDNs are already CDNs).
//
// Contract:
//   buildLocalImgUrl(src, width)
//     → "/api/img?src=<filename>&root=<photos|photos-hires>&w=<width>"
//        when src is a string that starts with "/photos/" or
//        "/photos-hires/" AND width is in the allowed set
//     → src untouched otherwise (broker URL, null, or unsupported
//        width — caller falls back to the raw src in <img>)
//
//   buildSrcSet(src, widths)
//     → " /api/img?…&w=400 400w, /api/img?…&w=800 800w, … "
//        ready to drop into <source srcSet={…}>. Returns null when
//        src is a broker URL or otherwise unoptimizable.

// Keep in lockstep with ALLOWED_WIDTHS in api/img.js.
export const ALLOWED_WIDTHS = [400, 800, 1600] as const;
export type AllowedWidth = (typeof ALLOWED_WIDTHS)[number];

const LOCAL_PHOTO_PREFIXES = [
  { prefix: "/photos/", root: "photos" as const },
  { prefix: "/photos-hires/", root: "photos-hires" as const },
];

function parseLocalSrc(src: string): { filename: string; root: "photos" | "photos-hires" } | null {
  for (const { prefix, root } of LOCAL_PHOTO_PREFIXES) {
    if (src.startsWith(prefix)) {
      const filename = src.slice(prefix.length);
      // Defensive: match api/img.js's regex so a path-traversal attempt
      // (e.g. `../etc/passwd`) is rejected client-side too. Caller falls
      // back to the raw src, which the browser then either renders or
      // 404s — but no /api/img call is made.
      if (!/^[a-z0-9_.-]+$/i.test(filename)) return null;
      return { filename, root };
    }
  }
  return null;
}

export function buildLocalImgUrl(src: string | null | undefined, width: AllowedWidth): string | null {
  if (!src) return null;
  const parsed = parseLocalSrc(src);
  if (!parsed) return null;
  return `/api/img?src=${encodeURIComponent(parsed.filename)}&root=${parsed.root}&w=${width}`;
}

export function buildSrcSet(
  src: string | null | undefined,
  widths: readonly AllowedWidth[] = ALLOWED_WIDTHS,
): string | null {
  if (!src) return null;
  const parts: string[] = [];
  for (const w of widths) {
    const url = buildLocalImgUrl(src, w);
    if (!url) return null;
    parts.push(`${url} ${w}w`);
  }
  return parts.join(", ");
}
