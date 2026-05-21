"""Create the PostHog Performance dashboards programmatically.

Builds three dashboards out of one bundle of HogQL-backed insights:

  - Performance — Geo Latency      (LCP / API / data-fetch / web-vitals
                                    "good" rate, all split by Central
                                    America / North America / Europe)
  - Performance — Image Health     (image.error + image.stuck rates +
                                    LCP element breakdown per route)
  - Performance — External Services (perf.api_call P50/P95 by endpoint
                                    × region; placeholder cards for the
                                    Clerk + Stripe handshake events
                                    that PR-perf-5c will populate)

Why a script: same rationale as scripts/posthog_create_funnels.py — the
query definitions are versioned with the codebase. When an event name
moves, we update the script and re-run it. Re-runs upsert by insight
name (idempotent).

Env vars (same contract as the funnels script):
  POSTHOG_PERSONAL_API_KEY   phx_... with scopes insight:write +
                             dashboard:write + project:read
  POSTHOG_PROJECT_ID         numeric, from the eu.posthog.com URL
  POSTHOG_HOST               defaults to https://eu.posthog.com

Usage:
  python3 scripts/posthog_setup_perf_dashboards.py
  python3 scripts/posthog_setup_perf_dashboards.py --dry-run
  python3 scripts/posthog_setup_perf_dashboards.py --days=14

Insights that reference events not yet shipped (perf.clerk_modal_opened,
perf.stripe_redirect — wired in PR-perf-5c) are still created — they
just show "no data yet" until the events flow. Better than gating
dashboard scaffolding on the implementation of every event.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

# The three geo cohorts. Embedded as a CASE WHEN in every HogQL query so
# we can split metrics by geo without depending on PostHog cohorts (which
# have a max age / staleness window we'd have to manage). Keep the lists
# in sync with the plan: if a country is added to a region, every dashboard
# query needs the update.
GEO_CENTRAL_AMERICA = "'SV','GT','HN','NI','CR','PA','BZ','MX'"
GEO_NORTH_AMERICA = "'US','CA'"
GEO_EUROPE = "'ES','DE','FR','IT','PT','GB','IE','NL','BE','CH','AT','SE','NO','DK','FI','PL'"


def geo_case() -> str:
    """Returns the CASE expression every dashboard insight uses to bin a
    record into one of the four geo cohorts. Repetitive but explicit —
    PostHog cohort references would obscure the slice rule."""
    return (
        "CASE "
        f"WHEN properties.$geoip_country_code IN ({GEO_CENTRAL_AMERICA}) THEN 'Central America' "
        f"WHEN properties.$geoip_country_code IN ({GEO_NORTH_AMERICA}) THEN 'North America' "
        f"WHEN properties.$geoip_country_code IN ({GEO_EUROPE}) THEN 'Europe' "
        "ELSE 'Other' END"
    )


# ── HogQL query bodies ──────────────────────────────────────────────────

def q_lcp_by_geo(days: int) -> str:
    return f"""
SELECT
  {geo_case()} AS geo,
  properties.route AS route,
  round(quantile(0.5)(toFloat(properties.value))) AS p50,
  round(quantile(0.75)(toFloat(properties.value))) AS p75,
  round(quantile(0.95)(toFloat(properties.value))) AS p95,
  count() AS n
FROM events
WHERE event = 'web_vitals.lcp' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY geo, route
ORDER BY geo, p95 DESC
""".strip()


def q_api_call_by_geo(days: int) -> str:
    return f"""
SELECT
  {geo_case()} AS geo,
  properties.endpoint AS endpoint,
  properties.vercel_region AS region,
  round(quantile(0.5)(toFloat(properties.ms))) AS p50_total_ms,
  round(quantile(0.95)(toFloat(properties.ms))) AS p95_total_ms,
  round(quantile(0.5)(toFloat(properties.server_ms))) AS p50_server_ms,
  round(quantile(0.95)(toFloat(properties.server_ms))) AS p95_server_ms,
  count() AS n
FROM events
WHERE event = 'perf.api_call' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY geo, endpoint, region
ORDER BY p95_total_ms DESC
""".strip()


def q_data_fetch_by_geo(days: int) -> str:
    return f"""
SELECT
  {geo_case()} AS geo,
  properties.file AS file,
  properties.cache AS cache_state,
  round(quantile(0.5)(toFloat(properties.ms))) AS p50_ms,
  round(quantile(0.95)(toFloat(properties.ms))) AS p95_ms,
  round(avg(toFloat(properties.bytes)) / 1024) AS avg_kb,
  count() AS n
FROM events
WHERE event = 'perf.data_fetch' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY geo, file, cache_state
ORDER BY file, geo
""".strip()


def q_web_vitals_good_rate(days: int) -> str:
    return f"""
SELECT
  {geo_case()} AS geo,
  event AS metric,
  countIf(properties.rating = 'good') AS good_count,
  count() AS total,
  round(100.0 * countIf(properties.rating = 'good') / count(), 1) AS good_pct
FROM events
WHERE event IN ('web_vitals.lcp','web_vitals.inp','web_vitals.cls','web_vitals.ttfb')
  AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY geo, metric
ORDER BY geo, metric
""".strip()


def q_asset_load_by_geo(days: int) -> str:
    return f"""
SELECT
  {geo_case()} AS geo,
  properties.kind AS asset_kind,
  properties.cache AS cache_state,
  round(quantile(0.95)(toFloat(properties.ms))) AS p95_ms,
  round(avg(toFloat(properties.bytes)) / 1024) AS avg_kb,
  count() AS n
FROM events
WHERE event = 'perf.asset_load' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY geo, asset_kind, cache_state
ORDER BY geo, asset_kind
""".strip()


def q_image_error_rate(days: int) -> str:
    return f"""
WITH sessions AS (
  SELECT count(DISTINCT $session_id) AS s
  FROM events WHERE timestamp >= now() - INTERVAL {days} DAY
)
SELECT
  properties.source AS surface,
  count() AS errors,
  round(100.0 * count() / (SELECT s FROM sessions), 3) AS errors_per_100_sessions
FROM events
WHERE event = 'image.error' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY surface
ORDER BY errors DESC
""".strip()


def q_image_stuck_rate(days: int) -> str:
    return f"""
SELECT
  properties.source AS surface,
  toBool(properties.is_local) AS is_local_photo,
  count() AS stuck,
  toString(round(100.0 * countIf(toBool(properties.was_cached_likely)) / count(), 1)) || '%' AS pct_cache_lookalike
FROM events
WHERE event = 'image.stuck' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY surface, is_local_photo
ORDER BY stuck DESC
""".strip()


def q_lcp_element_breakdown(days: int) -> str:
    return f"""
SELECT
  splitByChar('?', properties.$current_url)[1] AS path,
  properties.element_tag AS element,
  round(quantile(0.5)(toFloat(properties.ms))) AS p50_ms,
  count() AS n
FROM events
WHERE event = 'web_vitals.lcp.attribution' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY path, element
HAVING n >= 20
ORDER BY path, n DESC
""".strip()


# Stubs for events PR-perf-5c will ship — included so the dashboards are
# complete the day 5c lands. Until then they just say "no data yet".

def q_clerk_modal_open(days: int) -> str:
    return f"""
SELECT
  {geo_case()} AS geo,
  properties.intent AS intent,
  round(quantile(0.5)(toFloat(properties.ms_from_click))) AS p50_ms,
  round(quantile(0.95)(toFloat(properties.ms_from_click))) AS p95_ms,
  count() AS n
FROM events
WHERE event = 'perf.clerk_modal_opened' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY geo, intent
ORDER BY p95_ms DESC
""".strip()


def q_clerk_chunk_load(days: int) -> str:
    return f"""
SELECT
  {geo_case()} AS geo,
  properties.cache AS cache_state,
  round(quantile(0.5)(toFloat(properties.ms))) AS p50_ms,
  round(quantile(0.95)(toFloat(properties.ms))) AS p95_ms,
  count() AS n
FROM events
WHERE event = 'perf.clerk_chunk_load' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY geo, cache_state
ORDER BY geo, cache_state
""".strip()


def q_stripe_redirect(days: int) -> str:
    return f"""
SELECT
  {geo_case()} AS geo,
  round(quantile(0.5)(toFloat(properties.ms_from_click_to_redirect))) AS p50_ms,
  round(quantile(0.95)(toFloat(properties.ms_from_click_to_redirect))) AS p95_ms,
  count() AS n
FROM events
WHERE event = 'perf.stripe_redirect' AND timestamp >= now() - INTERVAL {days} DAY
GROUP BY geo
ORDER BY p95_ms DESC
""".strip()


# ── PostHog API client (cribbed from posthog_create_funnels.py) ─────────

def api_host() -> str:
    host = os.getenv("POSTHOG_HOST", "https://eu.posthog.com").strip().rstrip("/")
    return host.replace("://eu.i.posthog.com", "://eu.posthog.com").replace(
        "://us.i.posthog.com", "://us.posthog.com"
    )


def auth_headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def http(method: str, url: str, key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=auth_headers(key))
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code} {method} {url}\n{e.read().decode('utf-8', 'replace')}\n")
        raise


def find_insight(host: str, project_id: str, key: str, name: str) -> dict | None:
    url = f"{host}/api/projects/{project_id}/insights/?search={urllib.parse.quote(name)}"
    result = http("GET", url, key)
    for hit in result.get("results", []):
        if hit.get("name") == name:
            return hit
    return None


def find_dashboard(host: str, project_id: str, key: str, name: str) -> dict | None:
    url = f"{host}/api/projects/{project_id}/dashboards/?search={urllib.parse.quote(name)}"
    result = http("GET", url, key)
    for hit in result.get("results", []):
        if hit.get("name") == name:
            return hit
    return None


def upsert_insight(
    host: str, project_id: str, key: str, name: str, description: str, hogql: str,
) -> dict:
    payload = {
        "name": name,
        "description": description,
        "query": {
            "kind": "DataTableNode",
            "source": {"kind": "HogQLQuery", "query": hogql},
            "showSearch": False,
        },
        "tags": ["perf-audit", "auto-created"],
    }
    existing = find_insight(host, project_id, key, name)
    if existing:
        url = f"{host}/api/projects/{project_id}/insights/{existing['id']}/"
        return http("PATCH", url, key, payload)
    url = f"{host}/api/projects/{project_id}/insights/"
    return http("POST", url, key, payload)


def upsert_dashboard(
    host: str, project_id: str, key: str, name: str, description: str, insight_ids: list[int],
) -> dict:
    existing = find_dashboard(host, project_id, key, name)
    payload = {"name": name, "description": description, "tags": ["perf-audit"]}
    if existing:
        dash = existing
        url = f"{host}/api/projects/{project_id}/dashboards/{dash['id']}/"
        http("PATCH", url, key, payload)
    else:
        url = f"{host}/api/projects/{project_id}/dashboards/"
        dash = http("POST", url, key, payload)
    # Wire insights to the dashboard. Re-attaching an already-attached
    # insight is a no-op; PostHog dedupes on (dashboard, insight).
    for insight_id in insight_ids:
        try:
            http(
                "POST",
                f"{host}/api/projects/{project_id}/dashboards/{dash['id']}/add_insight/",
                key,
                {"insight_id": insight_id},
            )
        except urllib.error.HTTPError as e:
            # 400 typically means "already on this dashboard" — fine.
            if e.code != 400:
                raise
    return dash


# ── Driver ──────────────────────────────────────────────────────────────

INSIGHT_PLAN = [
    # (group_dashboard, name, description, query_builder)
    (
        "Performance — Geo Latency",
        "LCP P50/P75/P95 by geo × route",
        "Largest Contentful Paint quantiles, split by geo cohort + route. Anything above 2.5 s for the cohort's P75 is a problem.",
        q_lcp_by_geo,
    ),
    (
        "Performance — Geo Latency",
        "API call latency by geo × endpoint × region",
        "perf.api_call quantiles. total_ms = full round-trip; server_ms = function-runtime only. Network = total − server. Tells us whether a slow endpoint is the function or the network.",
        q_api_call_by_geo,
    ),
    (
        "Performance — Geo Latency",
        "Data file fetch latency by geo × file",
        "ranked.json / ranked.list.json / last_updated.json / featured.json fetch quantiles with cache hint. Surfaces CDN cold-cache regions.",
        q_data_fetch_by_geo,
    ),
    (
        "Performance — Geo Latency",
        "Web Vitals — 'good' rate by geo × metric",
        "SLO-style view: what % of sessions in each geo cohort land in the web.dev 'good' bucket for LCP / INP / CLS / TTFB.",
        q_web_vitals_good_rate,
    ),
    (
        "Performance — Geo Latency",
        "Static asset load P95 by geo × kind × cache",
        "perf.asset_load P95 for entry / chunk / css / webp, split by Vercel CDN cache state. Cold-cache rate climbing → edge eviction.",
        q_asset_load_by_geo,
    ),
    (
        "Performance — Image Health",
        "Image error rate per 100 sessions by surface",
        "image.error count normalized against session count. Anything above 0.5 per 100 sessions per surface is a regression signal.",
        q_image_error_rate,
    ),
    (
        "Performance — Image Health",
        "Stuck image rate by surface × local/remote",
        "image.stuck (8 s without onLoad or onError). Local stuck rates flag pipeline regressions; remote stuck rates flag broker CDN issues.",
        q_image_stuck_rate,
    ),
    (
        "Performance — Image Health",
        "LCP element breakdown by route",
        "Which DOM element wins LCP per page. On /listing/:id this should be 'img' (gallery-main); on / it should be the hero photo.",
        q_lcp_element_breakdown,
    ),
    (
        "Performance — External Services",
        "Clerk hosted modal open latency by geo (PR-perf-5c)",
        "perf.clerk_modal_opened — click → first interactive. Empty until PR-perf-5c lands the event.",
        q_clerk_modal_open,
    ),
    (
        "Performance — External Services",
        "Clerk SDK chunk load latency by geo (PR-perf-5c)",
        "perf.clerk_chunk_load — React.lazy() resolve time for the Clerk bundle. Empty until PR-perf-5c lands the event.",
        q_clerk_chunk_load,
    ),
    (
        "Performance — External Services",
        "Stripe redirect timing by geo (PR-perf-5c)",
        "perf.stripe_redirect — Upgrade click → window.location.assign. Empty until PR-perf-5c lands the event.",
        q_stripe_redirect,
    ),
]


DASHBOARDS = {
    "Performance — Geo Latency": (
        "Real-user perf metrics sliced by Central America / North America / "
        "Europe / Other. Built by scripts/posthog_setup_perf_dashboards.py — "
        "see perf-audit plan in ~/.claude/plans/."
    ),
    "Performance — Image Health": (
        "image.error + image.stuck rates per surface + LCP element breakdown. "
        "Built by scripts/posthog_setup_perf_dashboards.py."
    ),
    "Performance — External Services": (
        "Clerk modal-open + chunk-load + Stripe redirect latency. Three cards "
        "populate when PR-perf-5c lands. Built by "
        "scripts/posthog_setup_perf_dashboards.py."
    ),
}


def _load_env_file() -> None:
    """Best-effort `.env` loader. Reads `<repo-root>/.env` if present and
    sets any KEY=VALUE pairs into os.environ unless already set. Lets
    `python3 scripts/posthog_setup_perf_dashboards.py` read POSTHOG_*
    values from the same `.env` Vite + Vercel-dev already use, without
    adding python-dotenv as a dependency.

    Format: `KEY=value` per line, `#` comments allowed, surrounding
    single/double quotes stripped. Anything else is ignored silently
    (existing values in os.environ always win — so `export FOO=bar` on
    the shell still beats `.env`).
    """
    import pathlib
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    env_path = repo_root / ".env"
    if not env_path.is_file():
        return
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Strip matching surrounding quotes (single or double).
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        # Permissions / encoding hiccups — silently fall through; the
        # main() function will fail fast on missing env vars with a
        # clear message that doesn't mention `.env` so the user still
        # has the option of `export` if their file is unreadable.
        pass


def main() -> int:
    p = argparse.ArgumentParser(description="Stand up PostHog perf dashboards.")
    p.add_argument("--days", type=int, default=7,
                   help="Rolling window for every query (default: 7).")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the HogQL bodies without hitting the PostHog API.")
    args = p.parse_args()

    # Load .env BEFORE reading env vars so `.env` works seamlessly
    # alongside the existing `export FOO=bar` shell pattern. Shell
    # exports always win — see _load_env_file().
    _load_env_file()

    key_raw = os.getenv("POSTHOG_PERSONAL_API_KEY")
    project_raw = os.getenv("POSTHOG_PROJECT_ID")
    if not args.dry_run and (not key_raw or not project_raw):
        sys.stderr.write(
            "Missing POSTHOG_PERSONAL_API_KEY or POSTHOG_PROJECT_ID. "
            "Re-run with --dry-run to inspect the queries.\n"
        )
        return 1
    # Narrow for the type checker — by here either we're in dry-run (and
    # never use these) or both env vars are set.
    key: str = key_raw or ""
    project: str = project_raw or ""
    host = api_host()

    grouped: dict[str, list[int]] = {n: [] for n in DASHBOARDS}
    for dashboard_name, insight_name, description, build in INSIGHT_PLAN:
        hogql = build(args.days)
        if args.dry_run:
            print(f"\n# {dashboard_name} / {insight_name}\n# {description}\n{hogql}\n")
            continue
        result = upsert_insight(host, project, key, insight_name, description, hogql)
        grouped[dashboard_name].append(result["id"])
        short = result.get("short_id") or result.get("id")
        print(f"  ✓ insight {short}: {insight_name}")

    if args.dry_run:
        return 0

    for name, description in DASHBOARDS.items():
        dash = upsert_dashboard(host, project, key, name, description, grouped[name])
        short = dash.get("id")
        print(f"  ✓ dashboard {short}: {name}  ({len(grouped[name])} insights)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
