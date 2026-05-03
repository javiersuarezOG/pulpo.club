# Live supply completion — bump limits, audit, lock in

You are completing the supply-completeness phase: bump pagination caps,
run the coverage audit live, iteratively raise caps for any source still
truncating, then re-run the field audit so the field-completeness
numbers in `last_updated.json` reflect REAL live data instead of fixtures.

By the end of this prompt: every reachable source pulls 100% of its
advertised supply, the cron config is updated to keep it that way, and
we have a live field-completeness snapshot that points at the actual
calibration targets to tackle next.

Read commits `ff8e766` (coverage audit) and `83e462e` (field audit) for
context. Read `automation/coverage_audit.py`, `automation/field_audit.py`,
and every `pulpo/scrapers/*.py` to know the current MAX_PAGES values.

## Hard constraints

- **Don't change scraper parsing logic.** Selectors, normalize, ranker —
  all untouched. This phase is purely about pulling more of what's
  already there.
- **One commit per logical step.** Bump-and-audit is iterative; commit
  after each meaningful bump so we can see the progression.
- **Be polite to brokers.** Respect existing `REQUEST_DELAY` (1.5s).
  Don't parallelize requests.
- **Don't paper over failures.** If a source can't be reached or rate-
  limits, stop and report — don't silently fall through to fixtures.
- **Total time budget: ~30 minutes wall-clock.** If a scraper takes
  more than 5 minutes on its own, stop and report.

## What to do

**Step 1 — Bump MAX_PAGES across the board (one commit).**

In every scraper module under `pulpo/scrapers/` that has a
`MAX_PAGES` constant, raise it from 6 to 50. This is a one-line change
per file. Don't change Century 21 (single fetch, no pagination). Don't
add per-source heuristics yet — uniform bump.

Commit message: `chore(scrapers): bump MAX_PAGES from 6 to 50 to
support full-supply audit`.

**Step 2 — Document PULPO_LIMIT in deployment.**

Add a one-line note to `DEPLOY.md` (or create it if missing) under the
cron section: `PULPO_LIMIT=1000` should be set in the production cron
environment to prevent the default `limit=30` from truncating supply
on large sources. Do NOT modify the GitHub Actions workflow — the
human will apply the env var on their side.

Commit: `docs(deploy): document PULPO_LIMIT=1000 cron env requirement`.

**Step 3 — Run the live coverage audit.**

Set `PULPO_LIMIT=1000` and `unset PULPO_OFFLINE`. Run
`python3 automation/coverage_audit.py` with full live network access.
Capture the output verbatim into a new file
`docs/coverage-audit-live-1.md` so we have a record. Include the
timestamp at the top.

If any scraper hits a network error, anti-bot 403, or times out:
- Record the failure in the report.
- Move on to the next source — don't retry indefinitely.

**Step 4 — If anything's still truncating, bump and re-audit.**

For each source where `max_pages_hit=YES` AND `pulled` is meaningfully
less than `supplier`:
- Bump that scraper's MAX_PAGES to 200 (or whatever covers the
  reported supplier total / pageSize, with 50% headroom).
- Commit: `chore(scrapers/<name>): bump MAX_PAGES to N for full
  supply coverage`.
- Re-run the audit, save as `docs/coverage-audit-live-2.md`.
- Repeat until either everything is green or you've hit a wall (a
  scraper that can't pull all its supply due to broker-side
  pagination cutoff, anti-bot, etc. — document and stop).

**Step 5 — Run the live field audit.**

Once coverage is as green as it'll get, the `web/data/ranked.json`
now reflects real live data. Run `python3 automation/run.py` to
regenerate `ranked.json` and `last_updated.json` with full supply,
then run `python3 automation/field_audit.py`. Capture the output to
`docs/field-audit-live-1.md`. This replaces the fixture-based numbers
with the real ones we'll act on.

Commit `web/data/last_updated.json` and the new audit logs.

**Step 6 — Identify the top 3 calibration targets.**

Look at the live field-audit output. For each tracked field, sort by
populated %. Identify the 3 fields that are:
- Most populated on at least ONE source (so we know the data exists
  in the wild)
- AND most under-populated on at least one OTHER source (so we know
  it's a calibration gap, not a feature gap).

Example: if `has_water` is 80% on goodlife but 5% on oceanside, that's
a calibration gap on oceanside. If `lat` is 0% across every source,
that's a feature gap (defer to a separate phase).

Write the conclusion at the bottom of `docs/field-audit-live-1.md`
under a "## Calibration targets" heading. Be specific: source name +
field name + the gap, e.g. "oceanside.has_water — 5% populated vs
80% on goodlife. Likely missing the amenities-toggle selector on
oceanside detail pages."

## Verification

```bash
PULPO_LIMIT=1000 python3 automation/coverage_audit.py    # all sources at or near 100%
python3 -m pulpo.cli --offline                            # offline still works
python3 tests/test_units.py                              # unit tests still pass
```

## Final summary in chat

≤200 words. Cover:
1. Final coverage numbers per source — what `pulled` and `coverage` are now,
   per the last live audit run.
2. Anything that didn't reach 100% and why (broker cap? anti-bot?
   site doesn't publish a total?).
3. The top 3 calibration targets identified, in priority order.
4. One concrete recommendation for the next prompt — e.g. "calibrate
   has_water and has_power on oceanside detail pages, sample HTML
   already exists at samples/calibration/oceanside/detail.html."

If the live audit reveals something I should know before continuing
(e.g. a broker is blocking us entirely, or a source has 5x the
supply we expected), flag it explicitly so I can decide before we
move on.
