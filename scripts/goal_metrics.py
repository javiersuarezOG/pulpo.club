"""Read a goal's objective metric + guardrails from PostHog (HogQL).

The machine-readable half of the goals/ optimization protocol
(goals/README.md). One invocation = one measurement, strict JSON on
stdout so a /goal-driven iteration can parse it without scraping prose.

Query contract: every hogql in a goal-spec must SELECT columns aliased
``value`` and ``sample_n`` (single row). Guardrails with
``source: "supply"`` are skipped here (listed under ``skipped``) — they
are evaluated by scripts/goal_supply_metrics.py; mixed goals run both
readers.

Env (same key as scripts/posthog_create_funnels.py):
  POSTHOG_PERSONAL_API_KEY   phx_... — additionally needs scope query:read
  POSTHOG_PROJECT_ID         numeric, from the eu.posthog.com URL
  POSTHOG_HOST               defaults to https://eu.posthog.com

Usage:
  python3 scripts/goal_metrics.py --goal conversion-popup
  python3 scripts/goal_metrics.py --hogql "SELECT count() AS value, count() AS sample_n FROM events WHERE timestamp > now() - INTERVAL 7 DAY"
  python3 scripts/goal_metrics.py --goal conversion-popup --dry-run   # print queries, no API call
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from goal_registry import load_spec  # noqa: E402


def api_host() -> str:
    host = os.getenv("POSTHOG_HOST", "https://eu.posthog.com").strip().rstrip("/")
    return host.replace("://eu.i.posthog.com", "://eu.posthog.com").replace(
        "://us.i.posthog.com", "://us.posthog.com"
    )


def run_hogql(host: str, project_id: str, key: str, hogql: str) -> dict:
    """POST the query; return {value, sample_n} from the first result row."""
    url = f"{host}/api/projects/{project_id}/query/"
    body = json.dumps({"query": {"kind": "HogQLQuery", "query": hogql}}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        raise SystemExit(f"HTTP {e.code} from PostHog query API:\n{detail}") from e
    columns = [str(c) for c in payload.get("columns", [])]
    results = payload.get("results") or []
    if not results:
        return {"value": None, "sample_n": 0}
    row = results[0]
    by_col = dict(zip(columns, row))
    value = by_col.get("value", row[0] if row else None)
    sample_n = by_col.get("sample_n", 0)
    return {
        "value": None if value is None else float(value),
        "sample_n": int(sample_n or 0),
    }


def guardrail_pass(op: str, value: float | None, threshold: float) -> bool | None:
    """None = indeterminate (no data) — the caller decides; the protocol
    treats indeterminate guardrails as failing-safe (hold, not change)."""
    if value is None:
        return None
    return value <= threshold if op == "<=" else value >= threshold


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--goal", help="goal name under goals/")
    group.add_argument("--hogql", help="ad-hoc HogQL (must alias value, sample_n)")
    parser.add_argument("--dry-run", action="store_true", help="print queries, skip the API")
    args = parser.parse_args()

    queries: list[tuple[str, str, dict]] = []  # (label, hogql, guardrail-meta)
    skipped: list[str] = []
    out: dict = {"measured_at": datetime.now(timezone.utc).isoformat()}

    if args.goal:
        spec = load_spec(args.goal)
        out["goal"] = args.goal
        metric = spec["metric"]
        if metric["source"] != "posthog":
            out["note"] = (
                "metric.source is not posthog — objective comes from "
                "scripts/goal_supply_metrics.py; only posthog guardrails run here"
            )
        else:
            queries.append(("metric", metric["hogql"], {}))
        for g in spec.get("guardrails", []):
            if g.get("source") == "posthog":
                queries.append((f"guardrail:{g['name']}", g["hogql"], g))
            else:
                skipped.append(g["name"])
    else:
        out["goal"] = None
        queries.append(("metric", args.hogql, {}))

    if args.dry_run:
        out["queries"] = [{"label": label, "hogql": q} for label, q, _ in queries]
        out["skipped"] = skipped
        print(json.dumps(out, indent=2))
        return 0

    key = os.getenv("POSTHOG_PERSONAL_API_KEY", "").strip()
    project_id = os.getenv("POSTHOG_PROJECT_ID", "").strip()
    if not key or not project_id:
        sys.stderr.write(
            "Set POSTHOG_PERSONAL_API_KEY (scope query:read) and "
            "POSTHOG_PROJECT_ID, or pass --dry-run.\n"
        )
        return 1

    host = api_host()
    guardrails: list[dict] = []
    for label, hogql, meta in queries:
        result = run_hogql(host, project_id, key, hogql)
        if label == "metric":
            out["metric"] = result
        else:
            ok = guardrail_pass(meta["op"], result["value"], meta["threshold"])
            guardrails.append(
                {
                    "name": meta["name"],
                    "value": result["value"],
                    "sample_n": result["sample_n"],
                    "op": meta["op"],
                    "threshold": meta["threshold"],
                    "pass": ok,
                }
            )
    out["guardrails"] = guardrails
    out["skipped"] = skipped
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
