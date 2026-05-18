"""Create PostHog funnels programmatically.

Funnel A: Home page -> Paid
Funnel B: Listing detail (any listing) -> Paid
Funnel C: Card-click intent (shelf/browse/featured/hero_just_in) -> Paid
          — added post-#266 to measure the dominant anon/free conversion
          path that bypasses detail.opened.

Why a script: the funnel definitions are versioned with the codebase so
when an event name moves we update the script and re-run it. The PostHog
UI is for ad-hoc exploration, not the load-bearing conversion funnels.

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
    # Canonical funnel from PR #262 (FreeMonthModal):
    #   $pageview → cta_routed → modal.shown → modal.cta_clicked
    #   → modal.checkout_redirected → webhook.checkout_completed.
    # modal.cta_clicked vs checkout_redirected splits "clicked CTA but
    # never reached Stripe" (rate-limit, network, promo retry fail) from
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
    # paid users are a small slice of /  traffic.
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
            "Home pageview → intent (cta_routed) → free-month modal shown "
            "→ modal CTA clicked → Stripe redirect → webhook confirms payment. "
            "Identity stitched via posthog.alias() at webhook time. "
            "Owner: scripts/posthog_create_funnels.py."
        ),
        steps=steps,
        date_from=date_from,
    )


def build_listing_funnel(date_from: str) -> dict:
    # Post-#262 + #266: `detail.opened` fires for three populations.
    #   1. Direct-link entrants (shared/external links to /listing/<id>)
    #   2. Paid (pro / agency) users opening any listing — including real
    #      shelf cards on the homepage, which #266 wired to fire
    #      `app.openListing()` on the passthrough branch.
    #   3. Free users clicking a card that lands on passthrough by tier
    #      (rare — most free-user CTA branches resolve to the modal).
    # Anon/free shelf+browse clicks bypass detail.opened entirely and
    # route into the conversion modal (see build_any_card_intent_funnel).
    # Conversion math from step 2 (modal.shown) onward stays correct;
    # paid users at step 0 wash out at step 2 because they never see the
    # modal. If you want the addressable conversion rate, filter step 0
    # on `plan` person property ≠ pro.
    #
    # All other steps mirror the home funnel.
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
            "detail.opened (any listing) → intent (cta_routed) "
            "→ free-month modal shown → modal CTA clicked → Stripe redirect "
            "→ webhook confirms payment. Post-PR #266: detail.opened "
            "captures direct-link entrants + paid users opening real "
            "listings from shelf cards. Anon/free shelf+browse-card clicks "
            "still bypass detail.opened — they route straight into the "
            "free-month modal (see the 'Card intent → Paid' funnel for that "
            "population). Owner: scripts/posthog_create_funnels.py."
        ),
        steps=steps,
        date_from=date_from,
    )


def build_any_card_intent_funnel(date_from: str) -> dict:
    # Post-#262 the dominant anon/free conversion path is:
    #   shelf/browse/featured card click → cta_routed (cta_id=<card>)
    #   → free_month_modal opens directly (NO detail.opened).
    # Funnel B (detail.opened → paid) therefore misses these users
    # entirely. This funnel captures every card-click intent regardless
    # of branch, by filtering cta_routed on the four card-origin
    # cta_id values (see web/app/lib/cta-routing.ts CtaId union).
    #
    # Paid users at step 0 hit passthrough → openListing and never reach
    # step 1 (modal.shown), washing out cleanly. So this funnel reads
    # as the addressable-population conversion rate without needing a
    # person-property filter.
    steps = [
        step(0, "cta_routed", [
            prop(
                "cta_id",
                ["shelf_card", "browse_card", "featured_deal", "hero_just_in"],
                operator="exact",
            ),
        ]),
        step(1, "free_month_modal.shown"),
        step(2, "free_month_modal.cta_clicked"),
        step(3, "free_month_modal.checkout_redirected"),
        step(4, "webhook.checkout_completed"),
    ]
    return funnel_payload(
        name="Funnel — Card intent → Paid (auto)",
        description=(
            "cta_routed (cta_id ∈ shelf_card / browse_card / featured_deal / "
            "hero_just_in) → free-month modal shown → modal CTA clicked → "
            "Stripe redirect → webhook confirms payment. Post-PR #262 the "
            "card-click → modal path is the dominant anon/free conversion "
            "route; this funnel measures it directly. Complements the "
            "'Listing detail → Paid' funnel, which only sees direct-link "
            "entrants and paid users. Owner: scripts/posthog_create_funnels.py."
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
        build_any_card_intent_funnel(args.date_from),
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
