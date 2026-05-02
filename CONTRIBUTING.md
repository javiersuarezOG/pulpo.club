# Contributing to pulpo.club

## Branch structure

| Branch | Purpose |
|--------|---------|
| `main` | Production — deploys to pulpo-club.vercel.app automatically |
| `dev`  | Shared integration branch — merge here first, test together |
| `your-name/feature` | Your working branch, e.g. `shon/whatsapp-import` |

## Workflow

```
# 1. Always start from dev
git checkout dev
git pull origin dev

# 2. Create your branch
git checkout -b shon/my-feature

# 3. Do your work, commit often
git add .
git commit -m "feat: describe what you did"

# 4. Push and open a PR → dev
git push -u origin shon/my-feature
gh pr create --base dev --title "feat: my feature"

# 5. After review + approval, merge into dev
# 6. When dev is stable → PR from dev into main (deploys to prod)
```

## Rules

- **Never push directly to `main`** — always go through a PR
- **Never push directly to `dev`** — use your own branch + PR
- PRs to `main` require approval from @javiersuarezOG
- Run `python3 automation/run.py` locally before merging scraper changes
- Don't commit `.env`, `*.pyc`, or any credentials

## File ownership

| Path | Owner |
|------|-------|
| `pulpo/scrapers/` | Javier (scraper logic) |
| `web/index.html` | Either (frontend) |
| `api/` | Javier (auth/API) |
| `automation/` | Either |
| `web/data/` | Generated — do not edit by hand |

## Adding a new agent

Every new file under `pulpo/scrapers/`, `pulpo/agents/`, `pulpo/enrichers/`, or `pulpo/ranker_legs/` must ship with a matching test file under the corresponding `tests/` subdirectory. CI will fail the PR if the test file is absent. Use the `no-test-required` label only for pure docs or refactor PRs that add no new logic.
