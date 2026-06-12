#!/usr/bin/env node
// Card-image gate linter — a fast (<1s) static check that catches the
// regression class behind the browse_table (Jun 8) and map/map_sheet (Jun 9)
// blank-slot 404s: a card/list/map surface rendering a listing image with a
// bare <img> instead of the gated <Photo> component.
//
// Background: <Photo> (web/app/components.jsx) routes listing thumbnails
// through `isCardImageDisplayable`, which suppresses `is_local=true` URLs that
// would 404 and provides a bundled-illustration fallback. New surfaces that
// render `thumbnail_url` / `selected_photo_url` / `.photos[...]` raw in an
// <img> bypass that gate and re-introduce the blank-slot bug.
//
// What this flags: a JSX `<img ... src={ <expr> ... }>` whose `src` expression
// references `thumbnail_url`, `selected_photo_url`, or `.photos[` — i.e. a
// listing image rendered outside <Photo>. The tag may span multiple lines.
//
// EXEMPT:
//   • web/app/components.jsx — that file IS the <Photo> choke point.
//   • A flagged <img> carrying `// card-image-allow: <reason>` on the same or
//     a nearby preceding line (the gallery/lightbox/shelf-gated sites).
//
// The allow-marker is the escape hatch; each must carry a non-empty reason so
// it stays auditable. A new card surface should use <Photo>, not a marker.
//
// Usage: `node scripts/check_card_image_gate.mjs` (zero deps).

import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(process.cwd(), "web/app");
const EXTENSIONS = new Set([".jsx", ".tsx"]);

// web/app/components.jsx is the <Photo> component itself — the one place a
// listing thumbnail is *supposed* to be rendered as a raw <img>. Exempt by
// file so the choke point doesn't trip its own guard.
const SKIP_PATHS = ["web/app/components.jsx"];

// Listing-image field references that, inside an <img src={...}>, mean a
// listing thumbnail is being rendered outside <Photo>.
const LISTING_IMG_FIELD = /thumbnail_url|selected_photo_url|\.photos\[/;

const ALLOW_MARKER = "card-image-allow:";

function* walk(dir) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walk(full);
    } else if (EXTENSIONS.has(path.extname(entry.name))) {
      const rel = path.relative(process.cwd(), full);
      if (SKIP_PATHS.some((p) => rel === p || rel.startsWith(p + "/"))) continue;
      yield full;
    }
  }
}

// Match a whole <img ...> opening tag (may span multiple lines). We grab from
// `<img` up to the first `>` — JSX <img> is self-closing/void so there's no
// nested `>` to worry about inside attribute values here.
const IMG_TAG_REGEX = /<img\b[^>]*>/gs;
// Within an <img> tag, find a `src={ ... }` expression. `[^}]*` is enough
// because the src expressions in this codebase don't nest a closing brace
// before the attribute ends.
const SRC_EXPR_REGEX = /\bsrc=\{([^}]*)\}/s;

let violations = 0;
const findings = [];

for (const file of walk(ROOT)) {
  const content = fs.readFileSync(file, "utf8");
  const lines = content.split("\n");

  let m;
  IMG_TAG_REGEX.lastIndex = 0;
  while ((m = IMG_TAG_REGEX.exec(content)) !== null) {
    const tag = m[0];
    const srcMatch = SRC_EXPR_REGEX.exec(tag);
    if (!srcMatch) continue; // <img src="literal"> or no src — not our case.
    if (!LISTING_IMG_FIELD.test(srcMatch[1])) continue; // not a listing image.

    // Line number of the start of the <img> tag.
    const startLine = content.slice(0, m.index).split("\n").length; // 1-based

    // Allow-marker: same line as `<img`, or any line within the tag, or a
    // short preceding window (markers often sit on the line above the block).
    const tagLineCount = tag.split("\n").length;
    const windowStart = Math.max(0, startLine - 1 - 2); // up to 2 lines above
    const windowEnd = startLine - 1 + tagLineCount; // through end of the tag
    let exempt = false;
    for (let i = windowStart; i < windowEnd && i < lines.length; i++) {
      const idx = lines[i].indexOf(ALLOW_MARKER);
      if (idx !== -1) {
        const reason = lines[i].slice(idx + ALLOW_MARKER.length).trim();
        if (reason.length > 0) {
          exempt = true;
          break;
        }
      }
    }
    if (exempt) continue;

    findings.push({
      file: path.relative(process.cwd(), file),
      line: startLine,
      snippet: tag.split("\n")[0].trim() + (tagLineCount > 1 ? " …" : ""),
    });
    violations++;
  }
}

if (violations === 0) {
  console.log(
    "[card-image-gate] 0 raw listing-image <img> outside <Photo> under web/app/ ✓",
  );
  process.exit(0);
}

console.error(
  `[card-image-gate] ${violations} raw listing-image <img> outside <Photo> found:`,
);
for (const f of findings) {
  console.error(`  ${f.file}:${f.line}`);
  console.error(`    > ${f.snippet}`);
}
console.error("");
console.error(
  "Render listing images through <Photo> / isCardImageDisplayable (web/app/components.jsx),",
);
console.error(
  "which suppresses is_local 404s and supplies a fallback illustration. If this site is a",
);
console.error(
  "legitimately-gated raw render (detail gallery, lightbox, shelf-gated row), append",
);
console.error(
  "`// card-image-allow: <reason>` on the <img> line or just above it.",
);
console.error("");
console.error('See CLAUDE.md and plans/014-card-image-bypass-lint.md.');
process.exit(1);
