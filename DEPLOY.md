# Deploy `pulpo.club` — step-by-step runbook

Three phases, each independent. **Stop after Phase 1 and tell me what you see before going to Phase 2.**

```
Phase 1: Local end-to-end test       ~5 min
Phase 2: Vercel production deploy    ~3 min
Phase 3: Connect pulpo.club domain   ~5 min + DNS wait
```

---

## Phase 1 — Local end-to-end test

### Step 1.1 Open Terminal
Press `⌘ + Space`, type `Terminal`, hit Enter.

### Step 1.2 Go to the project folder
Paste this whole line (the quotes matter — the path has spaces):

```bash
cd "/Users/javiersuarez/Library/Application Support/Claude/local-agent-mode-sessions/ab935163-cdd2-4e57-a689-e2fa8d3f4b24/317a7556-3391-43e4-bb85-feb2dae01d51/local_6e27805f-b592-47fb-9154-5046ff1e1e56/outputs/pulpo-sv"
```

Verify with `pwd`. Should print the same path back. If it doesn't, the folder moved — tell me.

### Step 1.3 Install Node dependencies
```bash
npm install
```
**Expected:** `added 1 package, audited 2 packages in Xs`. Some warnings about deprecation are fine.
**If it fails with "command not found":** install Node.js from <https://nodejs.org/> (LTS), close and reopen Terminal, retry.

### Step 1.4 Generate a session secret
```bash
node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))"
```
Copy the output (long random string). **Save it somewhere — you need it twice.**

### Step 1.5 Create a test user
```bash
node automation/add_user.js javier
```
- Type a password (≥8 chars). Nothing shows on screen — that's intentional.
- Confirm the password.
- Output looks like: `javier:$2a$10$abcXYZ.....`

**Copy the entire `javier:$2a$10$....` line.** Don't lose the password — it's what you'll type to log in.

### Step 1.6 Install Vercel CLI (one time only)
```bash
npm install -g vercel
```
If you get a permission error: `sudo npm install -g vercel` (will ask for your Mac password).

### Step 1.7 Run the dev server
Replace `<SECRET>` with the string from Step 1.4 and `<USER_LINE>` with the line from Step 1.5:

```bash
SESSION_SECRET="<SECRET>" USERS="<USER_LINE>" vercel dev
```

The first time, Vercel will ask:
- `Set up and develop "~/.../pulpo-sv"?` → `Y`
- `Which scope?` → your account
- `Link to existing project?` → `N`
- `What's your project's name?` → `pulpo-club`
- `In which directory is your code located?` → `./`
- It may ask about framework — choose **Other**.

**Expected:** `> Ready! Available at http://localhost:3000`. Leave this terminal open.

### Step 1.8 Open the dashboard
Open <http://localhost:3000> in your browser.

**You should see:**
- Header with "Listings ranked this week"
- 15 listing cards, each with title, price band, $/m², zone, rank reasons
- A login button somewhere visible

**Test login:**
- Click login
- Username: `javier`
- Password: whatever you typed in Step 1.5
- The page reloads. Now cards should show **broker contact info, exact price, source URL** that weren't visible before.

**Test logout:**
- Click logout. Page reloads. Broker info hidden again.

✅ **If everything above worked, stop here and tell me. We'll go to Phase 2.**

❌ If anything breaks, screenshot it and tell me:
- What page were you on?
- What did you click?
- What did the screen do? (error message, blank, frozen, etc.)
- Any output in the terminal where `vercel dev` is running?

To stop the dev server: press `Ctrl + C` in its terminal.

---

## Phase 2 — Vercel production deploy

Don't start this until Phase 1 worked.

### Step 2.1 Link the local folder to a Vercel project
In the same terminal (still in `pulpo-sv` folder):

```bash
vercel link
```
- `Link to existing project?` → `N`
- `What's your project's name?` → `pulpo-club`
- `Which directory?` → `./`

This creates a hidden `.vercel/` folder remembering the link.

### Step 2.2 Set production environment variables
**Generate a NEW session secret** (don't reuse the dev one):
```bash
node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))"
```

Then add it:
```bash
vercel env add SESSION_SECRET production
```
Paste the new secret. Press Enter.

```bash
vercel env add USERS production
```
Paste the `javier:$2a$10$...` line from Step 1.5. Press Enter.

(You can confirm both via Vercel Dashboard → your project → Settings → Environment Variables.)

### Step 2.3 Deploy
```bash
vercel --prod
```

**Expected:** A URL like `https://pulpo-club-xxxxx.vercel.app`. Click it.

**Test on the production URL:**
- Public dashboard loads (15 listings)
- Login as `javier` works
- Full data shows after login

If everything works, you're ready for the custom domain.

---

## Phase 3 — Connect pulpo.club

### Step 3.1 Add the domain in Vercel
1. Go to <https://vercel.com/dashboard>.
2. Click your **pulpo-club** project.
3. **Settings → Domains** in the left sidebar.
4. Type `pulpo.club`, click **Add**.
5. (Optional but recommended: also add `www.pulpo.club`.)

Vercel will show one of these screens:
- "Configure your DNS" with A and/or CNAME records to add at your registrar.
- A "Buy this domain" option (skip — you already own it).

**Leave that page open.** You'll need the values it shows.

### Step 3.2 Add DNS records at your registrar
Open a new browser tab and log in to wherever you bought `pulpo.club` (GoDaddy, Namecheap, Google Domains, Cloudflare, etc.). Find the DNS settings page for `pulpo.club`.

Add the records Vercel showed you. Most commonly:

| Type  | Name | Value                  |
|-------|------|------------------------|
| A     | `@`  | `76.76.21.21`          |
| CNAME | `www`| `cname.vercel-dns.com` |

If Vercel showed different values, use those instead.

Save. (Some registrars take a minute to apply.)

### Step 3.3 Wait for DNS + TLS
Back on the Vercel Domains page, the status should change from "Invalid Configuration" → "Pending" → "Configured" (green check). Usually 5–30 minutes. TLS certificate provisions automatically after that.

### Step 3.4 Verify
Open <https://pulpo.club> in a fresh browser tab. Padlock icon, dashboard loads, login works.

Done. 🎉

---

## Common snags

| Symptom | Likely cause | Fix |
|---|---|---|
| `npm install` says command not found | Node.js not installed | Install from nodejs.org, restart Terminal |
| `vercel dev` says "EADDRINUSE :3000" | Another app on port 3000 | `vercel dev --listen 3001` and use `:3001` in browser |
| Login returns 401 | Wrong password, or USERS env var doesn't have your line | Double-check the user line was pasted whole, including the `:` and `$2a$` part |
| Dashboard shows "Loading…" forever | Auth API returned 500 — check the `vercel dev` terminal for the stack trace | Send me the trace |
| Custom domain shows "Invalid Configuration" after 1 hour | DNS records didn't save, or wrong values | Re-check at the registrar; some registrars require `@` to be left blank instead of typed |
| `vercel --prod` fails with "no project" | Forgot Step 2.1 | Run `vercel link` then retry |

---

## Quick reference (the whole thing in one block, if you want to do it fast)

```bash
# Phase 1 — local
cd "/Users/javiersuarez/Library/Application Support/Claude/local-agent-mode-sessions/ab935163-cdd2-4e57-a689-e2fa8d3f4b24/317a7556-3391-43e4-bb85-feb2dae01d51/local_6e27805f-b592-47fb-9154-5046ff1e1e56/outputs/pulpo-sv"
npm install
node automation/add_user.js javier         # save the printed line
SECRET=$(node -e "console.log(require('crypto').randomBytes(48).toString('base64url'))")
SESSION_SECRET="$SECRET" USERS="<paste-user-line>" vercel dev
# → open http://localhost:3000, test login, then Ctrl+C

# Phase 2 — production
vercel link
vercel env add SESSION_SECRET production   # paste a NEW secret
vercel env add USERS production            # paste the user line
vercel --prod
# → open the *.vercel.app URL, test login

# Phase 3 — domain (browser only)
# Vercel dashboard → pulpo-club → Settings → Domains → add pulpo.club
# Registrar → DNS → add the A/CNAME records Vercel showed
# Wait ~15 min, open https://pulpo.club
```

## Cron environment variables

When running `automation/run.py` as a weekly cron job (GitHub Actions or
self-hosted), set the following environment variable so the default `limit=30`
does not truncate supply on large sources:

```bash
PULPO_LIMIT=1000
```

Without this, each source is capped at 30 raw listings per run regardless
of how many the broker publishes. The coverage audit will report
`limit_hit=yes` for any source that publishes more than 30 land listings.

## Newsletter signup — Resend env vars

The rewritten homepage's hero form (POST `/api/newsletter`) subscribes
emails to a Resend Audience. Two env vars must be set in Vercel for
the endpoint to work; until they're set the endpoint returns 503 and
the FE shows the generic error toast (graceful degrade, no crash).

```bash
RESEND_API_KEY      # re_… from https://resend.com/api-keys
RESEND_AUDIENCE_ID  # UUID of the audience the homepage feeds into
```

Set both via the Vercel dashboard (Settings → Environment Variables →
Production + Preview + Development). The endpoint reads them at
request time, so flipping the env vars on does not require a redeploy.

To verify after setup:

```bash
curl -X POST https://pulpo.club/api/newsletter \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","source":"homepage_hero"}'
```

Expected responses:

| Code | Body | Meaning |
|---|---|---|
| 200 | `{ok: true}` | Subscribed |
| 400 | `{error: "invalid_email"}` | Email shape rejected client-side regex |
| 409 | `{error: "already_subscribed"}` | Already in audience |
| 429 | `{error: "rate_limited", retry_after_s: N}` | 5 attempts per IP / 5 min |
| 502 | `{error: "upstream_error"}` | Resend returned a non-dedup error |
| 503 | `{error: "service_unavailable"}` | One or both env vars missing |
| 500 | `{error: "internal_error"}` | Network / SDK throw |

PII: the endpoint NEVER logs the raw email — only `email_domain_only`
(after the @). Vercel runtime logs are safe to share.

## ranked.json recovery — Vercel Blob snapshots

Every successful nightly snapshots the canary-validated `ranked.json`
to a Vercel Blob store keyed by UTC date:

```
snapshots/ranked-2026-05-19.json
snapshots/ranked-2026-05-20.json
…
```

Retention is 90 days (set in `pulpo-nightly.yml`'s snapshot step).
Storage envelope: ~2 MB × 90 ≈ 180 MB, well inside the 1 GB free tier.
Snapshots are **public-read** so a restore doesn't need the write
token — just the URL or the date.

### When to use this

- A nightly produced a corrupt `ranked.json` and it landed on `main`
  before anyone noticed.
- The pipeline failed mid-write (PR-1's atomic-write helper makes this
  very unlikely, but Murphy's law).
- Forensic investigation: "what did ranked.json look like on 2026-05-12?"

### Required env var

```bash
BLOB_READ_WRITE_TOKEN   # vercel_blob_rw_…  (write & list; reads are public)
```

For nightly runs this is wired via GitHub Actions secrets. For local
ops use, get the token from Vercel dashboard → Storage →
`pulpo-data-snapshots` → Tokens.

### List what's available

```bash
BLOB_READ_WRITE_TOKEN=vercel_blob_rw_... node scripts/restore_ranked_json.mjs --list
```

Output is newest-first:

```
2026-05-19  1923456B  https://…vercel-storage.com/snapshots/ranked-2026-05-19.json
2026-05-18  1918002B  https://…vercel-storage.com/snapshots/ranked-2026-05-18.json
…
```

### Restore — emergency recovery

```bash
# Latest known-good snapshot:
BLOB_READ_WRITE_TOKEN=vercel_blob_rw_... node scripts/restore_ranked_json.mjs

# Specific date (UTC):
BLOB_READ_WRITE_TOKEN=vercel_blob_rw_... node scripts/restore_ranked_json.mjs --date 2026-05-12

# Validate without writing (lets you confirm the snapshot is good before clobbering local):
BLOB_READ_WRITE_TOKEN=vercel_blob_rw_... node scripts/restore_ranked_json.mjs --dry-run
```

The script validates the snapshot parses as JSON + has an array root
BEFORE overwriting `web/data/ranked.json`, and writes via tmpfile +
rename (atomic, matches PR-1's pattern). A garbage snapshot can't
corrupt your working copy.

After a successful restore: commit `web/data/ranked.json` and push
directly to `main` (the data-PR auto-flow is for nightly bot pushes;
an ops recovery is a deliberate manual commit).

### Manual snapshot (off-schedule)

```bash
BLOB_READ_WRITE_TOKEN=vercel_blob_rw_... node scripts/snapshot_ranked_json.mjs
```

Useful for capturing a known-good state immediately before a risky
pipeline change. Last-write-wins per UTC day, so a manual snapshot
followed by the nightly run will overwrite — date-named, not append.
If you need to keep an off-schedule snapshot distinct, just rename
the resulting blob via the Vercel dashboard afterwards.

## Vercel Pro upgrade — region pin

The day we move from Hobby to Pro, add multi-region functions so users
in LATAM and Europe stop paying the full RTT to `iad1`. Hobby plan
ignores multi-region (functions always run in the project's primary
region); Pro routes each request to the closest healthy region. The
static CDN is already global on both plans, so this change only
affects `/api/**` latency.

Edit `vercel.json`: add `"regions"` at the top level, alongside
`"version"` and `"functions"`:

```json
"regions": ["iad1", "gru1", "lhr1"],
```

Region codes: `iad1` = US East (Virginia), `gru1` = São Paulo
(covers Central America + LATAM from the closest peering point),
`lhr1` = London (covers Europe). Vercel routes each request to the
nearest healthy region automatically.

Verify after deploy: `curl -I https://pulpo.club/api/clerk/invitation-status`
from a São Paulo / London egress IP — the response should carry
`x-vercel-id: gru1::…` or `lhr1::…` instead of `iad1::…`.

Once regions are pinned, also enable the synthetic perf probe (cron
job that hits the prod URL every 15 minutes from each region) — see
PR-perf-1 in `~/.claude/plans/make-a-full-audit-cheerful-sketch.md`
for the design. The probe was deliberately deferred until Pro
because per-region cron requires Pro.
