// Separate vitest config from vite.config.js — vite.config.js sets
// `root: web/` for the React SPA build, but vitest needs to search the
// whole repo (api/ Vercel serverless handlers + tests/ unit tests).
//
// This config is picked up automatically by `npm test` (which calls
// `vitest run --passWithNoTests`).
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Run tests from anywhere in the repo. Default vitest pattern handles
    // *.test.{js,ts,jsx,tsx} and *.spec.*.
    include: ["tests/**/*.test.{js,ts,jsx,tsx}", "web/**/*.test.{js,ts,jsx,tsx}"],
    // Playwright e2e specs live under tests/e2e and run via `npm run e2e:smoke`,
    // not vitest.
    exclude: ["tests/e2e/**", "node_modules/**", "web/dist/**"],
  },
});
