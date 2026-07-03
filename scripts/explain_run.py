#!/usr/bin/env python3
"""Explain a nightly run from its artifacts — read-only operator tool (PRD R9).

Turns the nightly's diagnostic artifacts into one human-readable summary so an
operator can answer "what happened in this run?" without grepping the job log.
Pairs with the observability this series shipped: the `nightly.outcome`
classifier, the `guard_report.json` severity decisions, and per-source health.

Reads whatever is present in a data dir:
  nightly_outcome.json        — the classified verdict (committed / blocked_by_… / …)
  guard_report.json           — guard decisions (severity + message)
  last_updated.json           — counts, timing, errors
  source_health_history.jsonl — latest per-source health row

Usage:
  # On a committed checkout (sees last_updated.json + source_health):
  python3 scripts/explain_run.py
  # On a downloaded diagnostics artifact (also sees nightly_outcome + guard_report):
  gh run download <run-id> -n nightly-diagnostics-<run-id> -D /tmp/diag
  python3 scripts/explain_run.py --data-dir /tmp/diag

Always read-only; exits 0. Never mutates anything.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional


def _load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — missing/garbage artifact is expected
        return None


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        return []
    return rows


def latest_health_by_source(rows: list[dict]) -> dict[str, dict]:
    """Latest crawl-phase health row per source (rows are append-ordered, so the
    last one wins). Skips ``phase=post_validation`` rows, which describe the
    kept-count amendment rather than the crawl outcome."""
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("phase") == "post_validation":
            continue
        src = r.get("source")
        if src:
            latest[src] = r
    return latest


def render(
    outcome: Optional[dict],
    guards: Optional[list],
    meta: Optional[dict],
    health: dict[str, dict],
) -> str:
    """Pure render of the run summary from already-loaded artifacts."""
    L: list[str] = []

    # ── Outcome ──────────────────────────────────────────────────────
    if outcome:
        rid = outcome.get("run_id") or "—"
        url = outcome.get("run_url") or ""
        L.append(f"Run {rid}  {url}".rstrip())
        L.append(
            f"Outcome: {outcome.get('outcome', '?')}  "
            f"(committed={outcome.get('committed') or '—'}, "
            f"deploy={outcome.get('deploy_conclusion') or '—'}, "
            f"job={outcome.get('job_status') or '—'})"
        )
        if outcome.get("failed_step"):
            L.append(f"  blocked at: {outcome['failed_step']}")
    else:
        L.append(
            "Outcome: (no nightly_outcome.json — run predates the classifier or "
            "the diagnostics artifact isn't in --data-dir)"
        )

    # ── Catalogue ────────────────────────────────────────────────────
    if meta:
        L.append("")
        total = meta.get("total_listings")
        dropped = meta.get("dropped")
        line = f"Catalogue: {total if total is not None else '?'} listings"
        if dropped is not None:
            line += f" (dropped {dropped} at validation/purge)"
        L.append(line)
        if meta.get("started_at"):
            gen = f"Generated: {meta['started_at']}"
            if meta.get("duration_seconds") is not None:
                gen += f"  took {meta['duration_seconds']}s"
            if "offline" in meta:
                gen += f"  offline={meta.get('offline')}"
            L.append(gen)

    # ── Guards ───────────────────────────────────────────────────────
    if guards:
        L.append("")
        L.append(f"Guards ({len(guards)}):")
        for g in guards:
            L.append(f"  [{g.get('severity', '?')}] {g.get('name', '?')} — {g.get('message', '')}")

    # ── Sources ──────────────────────────────────────────────────────
    if health:
        greens = [s for s, r in health.items() if r.get("status") == "green"]
        reds = [(s, r) for s, r in health.items() if r.get("status") != "green"]
        L.append("")
        L.append(f"Sources: {len(greens)}/{len(health)} green")
        if reds:
            L.append(
                "  RED: "
                + ", ".join(f"{s}({r.get('error_class') or 'count=0'})" for s, r in reds)
            )

    # ── Errors ───────────────────────────────────────────────────────
    errs = (meta or {}).get("errors") or []
    if errs:
        L.append("")
        L.append(f"Errors ({len(errs)}):")
        for e in errs[:5]:
            L.append(f"  - {str(e)[:200]}")

    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Explain a nightly run from its artifacts.")
    ap.add_argument("--data-dir", type=Path, default=Path("web/data"))
    args = ap.parse_args(argv)
    d = args.data_dir

    outcome = _load_json(d / "nightly_outcome.json")
    guards = _load_json(d / "guard_report.json")
    meta = _load_json(d / "last_updated.json")
    health = latest_health_by_source(_load_jsonl(d / "source_health_history.jsonl"))

    print(
        render(
            outcome if isinstance(outcome, dict) else None,
            guards if isinstance(guards, list) else None,
            meta if isinstance(meta, dict) else None,
            health,
        ),
        end="",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
