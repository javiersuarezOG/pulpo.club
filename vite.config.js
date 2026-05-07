import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));

// Vite root is `web/`. The dev server serves `web/index.html` at /, and
// resolves `/app/app.jsx` to `web/app/app.jsx`. Build output goes to
// `web/dist/` so the legacy `/web/legacy.html` keeps working in production
// until PR-1 wires up `/preview` to the new bundle.
export default defineConfig({
  plugins: [react()],
  root: path.resolve(here, "web"),
  publicDir: false,
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
});
