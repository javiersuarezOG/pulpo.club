# Design references

Visual baseline for Pulpo's public surfaces. CLAUDE.md's "Visual fidelity" rule requires PRs touching Home/Discover/Browse/Detail to diff against these images and justify any deviation in one line. PRs that ship a visual surface attach a before/after at mobile (375×812) + desktop (1280×800).

## Active references

### Home — HeroV5 (default since [#623](https://github.com/javiersuarezOG/pulpo.club/pull/623))

- [home-hero-v5-desktop.png](home-hero-v5-desktop.png) — desktop 1280×800, cookie modal dismissed.
- [home-hero-v5-mobile.png](home-hero-v5-mobile.png) — mobile 375×812.

### Browse — mobile fallback density

- [browse-mobile-fallback-density.png](browse-mobile-fallback-density.png) — mobile 375×812 capture of `/browse`, taken from production after PR [#645](https://github.com/javiersuarezOG/pulpo.club/pull/645) (photo-path contract canary) was running, so the fallback-card density reflects the post-contract steady state. If a PR pushes fallback density visibly higher, that's a regression in the photo contract — investigate before merging.

### Pro page mockups (HTML)

- [pulpo-pro-general-en.html](pulpo-pro-general-en.html), [pulpo-pro-general-es.html](pulpo-pro-general-es.html) — Pro upsell HTML mockups (EN + ES). Open in a browser for the static-render reference.

## How to refresh

Take screenshots from **production** (`https://pulpo.club/`), not a Vercel preview — previews are SSO-gated and Pro features render differently for the SSO-authed cookie. Production gives an honest anonymous view.

Mobile capture pattern (Playwright):

```js
const { chromium } = require("playwright");
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 2 });
const page = await ctx.newPage();
await page.goto("https://pulpo.club/<route>", { waitUntil: "load" });
await page.waitForTimeout(3000);
// Dismiss cookie banner if present:
try { await page.click('button:has-text("Accept all")'); await page.waitForTimeout(500); } catch {}
await page.screenshot({ path: "<file>.png" });
```

Desktop: same pattern, `viewport: { width: 1280, height: 800 }`, `deviceScaleFactor: 1`.

## What NOT to commit here

- Vercel preview screenshots (SSO-gated; renders Pro features for the auth'd reviewer; misrepresents anonymous UX).
- Dev-server captures (data fetch fails locally without the live API; cards collapse to fallback).
- Screenshots from a stale branch (always re-capture against `main` post-merge).

## Stale archives

Three Screenshot 2026-05-06 files predate HeroV5; kept for historical comparison. New refs should follow the `<surface>-<viewport>.png` naming convention.
