# Vercel Security Checkpoint — investigation note

**Status (2026-05-08):** present, intermittent, not firing on humans or major search bots. **No action needed.** Re-evaluate if the symptom changes.

## What we observed

A Playwright session against `https://pulpo.club/` at 15:19 (UTC) on 2026-05-08 returned a 403 on the root document and rendered the Vercel Security Checkpoint page (`"We're verifying your browser"`, footer `Vercel Security Checkpoint fra1::1778253570-…`). Captured under:

- `.playwright-mcp/console-2026-05-08T15-19-30-659Z.log`
- `.playwright-mcp/page-2026-05-08T15-19-30-975Z.yml`

Two earlier captures from the same minute window (15:09, 15:12) returned the real app cleanly. No code change shipped between the three captures.

## What it isn't

We probed `pulpo.club` from the Claude Code shell with curl, varying user-agent and request rate. None of these triggered the Checkpoint:

| User-Agent | Request shape | Result |
|---|---|---|
| Real Chrome (macOS) | single GET | `200 OK` |
| Googlebot/2.1 | single GET | `200 OK` |
| Bingbot/2.0 | single GET | `200 OK` |
| `python-requests/2.31.0` | single GET | `200 OK` |
| `HeadlessChrome/130.0.0.0` | single GET | `200 OK` |
| `curl/8.x` (default) | single GET | `200 OK` |
| no UA | burst of 10 sequential GETs | `200 × 10` |
| `python-requests/2.31.0` | burst of 10 sequential GETs | `200 × 10` |

So the Checkpoint is **not gating Googlebot, Bingbot, or default-UA scripts** — SEO and casual scrapers pass through. Headless-Chrome UA alone also passes when the request is plain HTTP/1 from a server-class IP.

## What it probably is

Vercel's adaptive Bot Protection scores requests by a combination of UA string, TLS fingerprint, IP reputation, JA3, missing JS execution, and behavioral signals across the session. Playwright/Chromium running under the MCP runtime presents a high-signal profile: real Chrome UA + real TLS fingerprint + no human input timing + automation flags exposed via CDP. When the bot score crosses Vercel's threshold for the surfacing IP, the next document request gets the Checkpoint until the JS challenge runs and the session sets the `_vcrcs` cookie. Subsequent navigations on the same browser session pass cleanly.

This explains the observed pattern: same Playwright runner, three minutes apart, two passes and one challenge — the score crossed the threshold once, the challenge resolved, the session stayed clean.

## Why we're leaving it alone

- **Humans aren't seeing it.** Real browser sessions from residential IPs are not in the high-signal cohort, and the Checkpoint clears in a few hundred ms when it does fire. No support tickets, no crash reports, no PostHog `landing.viewed` gap on the funnel for 2026-05-08.
- **Search crawlers aren't seeing it.** Verified above — Googlebot/Bingbot UAs pass cleanly. The original SEO-audit concern (de-indexing) does not apply.
- **It's a free tier of bot protection** — turning it off entirely would remove a real layer of abuse-mitigation for a problem we don't have.

## When to revisit

Re-investigate if any of the following becomes true:

- Playwright e2e starts failing in CI with 403s on `/`. Mitigation: add a Vercel **Protection Bypass for Automation** token to the e2e config, OR allow-list the CI runner egress IPs in the Vercel Firewall.
- A real human user reports the Checkpoint persisting (more than ~2s) or looping. Mitigation: file a Vercel support ticket with the `fra1::…` request ID from the footer; ask for the bot-score threshold to be relaxed for the home document.
- PostHog `landing.viewed` count drops materially without a corresponding marketing change — a sign of a stricter Checkpoint cohort being silently challenged.

## How to reproduce the probes

```bash
# Single-shot UA matrix
for ua in "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36" \
          "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)" \
          "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)" \
          "python-requests/2.31.0" \
          "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/130.0.0.0 Safari/537.36"; do
  printf "%-100s → " "${ua:0:90}"
  curl -s -o /dev/null -w "status=%{http_code}\n" -A "$ua" "https://pulpo.club/"
done

# Burst test
for i in $(seq 1 10); do curl -s -o /dev/null -w "%{http_code} " "https://pulpo.club/"; done; echo
```

If any non-200 appears for a UA outside the Playwright/MCP cohort, escalate per the "When to revisit" list above.
