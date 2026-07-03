#!/usr/bin/env python3
"""R6 of docs/RESILIENCE-AUDIT-PRD.md — stranded-inventory alerter.

R1 makes a guard-failed nightly leave a durable candidate bundle at
``web/data/.staging/<run_id>/``. R6 surfaces that bundle to the
operator so the data doesn't sit forgotten in an Actions artifact
while the live site stays stale. Without R6 the candidate is just a
file on disk nobody knows to look at; with R6 the operator gets a
Slack page and a persistent GitHub Issue the moment the bundle exists
but promotion didn't happen.

Trigger condition::

    candidate_visible_count > 0 AND promoted == False

``promoted`` is decided by comparing the bundle's
``last_updated.candidate.json::generated_at`` to the canonical
``web/data/last_updated.json``: a fresher canonical means the
post-guard write path completed, a missing or older canonical means
the candidate is stranded.

Always exits 0 in production — never blocks the deploy step. Slack +
GitHub Issue creation are independent best-effort sends: if Slack
fails, the Issue still goes out so the operator has a permanent
record. ``--dry-run`` prints the alert body without sending anything,
useful for inline calibration on the runner.

Reads the candidate bundle layout R1 writes (see
``automation/candidate_bundle.py``). Does NOT import it directly so
this script can land before R1 merges without a circular dependency
in CI — the bundle path and manifest schema are stable enough that
the duplication is cheap and the independence is valuable.

Usage::

    python3 scripts/check_stranded_inventory.py \\
        --data-dir web/data \\
        --run-id $GITHUB_RUN_ID \\
        --run-url $RUN_URL \\
        --commit-status $COMMIT_STATUS
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


# ── Bundle discovery (mirrors automation/candidate_bundle.py) ──────────


def resolve_run_id(explicit: Optional[str]) -> str:
    """Pick the same run_id R1's writer used.

    Priority: explicit CLI flag > ``GITHUB_RUN_ID`` (the Actions
    runtime ID) > ``PULPO_RUN_ID`` (manual local override) > ``""``.
    When ``run_id`` is empty the script exits 0 — without a run_id we
    cannot locate the bundle, and silently no-op is the right behavior
    (matches the pre-R6 baseline).
    """
    if explicit:
        return explicit
    return os.environ.get("GITHUB_RUN_ID") or os.environ.get("PULPO_RUN_ID") or ""


def staging_dir_for(data_dir: Path, run_id: str) -> Path:
    return data_dir / ".staging" / run_id


# ── Promotion check ────────────────────────────────────────────────────


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def is_promoted(
    *,
    bundle_meta: Optional[dict],
    canonical_meta: Optional[dict],
) -> bool:
    """Promotion happened iff the canonical last_updated.json is at
    least as fresh as the candidate's last_updated.candidate.json.

    ``bundle_meta`` is the parsed ``last_updated.candidate.json``;
    ``canonical_meta`` is the parsed ``web/data/last_updated.json``.
    Returns False when either side is missing — the script's caller
    treats False + visible_count > 0 as the stranded signal.
    """
    if bundle_meta is None:
        # No candidate meta means there's nothing to compare against.
        # Treat as promoted-by-default so the alert doesn't fire on
        # pipelines that haven't migrated to R1 yet.
        return True
    if canonical_meta is None:
        return False
    bundle_ts = bundle_meta.get("generated_at") or bundle_meta.get("ts")
    canonical_ts = canonical_meta.get("generated_at") or canonical_meta.get("ts")
    if not (bundle_ts and canonical_ts):
        # Without timestamps on both sides we cannot make a confident
        # promotion call. Err on stranded (return False) so the operator
        # is alerted to the missing field rather than silently miss the
        # incident.
        return False
    return canonical_ts >= bundle_ts


def detect_stranded(
    data_dir: Path,
    run_id: str,
) -> tuple[bool, Optional[dict]]:
    """Return ``(stranded, manifest)``.

    ``stranded`` is True iff there's a bundle with ``visible_count > 0``
    and the canonical last_updated.json is older than (or missing)
    the candidate's last_updated.candidate.json.
    """
    if not run_id:
        return False, None
    staging = staging_dir_for(data_dir, run_id)
    manifest = _read_json(staging / "bundle_manifest.json")
    if manifest is None:
        # No bundle for this run — either R1 was disabled this run
        # (PULPO_R1_BUNDLE_ENABLED=0) or the pipeline crashed before
        # the bundle write. Either way, R6 has nothing to alert on:
        # there's no stranded data to recover.
        return False, None
    visible = int(manifest.get("visible_count") or 0)
    if visible <= 0:
        return False, manifest
    bundle_meta = _read_json(staging / "last_updated.candidate.json")
    canonical_meta = _read_json(data_dir / "last_updated.json")
    promoted = is_promoted(bundle_meta=bundle_meta, canonical_meta=canonical_meta)
    return (not promoted), manifest


# ── Alert composition ──────────────────────────────────────────────────


def build_alert(
    *,
    run_id: str,
    manifest: dict,
    run_url: Optional[str],
    artifact_hint: Optional[str],
    commit_status: Optional[str],
) -> dict[str, str]:
    """Return ``{title, body}`` for the Slack + Issue payloads.

    Body lists the run_id, visible count, generated_at, file list, the
    recovery command, the commit status (if known), and the run URL.
    The same body is used for Slack and for the GitHub Issue so the
    operator sees the same story regardless of which channel they hit
    first.
    """
    visible = manifest.get("visible_count", 0)
    generated_at = manifest.get("generated_at", "?")
    files = manifest.get("files", []) or []
    files_summary = ", ".join(sorted(f.get("path", "?") for f in files)) or "(empty)"
    title = (
        f"Pulpo nightly: stranded candidate ({visible} listings, run {run_id})"
    )
    lines = [
        "*Pulpo nightly: candidate bundle generated but not promoted.*",
        "",
        f"• run_id: `{run_id}`",
        f"• visible_count: {visible}",
        f"• candidate_generated_at: {generated_at}",
        f"• bundle files: {files_summary}",
    ]
    if commit_status:
        lines.append(f"• commit_status: {commit_status}")
    if artifact_hint:
        lines.append(f"• artifact: {artifact_hint}")
    if run_url:
        lines.append(f"• run: {run_url}")
    lines.extend([
        "",
        "*Recovery:* `python scripts/promote_candidate.py --run-id "
        f"{run_id} --dry-run` to inspect, then drop `--dry-run` to "
        "promote. See `docs/RESILIENCE-AUDIT-PRD.md` § R1/R9.",
    ])
    return {"title": title, "body": "\n".join(lines)}


# ── Slack ──────────────────────────────────────────────────────────────


def post_slack(webhook_url: str, text: str) -> bool:
    """Best-effort Slack POST. Returns True on success, False on any
    failure mode. Never raises."""
    req = urllib.request.Request(
        webhook_url,
        data=json.dumps({"text": text}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        print(f"[stranded-inventory] Slack POST failed: {e}", file=sys.stderr)
        return False


# ── GitHub Issue ───────────────────────────────────────────────────────


def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _gh_run(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def find_or_open_issue(
    *,
    run_id: str,
    title: str,
    body: str,
    label: str = "stranded-inventory",
) -> Optional[str]:
    """Open a GitHub Issue if none exists for this run_id, else return
    the existing one's URL. Dedup key: ``[stranded run=<run_id>]`` in
    the title (the caller already includes it in ``title``).

    Returns the issue URL on success, None when ``gh`` is missing or
    the call fails. Never raises — R6's whole point is that the alert
    is best-effort.
    """
    if not _gh_available():
        print("[stranded-inventory] gh CLI not on PATH — skipping Issue.")
        return None
    needle = f"stranded run={run_id}"
    title_with_key = f"[{needle}] {title}"
    # Search open issues for the run_id needle. Using --search to keep
    # the call cheap even on repos with many issues.
    rc, out, err = _gh_run(
        "issue", "list",
        "--state", "open",
        "--search", needle,
        "--json", "url",
        "--jq", ".[0].url",
    )
    if rc == 0 and out.strip():
        return out.strip()
    if rc != 0:
        print(f"[stranded-inventory] gh issue list failed: {err}", file=sys.stderr)
        # Fall through to attempt creation anyway — better to risk a
        # duplicate than silently miss the alert.
    create_args = [
        "issue", "create",
        "--title", title_with_key,
        "--body", body,
    ]
    if label:
        create_args += ["--label", label]
    rc, out, err = _gh_run(*create_args)
    if rc == 0 and out.strip():
        # `gh issue create` prints the URL on success.
        return out.strip().splitlines()[-1].strip()
    print(f"[stranded-inventory] gh issue create failed: {err}", file=sys.stderr)
    return None


# ── Entry point ────────────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="R6 — alert when a candidate bundle was generated but not promoted.",
    )
    parser.add_argument(
        "--data-dir",
        default="web/data",
        help="Directory where ranked.json and .staging/ live.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Override the run_id (defaults to GITHUB_RUN_ID / PULPO_RUN_ID).",
    )
    parser.add_argument(
        "--run-url",
        default=None,
        help="GitHub Actions run URL embedded in the alert body.",
    )
    parser.add_argument(
        "--artifact-hint",
        default=None,
        help="Human-readable hint for where the artifact lives (e.g. "
             "'candidate_bundle_<run_id> on the Actions run page').",
    )
    parser.add_argument(
        "--commit-status",
        default=None,
        help="Optional commit status to include in the alert "
             "(e.g. 'skipped due to guard failure').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the alert body but do not POST or open Issues.",
    )
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    run_id = resolve_run_id(args.run_id)
    if not run_id:
        print("[stranded-inventory] no run_id available — exiting 0.")
        return 0

    stranded, manifest = detect_stranded(data_dir, run_id)
    if not stranded or manifest is None:
        print(f"[stranded-inventory] OK — no stranded candidate (run_id={run_id}).")
        return 0

    alert = build_alert(
        run_id=run_id,
        manifest=manifest,
        run_url=args.run_url,
        artifact_hint=args.artifact_hint,
        commit_status=args.commit_status,
    )
    print(alert["body"])

    if args.dry_run:
        print("[stranded-inventory] --dry-run: not posting Slack or opening Issue.")
        return 0

    # Slack + GitHub are INDEPENDENT sends. The PRD requires that if
    # Slack fails the Issue still exists (and vice versa). We don't
    # short-circuit on either failure.
    webhook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if webhook:
        post_slack(webhook, alert["body"])
    else:
        print("[stranded-inventory] SLACK_WEBHOOK_URL unset — skipping Slack.")

    issue_url = find_or_open_issue(
        run_id=run_id,
        title=alert["title"],
        body=alert["body"],
    )
    if issue_url:
        print(f"[stranded-inventory] tracked at {issue_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
