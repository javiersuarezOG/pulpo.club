# Cron: nightly cadence + enable all working sources

You are updating the production weekly run to (a) fire every night
instead of just Wednesdays, and (b) include every source we've gotten
to work since the workflow was authored.

This is a small but trust-spine change — the YAML controls the only
automated job that publishes data to members. Touch only what's listed
below; no other changes.

Read `.github/workflows/pulpo-weekly.yml`, `automation/run.py`, and
`pulpo/scrapers/__init__.py` first to confirm which sources are
currently registered and which are working live.

## What to change

In `.github/workflows/pulpo-weekly.yml`:

1. **Rename the file** to `.github/workflows/pulpo-nightly.yml`. Update
   the `name:` field at the top to `pulpo nightly run`. Adjust the
   header comment from "Wednesdays at 12:00 UTC..." to describe the
   nightly cadence.
2. **Cron expression**: `"0 12 * * 3"` → `"0 12 * * *"`. Keep the time
   at 12:00 UTC (06:00 SV). Brokers update overnight, so 06:00 local
   is a polite window — early enough that members get fresh data with
   their morning coffee, late enough not to hit broker maintenance
   windows.
3. **`PULPO_SOURCES`**: change `"goodlife,oceanside"` to
   `"goodlife,oceanside,century21,bienesraices"`. Skip `kazu` (API
   denylisted) and `remax` (domain still being fixed in a separate
   PR). When those land, they get added in their own PRs.
4. **Commit-message in the "Commit refreshed data" step**: change
   `weekly run $(date -u +%Y-%m-%d)` to
   `nightly run $(date -u +%Y-%m-%d)`.
5. **Leave everything else alone** — the `permissions`, the
   `actions/checkout@v4` and `actions/setup-python@v5` versions, the
   `PULPO_LIMIT: "150"` value, the bcrypt-bot identity, the
   placeholder commented-out steps. None of those need to change.

## Other places to update for consistency

A nightly cadence breaks two pieces of in-repo branding that mention
weekly. Update both so the docs match reality:

1. **`README.md`** — search for "weekly Wednesday refresh" and "every
   Wednesday" mentions. Replace with "nightly refresh (06:00 SV)" or
   similar phrasing. There's at least one in the intro paragraph and
   probably one in the "How the pipeline works" section.
2. **`automation/cron_local.sh`** — the comment block near the top
   currently says `Wednesday 06:00 SV time`. Update to nightly. The
   crontab example needs to change from `0 6 * * 3` to `0 6 * * *`.

Do NOT update the README's phrasing in a way that promises members
something we can't deliver. "Nightly best-effort refresh" is the
accurate framing — some nights one or more brokers may be down or
rate-limiting, in which case the run silently keeps the previous
data (the existing pipeline already handles this).

## Hard constraints

- Don't change `PULPO_LIMIT`. 150 was working; increasing it costs
  cron time without obvious benefit at current supply.
- Don't enable kazu or remax until their respective issues are
  resolved. Adding them to `PULPO_SOURCES` while they error every run
  would make `last_updated.json` noisier without adding listings.
- Don't add new env vars or secrets.
- Don't modify the bot's git identity or the commit/push semantics.
- Don't deploy the dashboard from this workflow — Vercel auto-deploys
  on push, that's already wired.

## Verification

YAML lint locally:

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/pulpo-nightly.yml'))"
```

If `actionlint` is installed, also run it. Otherwise, eyeball the
diff and confirm:

- Cron expression is `"0 12 * * *"` (5 fields, asterisks where
  expected).
- `PULPO_SOURCES` is exactly `"goodlife,oceanside,century21,bienesraices"`
  with no trailing whitespace or quoting issues.
- The old `pulpo-weekly.yml` is gone (renamed, not duplicated).

Then trigger the workflow manually from the GitHub Actions UI to
confirm it runs end-to-end before the first scheduled fire. Don't
commit code changes after that test run — just confirm the data
commit lands cleanly.

## Commit

```
chore(cron): nightly cadence + enable century21,bienesraices

- Rename pulpo-weekly.yml → pulpo-nightly.yml
- Cron: "0 12 * * 3" → "0 12 * * *" (every night, 06:00 SV)
- PULPO_SOURCES: goodlife,oceanside → goodlife,oceanside,century21,bienesraices
  (kazu still denylisted; remax pending domain fix in separate PR)
- README + cron_local.sh phrasing updated
```

## Final summary in chat

≤120 words. Cover:
1. Confirmation the YAML parses and the cron expression is valid.
2. Which sources are now in the nightly run and which are deferred.
3. The expected impact: ~80 + ~40 + ~15 + ~471 = ~600 listings/night
   instead of ~120/week.
4. One sentence on whether you noticed any other place in the repo
   that still references "weekly" or Wednesdays — flag for follow-up,
   don't fix in this PR.
