import { mkdirSync, writeFileSync } from "node:fs";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "vitest";

import {
  buildSummary,
  classifyAsset,
  collectBundleFiles,
  summarizeBundle,
} from "../../web/app/styles/check-bundle-size.mjs";

describe("check-bundle-size manifest parser", () => {
  test("classifies tracked hashed chunks", () => {
    expect(classifyAsset("build/index-abc123.js").kind).toBe("main_js");
    expect(classifyAsset("build/index-abc123.css").kind).toBe("main_css");
    expect(classifyAsset("build/clerk-bundle-abc123.js").kind).toBe("clerk_bundle");
    expect(classifyAsset("build/vendor-react-abc123.js").kind).toBe("vendor_react");
    expect(classifyAsset("build/module-abc123.js").kind).toBe("unbudgeted_js");
  });

  test("collects unique JS and CSS assets from a Vite manifest", () => {
    const manifest = {
      "index.html": {
        file: "build/index-abc123.js",
        css: ["build/index-abc123.css"],
        isEntry: true,
      },
      "app/account.jsx": { file: "build/account-def456.js" },
      "app/start.jsx": { file: "build/start-ghi789.js", css: ["build/index-abc123.css"] },
      "asset.webp": { file: "build/photo-xyz.webp" },
    };
    expect(collectBundleFiles(manifest)).toEqual([
      "build/index-abc123.js",
      "build/index-abc123.css",
      "build/account-def456.js",
      "build/start-ghi789.js",
    ]);
  });

  test("summarizes raw and gzip sizes with budget status", () => {
    const root = mkdtempSync(join(tmpdir(), "pulpo-bundle-size-"));
    mkdirSync(join(root, "build"), { recursive: true });
    writeFileSync(join(root, "build/index-abc123.js"), "x".repeat(490 * 1024));
    writeFileSync(join(root, "build/index-abc123.css"), ".a{color:red}");
    const rows = summarizeBundle({
      distDir: root,
      manifest: {
        "index.html": {
          file: "build/index-abc123.js",
          css: ["build/index-abc123.css"],
          isEntry: true,
        },
      },
    });
    const summary = buildSummary(rows);
    expect(rows).toHaveLength(2);
    expect(summary.files[0]).toHaveProperty("file");
    expect(summary.warnings).toBe(1);
    expect(rows.find((row) => row.kind === "main_js").over_raw).toBe(true);
  });
});
