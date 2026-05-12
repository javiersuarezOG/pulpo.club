// Quick screenshot script for Phase 4C PR evidence — boots a headless
// browser, loads the dev server at three viewports, writes
// /tmp/newhp-{375,768,1280}.png. Lives inside the repo so it can
// resolve the local @playwright/test dep.
import { chromium } from "@playwright/test";

const VIEWPORTS = [
  { name: "375", width: 375,  height: 812  },
  { name: "768", width: 768,  height: 1024 },
  { name: "1280", width: 1280, height: 800 },
];

const URL = process.env.URL || "http://localhost:5173/";

const browser = await chromium.launch();
for (const vp of VIEWPORTS) {
  const ctx = await browser.newContext({
    viewport: { width: vp.width, height: vp.height },
    deviceScaleFactor: 2,
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(`console.error: ${msg.text()}`);
  });
  await page.goto(URL, { waitUntil: "networkidle", timeout: 20_000 });
  await page.waitForTimeout(500);
  const out = `/tmp/newhp-${vp.name}.png`;
  await page.screenshot({ path: out, fullPage: true });
  console.log(`[${vp.name}] saved ${out}` + (errors.length ? ` — ${errors.length} console issues` : ""));
  for (const e of errors) console.log(`  ${e}`);
  await ctx.close();
}
await browser.close();
