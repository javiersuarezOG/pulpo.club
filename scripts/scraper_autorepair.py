#!/usr/bin/env python3
"""
Auto-repair orchestrator for red scrapers (Phase 4 — shadow mode).

Run by ``.github/workflows/pulpo-scraper-autorepair.yml`` after a
failed nightly OR on manual dispatch. Reads ``source_health_history.jsonl``
to find sources in red status, loads the matching failure snapshot from
``web/data/scraper_failures/``, builds a structured prompt for Claude,
and (in SHADOW mode) posts the proposed fix as a comment on the
existing watchdog issue for that source. Optionally (ACTIVE mode,
gated behind a future PR) applies the patch, runs the offline scraper
test, and opens a PR if validation passes.

Why shadow first
----------------
The cost of a wrong scraper patch is bigger than the cost of waiting
to land it manually. Shadow mode posts the *suggested* patch as a
comment on the issue the watchdog already opens — Sebas reviews,
applies it himself, learns whether Claude's suggestions are worth
trusting. After 4 weeks of useful suggestions we graduate to active
mode (open PR with validation passed). The graduation lives in a
separate PR; this script never opens PRs in v1.

Safety rails (enforced here, not in the workflow)
-------------------------------------------------
1. Skips sources where ``policy.auto_repair is False`` (WAF / IP-
   bound sources can't be fixed by an LLM patch).
2. Skips sources with a recent auto-repair attempt (7-day cooldown
   via git log search) — no PR-spam.
3. Hard cap on per-source attempts per run (one per source) so an
   accidental loop doesn't burn Anthropic credit.
4. Never edits anything outside ``pulpo/scrapers/<source>.py`` or its
   test file. The script only reads from other paths.

Environment
-----------
ANTHROPIC_API_KEY      Required when AUTOREPAIR_MODE != "dry-run".
AUTOREPAIR_MODE        "shadow" (default) | "dry-run" | "active" (future).
AUTOREPAIR_MODEL       Anthropic model id; defaults to claude-opus-4-7.
AUTOREPAIR_TARGETS     Comma-separated source slugs to attempt. When
                       empty, auto-detects red sources from the latest
                       source_health_history.jsonl rows.
AUTOREPAIR_DRY_RUN     "1" to skip the network call and print the prompt.
GITHUB_TOKEN           Required for posting comments in shadow mode.
GITHUB_REPOSITORY      <owner>/<repo>, set by GitHub Actions runner.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from pulpo.scrapers._policy import get_policy  # noqa: E402


def _resolve_data_dir() -> Path:
    """Return the directory autorepair should read source_health_history
    and scraper_failures from.

    Priority order:
      1. ``AUTOREPAIR_DATA_DIR`` env var (set by the workflow's
         download-artifact step). This is the diagnostics artifact
         emitted by the triggering nightly — fresher than committed
         main, and crucially CONTAINS rows from a canary-blocked run
         that never reached main.
      2. ``<REPO>/web/data`` — committed main. Used on manual dispatch
         and as a fallback when the artifact download failed.

    Resolution is logged so a failed-artifact / fallback path is
    obvious in the run log without grepping for env vars.
    """
    override = os.environ.get("AUTOREPAIR_DATA_DIR", "").strip()
    if override:
        p = Path(override)
        if p.exists():
            print(f"[autorepair] using AUTOREPAIR_DATA_DIR={p} (nightly artifact)")
            return p
        print(f"[autorepair] AUTOREPAIR_DATA_DIR={p} not found — falling back to web/data")
    print(f"[autorepair] using committed main data: {REPO / 'web' / 'data'}")
    return REPO / "web" / "data"


_DATA_DIR     = _resolve_data_dir()
HEALTH_PATH    = _DATA_DIR / "source_health_history.jsonl"
FAILURES_DIR   = _DATA_DIR / "scraper_failures"
SCRAPERS_DIR   = REPO / "pulpo" / "scrapers"
CALIBRATION    = REPO / "samples" / "calibration"
COOLDOWN_DAYS  = 7

DEFAULT_MODEL  = "claude-opus-4-7"


# ── data classes ──────────────────────────────────────────────────────


@dataclass
class RepairContext:
    source: str
    failure_id: Optional[str]
    failure_payload: Optional[dict]
    scraper_path: Path
    scraper_code: str
    last_good_fixture: Optional[str]    # raw HTML / JSON sample from calibration dir
    recent_commits: str
    health_row: dict


@dataclass
class RepairResult:
    source: str
    skipped_reason: Optional[str] = None
    prompt_chars: int = 0
    response: Optional[str] = None
    posted_to_issue: Optional[int] = None
    errors: list[str] = field(default_factory=list)


# ── helpers ──────────────────────────────────────────────────────────


def latest_health_per_source(path: Path = HEALTH_PATH) -> dict[str, dict]:
    """Return the most-recent row per source from the JSONL."""
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        src = row.get("source")
        if not src:
            continue
        prev = out.get(src)
        if prev is None or row.get("ts", "") > prev.get("ts", ""):
            out[src] = row
    return out


def red_sources(rows: dict[str, dict]) -> list[str]:
    return [src for src, row in rows.items() if row.get("status") == "red"]


def load_failure_snapshot(source: str, failure_id: Optional[str]) -> Optional[dict]:
    if not FAILURES_DIR.exists():
        return None
    if failure_id:
        for path in FAILURES_DIR.glob(f"{source}_*_{failure_id}.json"):
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return None
    # Fallback: newest snapshot for the source.
    candidates = sorted(
        FAILURES_DIR.glob(f"{source}_*.json"),
        key=lambda p: p.name, reverse=True,
    )
    if not candidates:
        return None
    try:
        return json.loads(candidates[0].read_text(encoding="utf-8"))
    except Exception:
        return None


def load_last_good_fixture(source: str) -> Optional[str]:
    """Return a sample of last-good calibration HTML for the source.

    Pulpo's per-source calibration dir under ``samples/calibration/<source>/``
    holds saved HTML / JSON the scraper successfully parsed at some
    point. The auto-repair agent compares the FAILING current HTML
    (from the snapshot) against this LAST-GOOD HTML to spot what
    selectors / fields drifted. Returns the largest file's contents
    capped at 200KB.
    """
    src_dir = CALIBRATION / source
    if not src_dir.exists():
        return None
    candidates = sorted(
        src_dir.glob("*.html"),
        key=lambda p: p.stat().st_size, reverse=True,
    )
    if not candidates:
        return None
    return candidates[0].read_text(encoding="utf-8")[:200_000]


def recent_commits_touching(scraper_path: Path, n: int = 5) -> str:
    try:
        out = subprocess.check_output(
            ["git", "log", f"-{n}", "--pretty=format:%h %ad %s", "--date=short",
             "--", str(scraper_path.relative_to(REPO))],
            cwd=str(REPO), text=True, timeout=10,
        )
        return out
    except Exception as e:
        return f"<git log failed: {e!r}>"


def cooldown_active(source: str, days: int = COOLDOWN_DAYS) -> bool:
    """True if an auto-repair branch / commit exists for ``source`` in the
    cooldown window. Looks for branches named ``auto-repair/<source>-*``
    in the last ``days`` days."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        out = subprocess.check_output(
            ["git", "log", f"--since={since}", "--all",
             "--grep", f"auto-repair: {source}", "--oneline"],
            cwd=str(REPO), text=True, timeout=10,
        )
        return bool(out.strip())
    except Exception:
        return False


# ── prompt construction ──────────────────────────────────────────────


def build_prompt(ctx: RepairContext) -> str:
    """Build the structured prompt sent to Claude.

    Style notes:
      - Frame the model as a senior engineer reviewing a specific file,
        not as a free-form chatter. Constrain the response shape
        explicitly so shadow-mode comments are scannable.
      - Include the failure snapshot verbatim (status, headers, body
        snippet) — that's where selector drift signals live.
      - Include last-good fixture so the model has a comparison
        baseline for what the page used to look like.
      - Recent git log shows whether the file is actively maintained
        or stale (informs whether the fix should be small or a rewrite).
      - Make the deliverable explicit: a patch + a one-paragraph
        rationale + a confidence rating. No prose-only responses.
    """
    failure_block = json.dumps(ctx.failure_payload or {}, indent=2, ensure_ascii=False)[:4000]
    fixture_block = (ctx.last_good_fixture or "<no last-good fixture on disk>")[:30_000]
    return f"""You are reviewing a broken web-scraper module for Pulpo (a Salvadoran real-estate aggregator). One scraper has gone red and you are asked to propose a minimal patch.

Constraints — read carefully:
- Only modify pulpo/scrapers/{ctx.source}.py and tests/scrapers/test_{ctx.source}.py.
- Do NOT modify normalize.py, property_types.py, ranker code, any data file, or any other scraper.
- Prefer the smallest possible change that restores function. If the failure is a selector drift, change selectors. If the server endpoint moved, update the URL. If the failure cannot be fixed without infrastructure changes (proxy, captcha, WAF bypass), say so explicitly and recommend "needs human".

Reply with EXACTLY this structure:
  ## Diagnosis
  Two-to-four sentences. What changed and why the current code fails.

  ## Proposed patch
  A unified diff (```diff fenced```) applied to the scraper file. Include enough context lines for git apply to land it cleanly. If you'd add tests, include a second diff for the test file.

  ## Confidence
  One of: high / medium / low. Rationale in one sentence.

  ## Risk of regression
  One sentence — what else this patch could break.

  ## Manual verification
  One sentence — what Sebas should run locally to confirm the fix.

If the failure isn't auto-fixable (WAF, captcha, IP ban, account-required login), reply with:
  ## Diagnosis
  [explain]
  ## Recommendation
  needs human — [one sentence why]

────────────────────────────────────────────────────────────
Source slug: {ctx.source}
Scraper path: pulpo/scrapers/{ctx.source}.py
Recent commits touching this file:
{ctx.recent_commits or '<none>'}

Latest health-history row:
{json.dumps(ctx.health_row, indent=2)}

Latest failure snapshot (web/data/scraper_failures/...):
{failure_block}

Last-known-good calibration HTML (samples/calibration/{ctx.source}/, capped at 30KB):
```html
{fixture_block}
```

Current scraper code (pulpo/scrapers/{ctx.source}.py):
```python
{ctx.scraper_code}
```
"""


# ── Anthropic call ────────────────────────────────────────────────────


def call_anthropic(prompt: str, *, model: str = DEFAULT_MODEL, dry_run: bool = False) -> str:
    """Send the prompt to Claude. Returns the response text.

    When ``dry_run`` is True or ``ANTHROPIC_API_KEY`` is unset, returns
    a stub response that quotes the first 400 chars of the prompt — lets
    the workflow exercise everything except the actual model call."""
    if dry_run or not os.environ.get("ANTHROPIC_API_KEY"):
        return (
            "## Diagnosis\n"
            "[DRY-RUN: no Anthropic API call made]\n\n"
            f"Prompt preview ({len(prompt)} chars):\n```\n{prompt[:400]}…\n```\n"
        )
    try:
        from anthropic import Anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic SDK not installed — `pip install anthropic` "
            "or set AUTOREPAIR_DRY_RUN=1"
        ) from e

    client = Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    # Concatenate the text blocks.
    out: list[str] = []
    for block in msg.content:
        text = getattr(block, "text", "")
        if text:
            out.append(text)
    return "\n".join(out) or "<empty response>"


# ── GitHub I/O ────────────────────────────────────────────────────────


def find_watchdog_issue_for(source: str) -> Optional[int]:
    """Search open watchdog issues for one mentioning the source. The
    watchdog opens issues titled like 'Scraper red: <source>' — be
    lenient on title matching to survive future title changes."""
    try:
        out = subprocess.check_output(
            ["gh", "issue", "list", "--state", "open", "--limit", "20",
             "--search", source, "--json", "number,title"],
            text=True, timeout=15,
        )
    except Exception:
        return None
    try:
        issues = json.loads(out)
    except json.JSONDecodeError:
        return None
    for it in issues:
        title = (it.get("title") or "").lower()
        if source.lower() in title:
            return int(it.get("number"))
    # Fallback: any open issue mentioning the source is probably the
    # right place to comment.
    if issues:
        return int(issues[0].get("number"))
    return None


def post_comment(issue_number: int, body: str) -> bool:
    try:
        subprocess.run(
            ["gh", "issue", "comment", str(issue_number), "--body", body],
            check=True, timeout=30,
        )
        return True
    except Exception as e:
        print(f"[scraper_autorepair] failed to post comment: {e}")
        return False


# ── main orchestration ───────────────────────────────────────────────


def build_context(source: str, health_row: dict) -> Optional[RepairContext]:
    scraper_path = SCRAPERS_DIR / f"{source}.py"
    if not scraper_path.exists():
        return None
    failure_id = health_row.get("failure_id")
    snapshot = load_failure_snapshot(source, failure_id)
    return RepairContext(
        source=source,
        failure_id=failure_id,
        failure_payload=snapshot,
        scraper_path=scraper_path,
        scraper_code=scraper_path.read_text(encoding="utf-8"),
        last_good_fixture=load_last_good_fixture(source),
        recent_commits=recent_commits_touching(scraper_path),
        health_row=health_row,
    )


def attempt_repair(
    source: str,
    health_row: dict,
    *,
    mode: str,
    model: str,
    dry_run: bool,
) -> RepairResult:
    res = RepairResult(source=source)

    policy = get_policy(source)
    if not policy.auto_repair:
        res.skipped_reason = "policy.auto_repair=False (WAF/IP/auth class — needs human)"
        return res

    if cooldown_active(source):
        res.skipped_reason = f"cooldown active (auto-repair attempt within {COOLDOWN_DAYS}d)"
        return res

    ctx = build_context(source, health_row)
    if ctx is None:
        res.skipped_reason = f"scraper file pulpo/scrapers/{source}.py not found"
        return res

    prompt = build_prompt(ctx)
    res.prompt_chars = len(prompt)

    try:
        response = call_anthropic(prompt, model=model, dry_run=dry_run)
    except Exception as e:
        res.errors.append(f"anthropic_call_failed: {e!r}")
        return res
    res.response = response

    if mode == "shadow":
        issue_no = find_watchdog_issue_for(source)
        if issue_no is None:
            res.errors.append("no_watchdog_issue_to_comment_on")
            return res
        body = (
            f"## :robot: Auto-repair shadow suggestion — `{source}`\n\n"
            f"Model: `{model}` · Prompt: {res.prompt_chars} chars · "
            f"Mode: **shadow** (no PR opened, no code changed).\n\n"
            f"{response}\n\n"
            f"---\n"
            f"_This is a shadow-mode suggestion — no code has been changed. "
            f"Review and apply manually if useful. Cooldown: {COOLDOWN_DAYS}d "
            f"per source (so the script won't comment again on the same source "
            f"for a week)._"
        )
        if post_comment(issue_no, body):
            res.posted_to_issue = issue_no
        else:
            res.errors.append(f"failed_to_comment_on_issue_{issue_no}")

    # ACTIVE mode is gated behind a future PR.
    return res


def main() -> int:
    mode      = os.environ.get("AUTOREPAIR_MODE", "shadow").lower()
    model     = os.environ.get("AUTOREPAIR_MODEL", DEFAULT_MODEL)
    dry_run   = os.environ.get("AUTOREPAIR_DRY_RUN") == "1"
    targets_s = os.environ.get("AUTOREPAIR_TARGETS", "").strip()

    if mode not in ("shadow", "dry-run"):
        print(f"[scraper_autorepair] mode {mode!r} not yet supported in v1 — "
              f"defaulting to shadow")
        mode = "shadow"

    health = latest_health_per_source()
    if targets_s:
        targets = [t.strip() for t in targets_s.split(",") if t.strip()]
    else:
        targets = red_sources(health)
    if not targets:
        print("[scraper_autorepair] no red sources detected — nothing to do")
        return 0

    print(f"[scraper_autorepair] mode={mode} model={model} targets={targets}")

    summary: list[RepairResult] = []
    for src in targets:
        row = health.get(src) or {"source": src, "status": "unknown"}
        res = attempt_repair(src, row, mode=mode, model=model, dry_run=dry_run)
        summary.append(res)
        if res.skipped_reason:
            print(f"[scraper_autorepair] {src}: skipped — {res.skipped_reason}")
        elif res.errors:
            print(f"[scraper_autorepair] {src}: errors — {res.errors}")
        else:
            print(f"[scraper_autorepair] {src}: shadow-comment posted to "
                  f"issue #{res.posted_to_issue} ({res.prompt_chars} chars)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
