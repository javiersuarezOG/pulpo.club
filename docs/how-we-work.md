# How we work — pulpo.club

Two people, small project, ship fast. Here's the whole rulebook.

## The four rules

1. **Small PRs.** One thing at a time. If it's bigger than a day's
   work, split it.
2. **CI must be green to merge.** Tests run automatically on every PR.
3. **Some files need a second pair of eyes.** GitHub will ask for a
   review when you touch `pulpo/normalize.py`, `pulpo/ranker.py`,
   `pulpo/units.py`, or anything in `api/`. These are the files where a
   silent bug would corrupt member data — they're worth the 5-minute
   review every time.
4. **Everything else: if CI is green and you've looked at the diff,
   merge it.** No labels to apply, no approvals to wait for. Just ship.

## When our PRs touch each other

Stop at the first one that applies:

1. Is one a hotfix? → that one goes first.
2. Does one depend on the other? → the dependency goes first.
3. Is one smaller? → smaller goes first; bigger rebases.
4. None of the above? → DM each other for 30 seconds, decide, move on.

## Two technical defaults

- **Rebase to update your branch**, never merge-commit. Repo settings
  enforce this so you basically can't get it wrong.
- **Don't let branches get old.** If a PR is sitting for 2+ days
  without progress, either ship it or close it.

## When to talk

Most of the time you don't need to. The PR description and the diff
say enough. Hop on a call when:

- You're both about to refactor the same area.
- You've already had two failed attempts at the same problem.
- You're changing something architectural (the way agents register, the
  auth model, etc.).

That's the whole doc. We'll add more rules only if we feel pain.
