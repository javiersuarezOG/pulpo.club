#!/usr/bin/env python3
"""Active-mode scraper repair — Train A of the scraper-agent plan.

The harness-based counterpart to shadow-mode ``scripts/scraper_autorepair.py``.
When a source goes red (selector / URL / pagination drift), this runs the
keep/discard loop to FIX it, then leaves the repaired scraper + a PR body for
review. It never auto-merges.

Honesty rules (from ~/.claude/plans/can-this-improving-the-humble-shamir.md):

- **The repair eval is LIVE every iteration.** A stale calibration fixture
  would let a still-broken scraper "pass" against HTML the site no longer
  serves — the #1 way repair ships a fake fix. ``evaluate_scraper(live=True)``.
- **Recover-to-median gate, not just the generic acceptance gate.** A repair
  only counts if live coverage climbs back to the source's recent historical
  ``kept`` median (× a recovery fraction), so a patch that yields 2 listings
  for a source that used to yield 200 is correctly rejected.
- **WAF / JA3 sources are NOT loop-solvable** and are skipped
  (``policy.auto_repair is False``) — those need a transport change, not an
  LLM patch.

This reuses the LLM / probe / parse / prompt building blocks from
``scraper_onboard`` (the proposer reads the live site the same way) and the
shared harness (``automation.scraper_agent``). The only repair-specific pieces
are the prompt framing, the failure-snapshot context, and the median gate.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from statistics import median
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from automation.scraper_agent import Budget, ProposedEdit, Sandbox, agent_loop  # noqa: E402
from automation.scraper_agent.eval import EvalReport, evaluate_scraper  # noqa: E402
from automation.scraper_agent.loop import LoopContext  # noqa: E402
from pulpo.scrapers._policy import get_policy  # noqa: E402

# Reuse the onboard proposer's LLM/probe/parse/prompt building blocks — the
# repair proposer reads the live site exactly the same way.
import scraper_onboard as onboard  # noqa: E402

HEALTH_PATH = REPO / "web" / "data" / "source_health_history.jsonl"
FAILURES_DIR = REPO / "web" / "data" / "scraper_failures"
# How much of the historical median a repair must recover to count as fixed.
DEFAULT_RECOVER_FRAC = 0.8
# Floor when there's no usable history (a source with no green runs yet).
DEFAULT_FLOOR = 10


# ── recover-to-median target ─────────────────────────────────────────

def recent_kept_median(slug: str, history_path: Path = HEALTH_PATH, *, window: int = 7) -> Optional[int]:
    """Median post-validation ``kept`` count over the source's most recent
    productive runs, or None if there's no history. Rows are append-ordered."""
    keeps: list[int] = []
    if not history_path.exists():
        return None
    for line in history_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("source") == slug and isinstance(row.get("kept"), int) and row["kept"] > 0:
            keeps.append(row["kept"])
    keeps = keeps[-window:]
    if not keeps:
        return None
    return int(median(keeps))


def repair_target_min_ranked(
    slug: str,
    history_path: Path = HEALTH_PATH,
    *,
    floor: int = DEFAULT_FLOOR,
    recover_frac: float = DEFAULT_RECOVER_FRAC,
) -> int:
    """The min ranked count a repair must reach: the historical median scaled
    by ``recover_frac``, never below ``floor``."""
    med = recent_kept_median(slug, history_path)
    if med is None:
        return floor
    return max(floor, int(med * recover_frac))


# ── failure snapshot ─────────────────────────────────────────────────

def load_failure_snapshot(slug: str, failures_dir: Path = FAILURES_DIR) -> Optional[dict]:
    """Newest per-source failure snapshot (response body / headers / traceback),
    or None. Filenames sort lexically by ISO timestamp, so reverse = newest."""
    if not failures_dir.exists():
        return None
    for path in sorted(failures_dir.glob(f"{slug}_*.json"), key=lambda p: p.name, reverse=True):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return None


# ── source URL ───────────────────────────────────────────────────────

def derive_source_url(slug: str) -> Optional[str]:
    """Best-effort: read the broken scraper's own CONFIG.list_url so the
    operator usually doesn't have to pass --url. Returns None if the module
    can't be imported or has no CONFIG (then --url is required)."""
    try:
        from pulpo.agents import SOURCES
        importlib.import_module(f"pulpo.scrapers.{slug}")
        inst = SOURCES.get(slug)
        cfg = getattr(inst, "CONFIG", None)
        url = getattr(cfg, "list_url", None) or getattr(cfg, "base_url", None)
        return url or None
    except Exception:  # noqa: BLE001 — a broken module is exactly the repair case
        return None


# ── repair prompt + proposer ─────────────────────────────────────────

def build_repair_prompt(ctx: LoopContext, *, source_url: str,
                        failure_snapshot: Optional[dict], probe: Optional[dict]) -> str:
    """Repair framing wrapped around the shared onboard prompt: the current
    (broken) scraper is ctx.current_source, the probe is the live site NOW, and
    the failure snapshot is the error that's happening."""
    snap = (json.dumps(failure_snapshot, indent=2, ensure_ascii=False)[:3000]
            if failure_snapshot else "<no failure snapshot on disk>")
    header = (
        f"This scraper for '{ctx.slug}' WAS WORKING and recently broke — it now "
        f"yields too few or zero listings. The site most likely changed its HTML "
        f"structure, detail-URL scheme, or pagination. Diagnose what DRIFTED by "
        f"comparing the current (broken) module below against how the live site "
        f"looks NOW (shown further down), and produce a fixed module.\n\n"
        f"Most recent failure snapshot:\n```json\n{snap}\n```\n\n"
        f"────────────────────────────────────────────────────────────\n"
    )
    base = onboard.build_onboard_prompt(ctx, source_url=source_url, probe=probe)
    return header + base


def make_repair_propose(source_url: str, *, provider: str = onboard.DEFAULT_PROVIDER,
                        model: Optional[str] = None, failure_snapshot: Optional[dict] = None):
    """Repair ``propose`` callable. Probes the live site once, reuses it across
    iterations (the 'prepare once' split)."""
    model = model or onboard.PROVIDERS[provider]["default_model"]
    cache: dict = {}

    def propose(ctx: LoopContext) -> Optional[ProposedEdit]:
        if "probe" not in cache:
            cache["probe"] = onboard._probe_site(source_url)
        prompt = build_repair_prompt(ctx, source_url=source_url,
                                     failure_snapshot=failure_snapshot, probe=cache["probe"])
        text, usage = onboard._call_model(prompt, provider=provider, model=model)
        parsed = onboard.parse_proposal(text)
        if parsed is None:
            return None
        module, rationale = parsed
        return ProposedEdit(content=module, rationale=rationale, model=model, usage=usage)

    return propose


# ── PR body ──────────────────────────────────────────────────────────

def render_repair_pr_body(slug: str, source_url: str, result, target: int) -> str:
    best = result.best
    gates = "\n".join(f"  - `{k}`: {int(v * 100)}%" for k, v in best.hard_gate_pct.items())
    return f"""## Repair: `{slug}` ({source_url})

Auto-repaired by the scraper-agent loop ({result.iterations} iteration(s),
stop_reason=`{result.stop_reason}`, {result.budget_summary}).

**Live coverage recovered to ≥ historical median** (target ≥ {target} ranked):
- ranked (live): {best.ranked_count}
- hard gates (≥85% required):
{gates}
- validation: {best.validation}

### Reviewer checklist
- [ ] Eyeball 3 records for correctness (not just count > 0).
- [ ] Diff vs the pre-break version — is the fix minimal and sensible?
- [ ] `PULPO_OFFLINE=1 pytest tests/scrapers/test_{slug}.py` if a fixture test exists.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
"""


# ── orchestration ────────────────────────────────────────────────────

def run_repair(
    slug: str,
    source_url: str,
    *,
    propose,
    target_min_ranked: int,
    max_iters: int,
    budget_usd: float,
    live: bool = True,
    limit: int = 30,
    trace_dir: Optional[Path] = None,
    log=print,
):
    """Run the repair loop. ``live`` is True in production (the honesty rule);
    tests pass False to exercise the wiring against offline fixtures.
    Returns ``(LoopResult, pr_body_or_None)``."""
    def evaluate() -> EvalReport:
        return evaluate_scraper(slug, live=live, limit=limit, min_ranked=target_min_ranked)

    with Sandbox(REPO, slug) as sb:
        result = agent_loop(
            slug, propose=propose, evaluate=evaluate, sandbox=sb,
            budget=Budget(limit_usd=budget_usd), kind="repair",
            max_iters=max_iters, log=log, trace_dir=trace_dir,
        )
        pr_body = None
        if result.passed:
            sb.commit()
            pr_body = render_repair_pr_body(slug, source_url, result, target_min_ranked)
            (REPO / f"PR_BODY_repair_{slug}.md").write_text(pr_body, encoding="utf-8")
    return result, pr_body


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Active-mode scraper repair (harness-based).")
    p.add_argument("--slug", required=True, help="Red source slug to repair.")
    p.add_argument("--url", default=None,
                   help="Catalog URL (defaults to the scraper's own CONFIG.list_url).")
    p.add_argument("--max-iters", type=int, default=6)
    p.add_argument("--budget", type=float, default=2.0, help="Per-run USD ceiling.")
    p.add_argument("--provider", choices=sorted(onboard.PROVIDERS), default=onboard.DEFAULT_PROVIDER)
    p.add_argument("--model", default=None)
    p.add_argument("--limit", type=int, default=30, help="Listings to fetch per eval.")
    p.add_argument("--recover-frac", type=float, default=DEFAULT_RECOVER_FRAC,
                   help="Fraction of the historical kept-median a repair must reach.")
    p.add_argument("--trace-dir", default=None)
    p.add_argument("--dry-run", action="store_true",
                   help="Print the first-iteration repair prompt and exit. No API call, no edits.")
    args = p.parse_args(argv)

    if not re.fullmatch(r"[a-z0-9_]+", args.slug):
        print(f"error: --slug must be [a-z0-9_]+, got {args.slug!r}")
        return 2

    # WAF / IP / auth-class sources can't be fixed by an LLM patch.
    if not get_policy(args.slug).auto_repair:
        print(f"skip: {args.slug} is policy.auto_repair=False (WAF/IP/auth class — "
              f"needs a transport change, not an LLM patch).")
        return 0

    source_url = args.url or derive_source_url(args.slug)
    if not source_url:
        print(f"error: could not derive a catalog URL for {args.slug}; pass --url.")
        return 2

    snapshot = load_failure_snapshot(args.slug)
    target = repair_target_min_ranked(args.slug, recover_frac=args.recover_frac)

    if args.dry_run:
        ctx = LoopContext(slug=args.slug, kind="repair", iteration=1,
                          current_source=(REPO / "pulpo" / "scrapers" / f"{args.slug}.py").read_text(encoding="utf-8")
                          if (REPO / "pulpo" / "scrapers" / f"{args.slug}.py").exists() else None,
                          best=evaluate_scraper(args.slug, live=False),
                          last=evaluate_scraper(args.slug, live=False), history=[])
        print(f"# repair target: recover to >= {target} ranked (live)\n")
        print(build_repair_prompt(ctx, source_url=source_url, failure_snapshot=snapshot, probe=None))
        return 0

    key_env = onboard.PROVIDERS[args.provider]["key_env"]
    if not os.environ.get(key_env):
        print(f"error: {key_env} unset for --provider {args.provider} (use --dry-run to preview).")
        return 2

    trace_dir = Path(args.trace_dir) if args.trace_dir else (
        Path(tempfile.gettempdir()) / "scraper_agent_repair" / args.slug)
    print(f"repairing {args.slug}: recover to >= {target} ranked (live), budget ${args.budget}")
    propose = make_repair_propose(source_url, provider=args.provider, model=args.model,
                                  failure_snapshot=snapshot)
    result, _ = run_repair(
        args.slug, source_url, propose=propose, target_min_ranked=target,
        max_iters=args.max_iters, budget_usd=args.budget, live=True, limit=args.limit,
        trace_dir=trace_dir,
    )
    print("\n" + result.summary())
    print(f"   trace: {trace_dir}")
    if result.passed:
        print(f"\n✅ repaired pulpo/scrapers/{args.slug}.py — review & PR "
              f"(PR_BODY_repair_{args.slug}.md). NOT auto-merged.")
        return 0
    print(f"\n❌ repair did not recover coverage — nothing committed. "
          f"Diagnose: {trace_dir}/best-scraper.py + iter-NN.json")
    return 1


if __name__ == "__main__":
    sys.exit(main())
