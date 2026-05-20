import { defineConfig, devices } from "@playwright/test";

// E2E smoke tests for the new app. Boots Vite dev server, opens key
// routes, asserts no console errors. Catches the kind of bug we hit on
// /preview twice (price_per_m2 null crash, hook-order #310). Runs in
// CI on every PR via the frontend job.
//
// Tests live at tests/e2e/. Locally: `npm run e2e:smoke`.
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 5_000 },
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? "github" : "list",

  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  webServer: {
    command: "npm run dev",
    url: "http://localhost:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "pipe",
    env: {
      // Seed the founder-email override list so the founder-override
      // e2e can assert that a free user with this email is promoted to
      // Pro across all surfaces. CI always spins a fresh dev server;
      // a stale local dev server (reuseExistingServer=true) without
      // this env will fail the founder-override test only — the other
      // specs are unaffected.
      VITE_FOUNDER_EMAILS: "founder-tester@pulpo.club",
    },
  },
});
