# Observability — Pulpo

## Stack

| Surface | Tool | Why |
|---|---|---|
| Product analytics + funnels | **PostHog** (EU host, cloud) | Auto-segments by country/device/browser; built-in funnels, retention, feature flags, session replay. Free up to 1M events/mo. |
| Web Vitals (LCP/INP/CLS/TTFB) | `web-vitals` → PostHog events | Real-user perf, segmentable by device/route. |
| Server runtime | Vercel runtime logs | Single-line `[api] <name> status=… ms=…` per request, grep-able. |
| Pipeline health | `web/data/last_updated.json` | Per-source green/yellow/red; field-population rates per release. |

## Setup

PostHog requires two Vercel env vars:

```
VITE_POSTHOG_KEY    = <project API key from PostHog dashboard>
VITE_POSTHOG_HOST   = https://eu.i.posthog.com   # default
```

Without them, `track()` silently no-ops — production safe (the FE just doesn't telemeter), but no funnels appear in PostHog. Set both before PR-10 cutover.

## Where the gates fire

- **Local `vite dev`:** silent unless `?ph=1` URL flag.
- **Vercel preview deploys:** active (so we can verify events on PR review).
- **Production:** active.

PostHog JS is lazy-loaded inside `requestIdleCallback` (~50KB gzipped, not first-paint-critical). Autocapture is **off** — we use the explicit typed catalog at `web/app/telemetry/events.ts`.

## Privacy

- No PII in event payloads. `listing_id`, `auth_state`, etc. — no broker emails, no listing addresses.
- Session replay sample rate: 10%, all input fields masked.
- `consent.declined` blocks all subsequent events client-side.
- Server-side logs hash any email-like field with a server-only salt before logging (post-PR-9).

## Funnels (built in PR-10)

1. **Click-through (primary success metric):** `landing.viewed → card.clicked → detail.opened → view_original.clicked`.
2. **Acquisition:** `landing.viewed → hero.cta_clicked → card.clicked → detail.opened → signup_modal.shown → signup.completed`.
3. **Save:** `card.clicked → save.toggled → signup_modal.shown → signup.completed`.
4. **Paywall:** `detail.opened (auth=free) → paywall.shown → paywall.bypassed.action=upgrade → plans.viewed → /api/checkout`.

PostHog auto-segments each of the above by country, device_type, browser, referrer — no extra instrumentation.

## Adding an event

1. Add the entry in `web/app/telemetry/events.ts` (key + payload type).
2. Import `useTelemetry` (or `track` directly) in the component, call `track('your.event', { ... })`.
3. PostHog's typed contract rejects unknown events at build time.
4. PR description should list any new events introduced.
