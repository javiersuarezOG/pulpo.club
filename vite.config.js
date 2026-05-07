import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Vite root is `web/`. The dev server serves `web/index.html` at /, and
// resolves `/app/app.jsx` to `web/app/app.jsx`. Build output goes to
// `web/dist/`. The legacy vanilla-JS site keeps serving at /legacy.html
// until the PR-10 cutover.
//
// Dev panel DCE: VERCEL_ENV is "production" only on the prod alias. On
// preview deploys + locally it's undefined or "preview", so the dev panel
// stays in the bundle. In prod, the panel is statically replaced with
// `false && (...)` and dropped by tree-shaking. Verify with:
//   grep -c "TweakRadio\|DevPanel" web/dist/assets/index.js   # 0 in prod
const IS_PROD_DEPLOY = process.env.VERCEL_ENV === "production";

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  root: path.resolve(here, "web"),
  publicDir: false,
  // Mounted under /preview/ until PR-10 cutover; the rewrite in vercel.json
  // sends /preview → /web/dist/index.html and /preview/assets/* → /web/dist/assets/*.
  // Dev mode (`vite dev`) ignores this and serves at the Vite root.
  base: mode === "production" ? "/preview/" : "/",
  define: {
    __PULPO_DEV_PANEL__: JSON.stringify(!IS_PROD_DEPLOY),
  },
  build: {
    outDir: path.resolve(here, "web/dist"),
    emptyOutDir: true,
    assetsDir: "assets",
    rollupOptions: {
      output: {
        // Pinned filenames: vercel.json rewrites are exact-path. Cache
        // invalidation comes from Vercel's Cache-Control headers, not URL
        // hashing.
        entryFileNames: "assets/index.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: (info) => {
          if (info.name && info.name.endsWith(".css")) return "assets/index.css";
          return "assets/[name][extname]";
        },
      },
    },
  },
  server: {
    port: 5173,
    open: false,
  },
}));
