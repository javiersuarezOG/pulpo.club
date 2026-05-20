"""Create PostHog funnels programmatically.

Funnel A: Home page -> Paid
Funnel B: Listing detail -> Paid
Funnel C: Detail-panel upgrade -> Paid (replaces post-#266 "Card intent"
          funnel; #305 made shelf/browse cards passthrough so the
          dominant conversion path now flows through the detail panel
          with trigger="detail_upgrade").
Funnel D: Activation -> Account engagement (post-Stripe loop)
Funnel E: Activation -> Continued browsing (post-Stripe loop)
Funnel F: Activation email delivery — proves the Stripe → us →
          Resend → Clerk → user chain is intact end-to-end. Six
          steps; starts at webhook.received so Stripe-delivery
          failures show up as 0→1 drops. Filters step 1 on
          invitation_sent=true (post-#360 Resend path) to exclude
          existing_user / auth_gated / no_email branches that
          legitimately don't send an email. Includes the new
          invitation.password_creation_opened and ticket_consumed
          events from PR #361/#363/#368/#374 so deliverability,
          ticket-race, and password-modal-bail drops are each
          distinguishable.

Funnels D + E share steps 0-3 (webhook.checkout_completed →
stripe.return_landed → invitation.password_creation_opened →
signin.completed[provider=clerk]) and diverge at step 4 to capture
the two end-states the user asked about: "updated account anyhow"
vs "kept browsing the website". Identity stitching post-#367:
posthog.identify() fires on signin.completed so anon distinct_id
resolves to the signed-in Person automatically.

Why a script: the funnel definitions are versioned with the codebase so
when an event name moves we update the script and re-run it. The PostHog
UI is for ad-hoc exploration, not the load-bearing conversion funnels.

The legacy "Funnel — Card intent → Paid (auto)" insight (pre-#305) is
intentionally orphaned in the PostHog UI — historical data is preserved
but no longer maintained by this script. Delete in the UI when ready.

Env:
  POSTHOG_PERSONAL_API_KEY   phx_... with scopes insight:write + project:read
  POSTHOG_PROJECT_ID         numeric, from the eu.posthog.com URL
  POSTHOG_HOST               defaults to https://eu.posthog.com
                             (ingestion host eu.i.posthog.com auto-swapped)

Usage:
  python3 scripts/posthog_create_funnels.py
  python3 scripts/posthog_create_funnels.py --date-from=-90d   # use = (leading - confuses argparse)
  python3 scripts/posthog_create_funnels.py --dry-run

Re-running re-uses the existing insight by name (PATCH).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def api_host() -> str:
    host = os.getenv("POSTHOG_HOST", "https://eu.posthog.com").strip().rstrip("/")
    return host.replace("://eu.i.posthog.com", "://eu.posthog.com").replace(
        "://us.i.posthog.com", "://us.posthog.com"
    )


def auth_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def request(method: str, url: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=auth_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code} {method} {url}\n{e.read().decode('utf-8', 'replace')}\n")
        raise


def find_existing(host: str, project_id: str, key: str, name: str) -> dict | None:
    url = f"{host}/api/projects/{project_id}/insights/?search={urllib.parse.quote(name)}"
    result = request("GET", url, key)
    for hit in result.get("results", []):
        if hit.get("name") == name:
            return hit
    return None


def upsert(host: str, project_id: str, key: str, payload: dict) -> dict:
    name = payload["name"]
    existing = find_existing(host, project_id, key, name)
    if existing:
        url = f"{host}/api/projects/{project_id}/insights/{existing['id']}/"
        return request("PATCH", url, key, payload)
    url = f"{host}/api/projects/{project_id}/insights/"
    return request("POST", url, key, payload)


def funnel_payload(name: str, description: str, steps: list[dict], date_from: str) -> dict:
    """Wrap a list of step entities into the funnel insight schema PostHog
    expects. Uses the new `query` (InsightVizNode + FunnelsQuery) schema —
    the legacy `filters` schema is rejected with 403 permission_denied for
    new insights as of 2025+."""
    return {
        "name": name,
        "description": description,
        "query": {
            "kind": "InsightVizNode",
            "source": {
                "kind": "FunnelsQuery",
                "series": steps,
                "dateRange": {"date_from": date_from},
                "funnelsFilter": {
                    "funnelVizType": "steps",
                    "funnelOrderType": "ordered",
                    "funnelWindowInterval": 14,
                    "funnelWindowIntervalUnit": "day",
                },
            },
        },
        "tags": ["conversion", "auto-created"],
    }


def step(order: int, event: str, properties: list[dict] | None = None) -> dict:
    # FunnelsQuery `series` entries are EventsNode objects. Order is
    # positional (index in the series array), not a field.
    del order
    e: dict = {"kind": "EventsNode", "event": event, "name": event}
    if properties:
        e["properties"] = properties
    return e


def prop(key: str, value, operator: str = "exact", ptype: str = "event") -> dict:
    return {"key": key, "value": value, "operator": operator, "type": ptype}


def build_home_funnel(date_from: str) -> dict:
    # Ordered funnel — intermediate events are allowed between steps.
    # Post-#305 the dominant anon/free path is:
    #   $pageview / → cta_routed (shelf_card, branch=passthrough)
    #   → detail.opened → free_month_modal.shown (trigger=detail_upgrade)
    #   → cta_clicked → checkout_redirected → webhook.checkout_completed.
    # Hero / header CTAs short-circuit to modal directly:
    #   $pageview / → cta_routed (hero_primary/header_primary)
    #   → free_month_modal.shown (trigger=hero_cta/header_cta) → …
    # Both paths satisfy this funnel's ordering.
    #
    # cta_clicked vs checkout_redirected splits "clicked CTA but never
    # reached Stripe" (rate-limit, network, promo retry fail) from
    # "Stripe redirect actually fired" — distinct diagnostics.
    #
    # Identity stitching: api/stripe/webhook.js calls posthog.alias() on
    # the anon distinct_id forwarded from the client, so the email-keyed
    # webhook step resolves to the same person as the anon $pageview.
    #
    # Paid users hit $pageview / but never see the modal. They inflate
    # the step-1 denominator but wash out at step 3 (cannot fire shown).
    # Conversion math from step 3 onward is correct; step 1 → step 3 is
    # a noisy ratio. If we want the "addressable conversion rate", filter
    # step 1 on the `plan` person property = NOT pro. Skipped for now —
    # paid users are a small slice of / traffic.
    steps = [
        step(0, "$pageview", [prop("$pathname", "/")]),
        step(1, "cta_routed"),
        step(2, "free_month_modal.shown"),
        step(3, "free_month_modal.cta_clicked"),
        step(4, "free_month_modal.checkout_redirected"),
        step(5, "webhook.checkout_completed"),
    ]
    return funnel_payload(
        name="Funnel — Home → Paid (auto)",
        description=(
            "/ $pageview → cta_routed → free_month_modal.shown → cta_clicked "
            "→ checkout_redirected → webhook.checkout_completed. Ordered: "
            "intermediate events (detail.opened post-#305) permitted between "
            "steps. Identity stitched via posthog.alias() at webhook. "
            "Owner: scripts/posthog_create_funnels.py."
        ),
        steps=steps,
        date_from=date_from,
    )


def build_listing_funnel(date_from: str) -> dict:
    # Post-#305 detail.opened captures ALL card-click entrants for every
    # tier — shelf_card / browse_card row in the matrix is now
    # passthrough across the board, so the card click opens the detail
    # panel (which has its own tier-aware soft-gating via lib/gating.ts).
    # Step 1 cta_routed fires from the in-panel upgrade CTAs (broker_
    # outbound, locked_thumb, locked_usp, more_photos_overlay) which all
    # dispatch through the matrix as cta_id=detail_upgrade. Before that
    # wiring landed the step was empty for the dominant path; ship the
    # in-panel routing change before relying on the conversion math.
    #
    # Direct-link entrants (shared /listing/<id> URLs) also flow through
    # this funnel — they hit detail.opened first, then convert via the
    # same in-panel CTAs. Paid users at step 0 wash out at step 2 because
    # they never see the modal.
    steps = [
        step(0, "detail.opened"),
        step(1, "cta_routed"),
        step(2, "free_month_modal.shown"),
        step(3, "free_month_modal.cta_clicked"),
        step(4, "free_month_modal.checkout_redirected"),
        step(5, "webhook.checkout_completed"),
    ]
    return funnel_payload(
        name="Funnel — Listing detail → Paid (auto)",
        description=(
            "detail.opened → cta_routed (cta_id=detail_upgrade) → "
            "free_month_modal.shown (trigger=detail_upgrade) → cta_clicked "
            "→ checkout_redirected → webhook.checkout_completed. Post-#305 "
            "shelf/browse clicks passthrough → detail.opened captures every "
            "card entrant; in-panel CTAs route through cta_id=detail_upgrade. "
            "Owner: scripts/posthog_create_funnels.py."
        ),
        steps=steps,
        date_from=date_from,
    )


def build_detail_panel_upgrade_funnel(date_from: str) -> dict:
    # Post-#305 the dominant anon/free conversion path runs through the
    # detail panel: card click → passthrough → detail.opened → in-panel
    # upgrade CTA → free_month_modal.shown (trigger=detail_upgrade) → …
    # This funnel filters every modal-side step on trigger=detail_upgrade
    # so it measures the detail-panel conversion in isolation, separate
    # from hero / header CTAs which use different trigger labels.
    #
    # Replaces the legacy "Card intent → Paid" funnel which became dead
    # when shelf/browse cards flipped from free_month_modal → passthrough.
    steps = [
        step(0, "detail.opened"),
        step(1, "free_month_modal.shown",
              [prop("trigger", "detail_upgrade")]),
        step(2, "free_month_modal.cta_clicked",
              [prop("trigger", "detail_upgrade")]),
        step(3, "free_month_modal.checkout_redirected",
              [prop("trigger", "detail_upgrade")]),
        step(4, "webhook.checkout_completed"),
    ]
    return funnel_payload(
        name="Funnel — Detail-panel upgrade → Paid (auto)",
        description=(
            "detail.opened → free_month_modal.shown / cta_clicked / "
            "checkout_redirected (all trigger=detail_upgrade) → "
            "webhook.checkout_completed. Replaces dead 'Card intent → Paid' "
            "(shelf/browse passthrough post-#305). Owner: "
            "scripts/posthog_create_funnels.py."
        ),
        steps=steps,
        date_from=date_from,
    )


def build_activation_account_funnel(date_from: str) -> dict:
    # Post-Stripe activation loop. Five-step funnel — the
    # canonical happy path after PRs #360 (Resend-sent activation
    # emails), #361/#363/#368/#374 (?__clerk_ticket=… URL marker
    # drives password creation directly), and #367 (PostHog
    # identify() on sign-in stitches anon → signed-in cleanly):
    #
    #   0. webhook.checkout_completed  — user paid; Stripe webhook
    #      handler created the Clerk invitation server-side.
    #   1. stripe.return_landed (account_welcome) — user hit
    #      /account?welcome=1 from Stripe's success_url (anon
    #      variant, anchors the funnel without Clerk-hydration
    #      latency).
    #   2. invitation.password_creation_opened (source=
    #      clerk_ticket_url) — user clicked the activation email;
    #      arrived at /?__clerk_ticket=…; Pulpo opened Clerk's
    #      hosted password modal.
    #   3. signin.completed (provider=clerk) — password created,
    #      Clerk signed the user in. #367 now fires posthog.identify()
    #      on this transition so anon distinct_id resolves to the
    #      Person.
    #   4. account.section_viewed — terminal "updated account"
    #      state.
    #
    # Drop-offs by step are diagnostic:
    #   0→1: paid but never returned to /account?welcome=1 (rare;
    #        Stripe redirect fail or instant tab-close).
    #   1→2: email delivered? clicked? Slice by
    #        webhook.activation_email_failed and
    #        welcome_modal.invitation_status_resolved status to
    #        attribute deliverability vs UX vs spam folder.
    #   2→3: ticket consumed? slice by
    #        invitation.ticket_consumed vs ticket_rejected to
    #        attribute Clerk SDK issues.
    #   3→4: signed in but didn't visit /account — measured by
    #        sibling 'Continued browsing' funnel terminating on
    #        route.changed instead.
    steps = [
        step(0, "webhook.checkout_completed"),
        step(1, "stripe.return_landed",
              [prop("surface", "account_welcome")]),
        step(2, "invitation.password_creation_opened",
              [prop("source", "clerk_ticket_url")]),
        step(3, "signin.completed", [prop("provider", "clerk")]),
        step(4, "account.section_viewed"),
    ]
    return funnel_payload(
        name="Funnel — Activation → Account engagement (auto)",
        description=(
            "webhook.checkout_completed → stripe.return_landed "
            "(account_welcome) → invitation.password_creation_opened "
            "(clerk_ticket_url; user clicked the activation email) → "
            "signin.completed (clerk) → account.section_viewed. Terminal: "
            "'updated account'. 1→2 drop = email deliverability / "
            "click-through. 2→3 = ticket consume / Clerk SDK. "
            "Owner: scripts/posthog_create_funnels.py."
        ),
        steps=steps,
        date_from=date_from,
    )


def build_activation_browsing_funnel(date_from: str) -> dict:
    # Sibling of build_activation_account_funnel. Steps 0-3 are
    # identical; step 4 measures the "kept browsing" terminal state —
    # the user navigated away from /account/* after activating. Uses
    # `not_icontains` because PostHog's exact-match operator can't
    # express "any path not starting with /account".
    steps = [
        step(0, "webhook.checkout_completed"),
        step(1, "stripe.return_landed",
              [prop("surface", "account_welcome")]),
        step(2, "invitation.password_creation_opened",
              [prop("source", "clerk_ticket_url")]),
        step(3, "signin.completed", [prop("provider", "clerk")]),
        step(4, "route.changed",
              [prop("to_path", "/account", operator="not_icontains")]),
    ]
    return funnel_payload(
        name="Funnel — Activation → Continued browsing (auto)",
        description=(
            "webhook.checkout_completed → stripe.return_landed "
            "(account_welcome) → invitation.password_creation_opened "
            "(clerk_ticket_url; user clicked the activation email) → "
            "signin.completed (clerk) → route.changed (to_path not_icontains "
            "'/account'). Terminal: 'kept browsing'. Pairs with Activation → "
            "Account engagement. Owner: scripts/posthog_create_funnels.py."
        ),
        steps=steps,
        date_from=date_from,
    )


def build_activation_email_delivery_funnel(date_from: str) -> dict:
    # Funnel F: proves the Stripe → us → Resend → Clerk → user-acted
    # chain is intact end-to-end, and pinpoints WHICH step drops users
    # when it isn't. Six steps after PR #360 (Resend takes over the
    # activation email from Clerk's queue) + PR #361/#363/#368/#374
    # (?__clerk_ticket=… URL marker drives password creation):
    #
    #   0. webhook.received — Stripe delivered, signature verified.
    #   1. webhook.checkout_completed
    #      (path=anonymous_invitation_created, invitation_sent=true)
    #      — the only Path-B branch that creates AND sends an
    #      invitation via Resend. Both filters together exclude the
    #      auth_gated / existing_user / no_email / dupe / race
    #      paths that legitimately set invitation_sent=false.
    #   2. welcome_modal.invitation_status_resolved
    #      (status=invitation_pending) — the client confirmed via
    #      GET /api/clerk/invitation-status that the pending
    #      invitation exists. Only fires on the initial
    #      /account?welcome=1 anon landing.
    #   3. invitation.password_creation_opened
    #      (source=clerk_ticket_url) — user clicked the Resend
    #      email; landed at /?__clerk_ticket=…; Pulpo opened the
    #      Clerk hosted password modal.
    #   4. invitation.ticket_consumed — Clerk validated the ticket
    #      (fresh, not already spent) and the SignUp resource is
    #      bound to it.
    #   5. signin.completed (provider=clerk) — password created,
    #      sign-in transition fired posthog.identify() to stitch
    #      anon → signed-in identity (#367).
    #
    # Drop-off semantics:
    #   0→1: webhook handler errored OR took a non-invitation Path-B
    #        branch OR Resend send failed (webhook.activation_email_failed
    #        is the sibling signal — slice on it to attribute).
    #   1→2: user never returned to /account?welcome=1 in an anon
    #        state — usually Stripe redirect race or close-on-Stripe.
    #   2→3: email deliverability / spam folder / copy not
    #        compelling enough — the step that surfaces SPF/DKIM/
    #        DMARC gaps.
    #   3→4: ticket already consumed (resent-link race) or invalid
    #        — slice by invitation.ticket_rejected for the
    #        complementary count.
    #   4→5: user opened the password modal but bailed before
    #        submitting; Clerk SDK error mid-flow.
    steps = [
        step(0, "webhook.received",
              [prop("type", "checkout.session.completed")]),
        step(1, "webhook.checkout_completed", [
            prop("path", "anonymous_invitation_created"),
            # PostHog stores invitation_sent as boolean (webhook.js
            # passes Python-true / Node-true); filter with the
            # native bool so the operator="exact" match resolves.
            prop("invitation_sent", True),
        ]),
        step(2, "welcome_modal.invitation_status_resolved",
              [prop("status", "invitation_pending")]),
        step(3, "invitation.password_creation_opened",
              [prop("source", "clerk_ticket_url")]),
        step(4, "invitation.ticket_consumed"),
        step(5, "signin.completed", [prop("provider", "clerk")]),
    ]
    return funnel_payload(
        name="Funnel — Activation email delivery (auto)",
        description=(
            "webhook.received → webhook.checkout_completed "
            "(anonymous_invitation_created, invitation_sent=true) → "
            "welcome_modal.invitation_status_resolved (invitation_pending) "
            "→ invitation.password_creation_opened (clerk_ticket_url) → "
            "invitation.ticket_consumed → signin.completed (clerk). "
            "Drops: 0→1 webhook/Resend fail; 1→2 Stripe-close; 2→3 email "
            "deliverability; 3→4 ticket race; 4→5 password bail."
        ),
        steps=steps,
        date_from=date_from,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date-from", default="-30d", help="PostHog date range, e.g. -30d, -90d (default: -30d)")
    parser.add_argument("--dry-run", action="store_true", help="Print payloads, don't POST")
    args = parser.parse_args()

    key = os.getenv("POSTHOG_PERSONAL_API_KEY", "").strip()
    project_id = os.getenv("POSTHOG_PROJECT_ID", "").strip()
    if not args.dry_run and (not key or not project_id):
        sys.stderr.write("Set POSTHOG_PERSONAL_API_KEY and POSTHOG_PROJECT_ID, or pass --dry-run.\n")
        return 1

    host = api_host()
    payloads = [
        build_home_funnel(args.date_from),
        build_listing_funnel(args.date_from),
        build_detail_panel_upgrade_funnel(args.date_from),
        build_activation_account_funnel(args.date_from),
        build_activation_browsing_funnel(args.date_from),
        build_activation_email_delivery_funnel(args.date_from),
    ]

    if args.dry_run:
        print(json.dumps(payloads, indent=2))
        return 0

    for payload in payloads:
        result = upsert(host, project_id, key, payload)
        insight_id = result.get("short_id") or result.get("id")
        url = f"{host}/project/{project_id}/insights/{insight_id}"
        print(f"OK  {payload['name']}\n    {url}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
