# Phase 7 — governance, auto-merge, and the guards that catch what unit tests miss

Run this **after** the agentic-refactor prompt has been applied and merged.
At this point the repo should already have: pytest scaffolding,
GitHub Actions CI running on every PR, a tests-required check, the
`Source` / `RankerLeg` plug-in registries under `pulpo/agents/`, and the
`CONTRIBUTING.md` file.

Read `prompts/agentic-refactor.md` for context, plus the current state of
`.github/workflows/`, `pulpo/`, and `CONTRIBUTING.md`. Then implement the
following, in order, one commit per phase.

## Goal

Reduce human-review load to near-zero on safe changes while keeping a
firm gate on changes that can silently corrupt member-facing data. We
explicitly do NOT want "tests green = auto-merge everywhere" — tests
catch what tests cover, and the failure modes that matter most for this
product (selectors that parse the wrong field, normalize bugs that
silently invert ranking, auth/cookie regressions that leak private
fields) are precisely the ones a passing test suite can miss.

**Concurrency-safe by construction.** Two engineers will ship to this
repo in parallel. The setup must make it impossible for two
independently-green PRs to land in an order that breaks `main`, and
must make it cheap to know who is working on what and what depends on
what. The mechanisms below — GitHub merge queue, area labels, PR
template with explicit `Touches`/`Stacked on` fields, auto-applied
`safe-to-automerge` for trivially-safe diffs — are the load-bearing
parts of that promise; treat them as required, not optional.

## Hard constraints

- The full offline pipeline (`python3 -m pulpo.cli --offline` and
  `python3 automation/run.py` with `PULPO_OFFLINE=1`) must keep working
  through every phase.
- Existing tests must keep passing.
- Don't introduce dependencies that aren't justified in the final summary.
- Anything that requires a click in the GitHub UI (branch protection
  rules) goes into `docs/repo-setup.md` as a checklist for the human to
  apply, not into a workflow file. Be explicit about what the human has
  to do and what you've automated.

## Phase 7a — CODEOWNERS + protected paths

1. Create `.github/CODEOWNERS` listing the repo owner (`@suarez-javier`
   or whatever the GitHub handle is — leave a `# TODO replace with your
   handle` comment) as the required reviewer for the trust spine:

   ```
   /pulpo/normalize.py        @owner
   /pulpo/ranker.py           @owner
   /pulpo/units.py            @owner
   /pulpo/models.py           @owner
   /pulpo/ranker_legs/        @owner
   /api/                      @owner
   /automation/run.py         @owner
   /vercel.json               @owner
   /.github/workflows/        @owner
   ```

2. Add a section to `CONTRIBUTING.md` titled **"What needs review vs.
   what can auto-merge"** that lists the protected paths and the
   auto-mergeable paths. Auto-mergeable: `samples/`, `fixtures/`,
   `prompts/`, `docs/`, `*.md` at the repo root, `web/data/*`,
   `requirements.txt` patch-version bumps only, additive-only `tests/**`
   files, and any new file under `pulpo/scrapers/` or `pulpo/agents/`
   *that ships with a matching test* (the existing tests-required check
   already enforces the test-shipping part).

## Phase 7b — `safe-to-automerge` label workflow

1. Create `.github/workflows/automerge.yml` triggered on `pull_request`
   events (`labeled`, `unlabeled`, `synchronize`, `opened`,
   `reopened`) and on `check_suite` `completed`. Logic:
   - If PR has the `safe-to-automerge` label AND the PR author is a
     repo collaborator AND CI is green AND the tests-required check is
     green AND there are no unresolved review comments → enable
     GitHub's auto-merge with squash strategy.
   - If the label is removed or CI fails, the auto-merge is
     automatically disabled by GitHub.
   - Use the `peter-evans/enable-pull-request-automerge` action (pin to
     a specific commit SHA, not a tag).
2. Create a separate `.github/workflows/dependabot-automerge.yml` that
   auto-applies the `safe-to-automerge` label to Dependabot PRs that
   bump only patch versions. Use `dependabot/fetch-metadata@v2` to
   inspect the bump type.
3. Document the human workflow in `CONTRIBUTING.md`:
   "Author a PR → CI runs → if you've already eyeballed the diff and
   it's safe, apply the `safe-to-automerge` label → it merges
   automatically when CI is green. Otherwise leave it for a real review
   pass." Make clear the label is a 2-second human checkpoint, not a
   bypass of the protected-paths review requirement.

## Phase 7c — additional CI guards

Add these as separate jobs in `.github/workflows/ci.yml` (parallel where
possible to keep wall-clock low):

1. **`ruff check`** — lint the whole repo. Add `ruff` to a new
   `requirements-dev.txt` (don't pollute `requirements.txt` — the
   production cron and Vercel functions don't need lint deps). Configure
   `ruff` in `pyproject.toml` with a sensible ruleset (E, F, I, B, UP,
   PL with a few select disables for our style).
2. **`mypy --strict pulpo/`** — type-check the `pulpo/` package only
   (skip `automation/` and `tests/` for now to keep adoption lightweight;
   note this scope decision in `pyproject.toml`).
3. **`gitleaks`** — scan for accidentally committed secrets. Use the
   official `gitleaks/gitleaks-action`. Pin to a SHA. Configure to ignore
   `fixtures/sample_listings.json` (broker phone numbers in fixtures are
   intentional and synthetic).
4. **Add `requirements-dev.txt`** with `ruff`, `mypy`, `pytest`,
   `pytest-cov`. Update `CONTRIBUTING.md` with a one-line `pip install -r
   requirements-dev.txt` step for local dev.

## Phase 7d — the ranking-diff guard (highest-leverage check)

This is the single most important addition. It catches the silent
ranking regressions that no unit test will catch.

1. Create `.github/workflows/ranking-diff.yml` triggered on
   `pull_request` for any PR that touches `pulpo/**` or `fixtures/**`.
2. The workflow checks out `main`, runs the offline pipeline, saves
   `samples/ranked.csv` as `ranked-base.csv`. Then checks out the PR
   head, runs the pipeline again, saves as `ranked-head.csv`.
3. Run a new script `automation/diff_ranking.py` that compares the two
   CSVs and reports:
   - Number of records added / removed (by `source` + `source_id`).
   - For records present in both: the largest absolute rank delta and
     the count of records whose rank moved by ≥ 3 positions.
   - The 5 records with the largest rank deltas, side by side.
4. The script exits 1 (failing the build) if any of:
   - More than 20% of records changed rank by ≥ 3 positions.
   - More than 30% of records were added or removed.
   - Any record's `value_score`, `quality_score`, `liquidity_score`, or
     `upside_score` changed by more than 25 points.
5. Failure message includes the side-by-side diff and the line: "Large
   ranking shift detected. Either this is intentional (intended
   re-tuning of the ranker) and you should add the
   `ranking-shift-acknowledged` label to bypass this check, or it's an
   accidental regression in normalize/ranker/units/scrapers and you
   should investigate before merging."
6. Honor the `ranking-shift-acknowledged` label as a bypass. The
   bypass auto-clears on every new push to the PR (so you can't apply
   it once and forget).

This guard catches: a vrs²→m² conversion bug, a selector that latches
onto the wrong field, a ranker leg that silently inverts, a fixture
edit with a typo'd price, etc. The 20%/30%/25-point thresholds are
starting points — tune in `automation/diff_ranking.py` constants based
on the first few PRs.

## Phase 7e — repo setup checklist for the human

Create `docs/repo-setup.md` with the GitHub-UI steps that can't be
codified in workflows (these are one-time and need to be applied by the
repo owner):

1. Settings → Branches → add a branch protection rule for `main`:
   - Require status checks before merging: `ci`, `tests-required`,
     `ranking-diff`.
   - **Require branches to be up to date before merging** (this is
     load-bearing for the two-engineer flow — combined with the merge
     queue below, it prevents the "both PRs were green individually but
     break together" failure).
   - Require review from Code Owners.
   - Require approval count: 1 (Code Owners satisfy this).
   - Restrict who can push to matching branches.
   - Allow auto-merge.
   - **Enable the GitHub merge queue** for `main` with the same
     required status checks. This serializes merges and re-runs CI on
     each PR rebased onto the queued combination of pending PRs, which
     is the single most important check against concurrent breakage.
   - Do NOT require linear history (lets us squash freely).
2. Settings → General → Pull Requests → enable "Allow auto-merge",
   "Automatically delete head branches", and "Always suggest updating
   pull request branches."
3. Settings → Secrets and variables → Actions → add any secrets the new
   workflows need (probably none, but list any if added).
4. Add these labels in Issues → Labels (name, color, description):
   `safe-to-automerge`, `ranking-shift-acknowledged`,
   `no-test-required`, `area:scrapers`, `area:ranker`, `area:frontend`,
   `area:auth`, `area:infra`, `stacked-on`. The `area:*` labels are
   used by the auto-labeler in Phase 7f.
5. Verify CODEOWNERS resolves correctly: open a draft PR touching
   `pulpo/normalize.py` and confirm the right reviewer is auto-requested.

Each step in the doc should have a "✅ done" checkbox in markdown so the
human can mark them off.

## Phase 7f — concurrent-work safety (two engineers shipping in parallel)

These are the pieces that make two-people-on-trunk safe and fast. None
of them are optional; each prevents a specific failure mode that the
other phases don't cover.

1. **PR template with required intent fields.** Create
   `.github/pull_request_template.md`:

   ```markdown
   ## Summary
   <!-- one paragraph; what and why -->

   ## Touches
   <!-- comma-separated paths or area:* labels that describe scope, e.g.
   pulpo/scrapers/, samples/calibration/century21/ -->

   ## Stacked on
   <!-- "none" or "#42" if this depends on another PR landing first -->

   ## Risk
   <!-- "low / medium / high" + one sentence; high-risk PRs should not get
   safe-to-automerge -->

   ## Verification
   <!-- what you ran locally; the CI matrix is assumed -->
   ```

   Add a line at the bottom: "If `Stacked on` is set, this PR will be
   blocked from merging until the parent merges (enforced by the
   stacked-on check below)."

2. **Stacked-on check.** Add a job in `.github/workflows/ci.yml` that
   parses the PR body for a `Stacked on: #N` line and fails the build
   if PR #N is still open. Implement as a small Python script under
   `.github/scripts/check_stacked_on.py` invoked by the workflow.

3. **Area auto-labeler.** Add `.github/labeler.yml` and use the
   `actions/labeler@v5` action in a new workflow
   `.github/workflows/labeler.yml`. Mapping:

   ```yaml
   "area:scrapers":
     - changed-files:
         - any-glob-to-any-file: ['pulpo/scrapers/**', 'samples/calibration/**']
   "area:ranker":
     - changed-files:
         - any-glob-to-any-file: ['pulpo/ranker.py', 'pulpo/ranker_legs/**', 'pulpo/normalize.py', 'pulpo/units.py', 'pulpo/models.py']
   "area:frontend":
     - changed-files:
         - any-glob-to-any-file: ['web/**']
   "area:auth":
     - changed-files:
         - any-glob-to-any-file: ['api/**', 'vercel.json']
   "area:infra":
     - changed-files:
         - any-glob-to-any-file: ['.github/**', 'requirements*.txt', 'pyproject.toml', 'automation/**']
   ```

   These labels make it instantly visible in the PR list who should
   look at what; combined with CODEOWNERS, they're the "who reviews"
   answer.

4. **Auto-apply `safe-to-automerge` to trivially-safe PRs.** Add a job
   in `.github/workflows/automerge.yml` that auto-applies the label
   when ALL of these are true:
   - PR touches only paths matching the auto-mergeable allowlist from
     Phase 7a (`samples/`, `fixtures/`, `prompts/`, `docs/`, `*.md`,
     `web/data/*`, additive-only `tests/**`).
   - Diff is < 100 lines of real changes (use
     `git diff --shortstat` and parse insertions+deletions).
   - PR author is a repo collaborator.
   - Risk field in the PR body says "low".

   The human still authors the PR and can remove the label if they
   want a real review. This converts the "I have to remember to label
   it" friction into "I have to remember to UN-label if I want
   review" — which is the right default for a two-person team.

5. **Stale-branch reaper.** Add
   `.github/workflows/stale-branches.yml` that closes PRs and deletes
   branches with no activity for 14 days. Long-lived branches are the
   #1 source of "both PRs were green individually but conflict
   horribly" pain. Reasonable PRs ship in 1–2 days; anything older is
   either abandoned or needs a redesign.

6. **Daily ritual file.** Add `docs/daily-sync.md` containing a
   3-line template the engineers post in their shared channel each
   morning:

   ```
   yesterday: <what shipped>
   today: <what I'm working on, area:* tags>
   blocked: <none, or what>
   ```

   Plus a one-paragraph note: "this is async, takes 30 seconds, the
   only goal is to surface 'we're both about to refactor ranker.py'
   before either of you starts. Skip on weekends and holidays."

7. **Merge-order decision rules.** Add a section to `CONTRIBUTING.md`
   titled "Merge order when PRs touch each other" with this
   stop-at-first-yes ladder:

   1. Is one a hotfix? → it goes first.
   2. Does one logically depend on the other? → foundation goes first
      (declared via `Stacked on:`).
   3. Is one significantly smaller? → smaller goes first; bigger
      rebases.
   4. Is one lower-risk? → lower-risk first; risky one rebases onto a
      known-good main.
   5. None of the above → 60-second chat, whoever's at the keyboard
      merges, the other rebases.

   Followed by: "Always rebase, never merge-commit. Always declare
   territory in the daily sync. When the rebase looks horrible, pair
   instead of fighting it."

8. **Repo settings nudges in `docs/repo-setup.md`.** Add to the
   checklist: "✅ Settings → Repository → Default branch → make sure
   PRs always rebase (set 'Allow rebase merging' on, 'Allow merge
   commits' off, 'Allow squash merging' on as the default)." This
   makes accidentally pushing a merge commit physically impossible.

Acceptance for Phase 7f: open two simultaneous test PRs that touch
different files. Confirm: both get the right `area:*` labels, the
small-and-safe one auto-gets `safe-to-automerge`, the merge queue
serializes the merges and re-runs CI on the combined state, and a
deliberately-stacked PR is blocked until its parent lands.

## Verification

Before declaring done:

```bash
pytest -q
ruff check .
mypy --strict pulpo/
python3 -m pulpo.cli --offline
python3 automation/diff_ranking.py samples/ranked.csv samples/ranked.csv
# (the last one should report 0 deltas — sanity check)
```

Then open a tiny test PR (e.g. add a typo fix to a docstring) and
confirm: CI runs all the new jobs, ranking-diff passes (no diff), and
the `safe-to-automerge` label correctly enables auto-merge.

## Final summary

Write a ≤250-word summary covering: which workflows you added, what the
ranking-diff thresholds are and why, what's left for the human to do in
the GitHub UI (link to `docs/repo-setup.md`), any deviations from this
plan, and any new dev dependencies. End with **two** one-line examples:

- "Typical safe PR lifecycle: …" (the auto-merge happy path)
- "Typical concurrent-work PR lifecycle: …" (two PRs touching adjacent
  areas, including how the merge queue and `Stacked on:` field
  resolved the order)
