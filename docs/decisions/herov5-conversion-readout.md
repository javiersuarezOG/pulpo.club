# HeroV5 home-conversion readout

**Status**: pending data refresh
**Decision owner**: Sebastian + Javier
**Data collected by**: agent (see `scripts/posthog_herov5_conversion.py`)
**Decision due by**: 2026-06-10 (7 days from PR merge)
**PRD reference**: P1-7

## Context

[#623 ramped HeroV5 to default on 2026-05-25](https://github.com/javiersuarezOG/pulpo.club/pull/623). HeroV5 has no in-page Pro CTA; all destination cards route to browse/discovery. PRD P1-7 asks Data Science whether discovery-led home is intentional or whether home conversion regressed enough to restore a Pro CTA.

This doc is the artifact. The script `scripts/posthog_herov5_conversion.py` re-runs the comparison on demand so the decision is grounded in PostHog data, not vibes.

## Funnel

```
paid_home_rendered
  → cta_routed
    → free_month_modal.shown
      → upgrade.checkout_started
        → stripe.checkout_completed
```

End-to-end conversion = `stripe.checkout_completed / paid_home_rendered`.

## Decision rule

Per PRD P1-7 + plan PR-4B:

- **Restore Pro CTA** if conversion is down **>10% relative** AND **p<0.05** (two-proportion z-test) between equivalent-length pre/post windows.
- **Keep discovery-led home** if conversion is **within ±10% relative**.
- **Inconclusive / extend window** if either window has **<100 paid_home_rendered events** OR the test is undefined.
- **Monitor** if the delta is large but not statistically significant.

The 10% threshold deliberately accepts a small regression in exchange for the discovery-led UX (cohort tests on similar B2C funnels show 5-15% noise from week-of-month effects alone — 10% is a defensible threshold above noise).

## Latest run

Run `scripts/posthog_herov5_conversion.py` to refresh this section. Paste the output below this line and replace anything stale.

> _No data yet — run the script and paste output here._

```
# (paste table + recommendation here)
```

## History

| Run date | Pre window | Post window | Pre conversion | Post conversion | Δ relative | p-value | Recommendation | Decision |
|---|---|---|---|---|---|---|---|---|
| _pending_ | | | | | | | | |

## Decision log

- _Pending first data run._

## How to refresh

```bash
POSTHOG_PROJECT_ID=... \
POSTHOG_PERSONAL_API_KEY=... \
python3 scripts/posthog_herov5_conversion.py
```

Append the markdown output above. Update the History table. If the recommendation has changed since the last run, add a row to the Decision log explaining what Product + Data Science chose and why.

## Related

- HeroV5 PR: [#623](https://github.com/javiersuarezOG/pulpo.club/pull/623)
- PRD: `docs/prds/system-health-audit-2026-06-02.md` (P1-7)
- Plan: [`~/.claude/plans/this-plan-users-sehonores-claude-plans-i-parallel-sutherland.md`](../../) (PR-4B)
- CLAUDE.md "NEVER ship a broken auth/billing flow" — applies if a CTA is restored (Stripe sandbox dry-run required).
