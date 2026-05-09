import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Vite root is `web/`. The dev server serves `web/index.html` at /, and
// resolves `/app/app.jsx` to `web/app/app.jsx`. Build output goes to
// `web/dist/`.
//
// PR section-urls (May 2026): /preview is gone. Production base is now
// "/", so built HTML references `/build/index-<hash>.js`. The
// `assetsDir: "build"` setting moves Vite's output away from `/assets/`
// (where brand assets like the favicon SVG live) — no rewrite collision,
// brand + build assets keep separate cache headers in vercel.json.
// Legacy vanilla-JS site continues to serve at `/legacy`.
//
// Dev panel DCE: VERCEL_ENV is "production" only on the prod alias. On
// preview deploys + locally it's undefined or "preview", so the dev panel
// stays in the bundle. In prod, the panel is statically replaced with
// `false && (...)` and dropped by tree-shaking. Verify with:
//   grep -c "TweakRadio\|DevPanel" web/dist/build/index-*.js   # 0 in prod
const IS_PROD_DEPLOY = process.env.VERCEL_ENV === "production";

export default defineConfig(() => ({
  plugins: [react()],
  root: path.resolve(here, "web"),
  publicDir: false,
  base: "/",
  define: {
    __PULPO_DEV_PANEL__: JSON.stringify(!IS_PROD_DEPLOY),
  },
  build: {
    outDir: path.resolve(here, "web/dist"),
    emptyOutDir: true,
    // `build/` (not `assets/`) so the rewrite for /assets/:file →
    // /web/assets/:file (brand assets) doesn't collide with Vite's
    // hashed output. /build/:file rewrites to /web/dist/build/:file in
    // vercel.json, with a 1y immutable cache header — safe because
    // every deploy emits new hashed names.
    assetsDir: "build",
    rollupOptions: {
      output: {
        // Content-hashed filenames so vercel.json's `/build/:file`
        // 1y immutable cache is safe — every deploy emits new hashed
        // names, no stale-cache risk. HTML stays max-age=0 so the
        // next nav always picks up the fresh hash. PR section-urls
        // moved this from /assets/ → /build/ so brand assets and
        // build assets don't share a cache rule.
        entryFileNames: "build/[name]-[hash].js",
        chunkFileNames: "build/[name]-[hash].js",
        assetFileNames: "build/[name]-[hash][extname]",
      },
    },
  },
  server: {
    port: 5173,
    open: false,
  },
}));
