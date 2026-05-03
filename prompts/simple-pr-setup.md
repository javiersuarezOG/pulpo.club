# Minimum-viable PR setup for pulpo.club

You are setting up just enough governance for two people to ship safely
on this repo. Don't over-build it. Skip anything not listed here.

Read `README.md` first to understand the project. Don't add CODEOWNERS,
merge queues, labels, PR templates, stacked-on checks, or any other
process scaffolding that isn't explicitly in this prompt — they cost
more than they pay until the team grows past 3–4 people.

## What to build

**1. One GitHub Actions workflow at `.github/workflows/ci.yml`** —
triggered on `push` and `pull_request`. Steps:
- Checkout, set up Python 3.10, install `requirements.txt`.
- Run `pytest -q`.
- Run `ruff check .` (add `ruff` to a new `requirements-dev.txt`; don't
  pollute `requirements.txt`).

That's the entire workflow. Don't add coverage reports, type-checking,
or secret-scanning yet — we'll add those if/when they earn their place.

**2. A `CODEOWNERS` file at `.github/CODEOWNERS`** — exactly four
entries, one per line:

```
/pulpo/normalize.py    @owner
/pulpo/ranker.py       @owner
/pulpo/units.py        @owner
/api/                  @owner
```

Replace `@owner` with a `# TODO: replace with both engineers' GitHub
handles, e.g. @javier @colleague` comment so the human applies it.

**3. A short section in `README.md`** titled "How we ship" with this
exact content (don't paraphrase — keep it terse):

> - Small PRs (one concern, ideally <300 lines).
> - CI must be green to merge.
> - Files in `CODEOWNERS` need a 1-person review.
> - Everything else: if you've eyeballed it and CI is green, merge it.
> - Use rebase to update branches, never merge commits.
> - When two PRs touch each other: hotfix first, dependency first,
>   smaller first. When in doubt, talk for 60 seconds.

**4. Repo settings checklist at `docs/repo-setup.md`** — one short
markdown file with a checklist for the human to apply in the GitHub
UI:

```
- [ ] Settings → Branches → protect `main`:
      require status check `ci`, require Code Owners review.
- [ ] Settings → General → enable "Allow rebase merging" + "Allow squash
      merging", disable "Allow merge commits".
- [ ] Settings → General → enable "Automatically delete head branches".
```

Three checkboxes. That's it.

## Hard constraints

- Don't break `python3 -m pulpo.cli --offline` or the existing test
  suite. Run them before declaring done.
- Don't add new dependencies beyond `ruff` (in `requirements-dev.txt`).
- Don't create labels, PR templates, auto-labelers, merge queues,
  stale-branch workflows, or any "ritual" docs. We add those only if
  we hit real friction.
- Total new files: one workflow, one CODEOWNERS, one repo-setup doc,
  one section in README, one `requirements-dev.txt`. Five files. If
  you're creating more, stop and re-read this prompt.

## Verification

```bash
pytest -q
ruff check .
python3 -m pulpo.cli --offline
```

All three pass with no errors. Then write a ≤100-word summary covering
what you added, the three checkboxes the human still needs to click,
and one sentence on when we'd graduate to the heavier setup (rough
heuristic: when manual merging becomes annoying enough that you're
asking "can we automate this?").
