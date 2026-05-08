# Pulpo · Backlog

Living list of follow-ups, untested caveats, and pre-existing tech debt. Work
items here are explicitly *not yet scheduled* — when you pick one up, move it
into the regular PR/issue flow. Sebastian is the owner unless noted otherwise.

Last updated: 2026-05-08.

---

## Calibration after the next nightly

- [ ] **Tune `detect_text_overlay` thresholds against real Pulpo photos.** PR-151 shipped with `min_word_count=8` and `min_area_pct=5.0`. Once the next nightly populates `has_text_overlay` across the full catalog (`web/data/ranked.json`), look at:
  - How many listings get flagged true / false / null
  - Sample 20 flagged + 20 unflagged manually — what's the precision?
  - If precision < ~80%, raise `min_word_count` to 10–12 or `min_area_pct` to 7–8. Code lives in [automation/photo_quality.py](automation/photo_quality.py).
  - If recall is poor (real brochures missed), drop the area threshold or lower confidence.
  - Long-term: add a Phase-2 vision LLM pass for borderline cases (Tesseract ≥ 60% conf but flagged false).

---

## UX / FE polish

- [ ] **PlansPage hard-coded English.** Only the new `plans.upgrade_pro_cta` and `plans.checkout_error_toast` keys go through `t()`. "Free", "Pulpo Pro", "Most popular", every feature line — all literal English in [pages.jsx:2110-2179](web/app/pages.jsx). ES users see English here. Wrap each string in `t()` and add EN/ES pairs in [i18n.jsx](web/app/i18n.jsx).
- [ ] **Account.jsx mock orders are hardcoded dates** ("5 May 2026" through "5 Jan 2026" in [account.jsx:301-305](web/app/account.jsx)). Will read as stale once today moves past them. Replace with a `n_months_ago(today, n)` helper or pull live data from Stripe.
- [ ] **Stripe checkout friction for anonymous users.** Anonymous → "Upgrade $10/month" → `sign_in_required` → SignupModal opens → user signs up → modal closes → user has to click "Upgrade" *again*. Same pattern on Account page. Fix: add a `pendingAction: "checkout"` field to `SignupModal` so the flow chains automatically after auth completes. See [account.jsx:336-355](web/app/account.jsx) and [pages.jsx:2125-2175](web/app/pages.jsx).
- [ ] **`ranked.json` is ~4 MB on every cold load.** Even with the 60-card pagination from PR-150 the JSON is fully parsed in memory. Worth splitting into pages server-side once the catalog grows past ~1500 listings.

## Telemetry

- [ ] **Wire client-side `web-vitals` to PostHog.** The `web-vitals` package is in `package.json` but isn't actually emitting events. There's no `web_vitals.cls` insight today, so flicker / layout-shift bugs have to be triaged by eyeball. Hook `onCLS` / `onLCP` / `onFID` to `track("web_vitals.<metric>", { value, rating })` from `web/app/app.jsx`. Then build the corresponding insights in PostHog.

## Pre-existing tech debt

- [ ] **Local pytest mismatch:** `tests/test_photos.py::test_hero_download_creates_jpeg` fails locally with `Wrong JPEG library version: library is 90, caller expects 80`. Pillow vs `libjpeg` mismatch in Sebastian's env. CI passes. `pip install --force-reinstall Pillow` should fix it.

## Untested caveats from PR-150 (Discover/Detail UX punch-list)

These shipped in [PR-150](https://github.com/javiersuarezOG/pulpo.club/pull/150) but were verified only in Chromium / dev. Worth a real-device spot check before relying on them:

- [ ] Real Stripe checkout end-to-end (need a real signed-in user + Stripe test card).
- [ ] Real iPhone Safari + Android Chrome — only Chromium emulated viewports were tested.
- [ ] ES locale — added translations exist, never visually inspected in-app.
- [ ] Tablet (768–1023px) — only mobile and desktop endpoints tested.

## Map (deferred from PR-150)

- [ ] **Real interactive map for listing detail.** PR-150 hid the fake `.static-map` illustration. To bring back a real map: expose `lat` + `lng` on the FE `Listing` type ([web/app/data/types.ts](web/app/data/types.ts)) and adapter ([web/app/data/listings.ts](web/app/data/listings.ts)), the data is already in [pulpo/normalize.py:618](pulpo/normalize.py). Ship Leaflet + OSM tiles (free, no API key). Lazy-load to keep the bundle lean on first paint.
