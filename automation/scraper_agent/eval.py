"""The fitness function — Pulpo's ``val_bpb`` analogue.

``evaluate_scraper`` runs a single source through the existing Scraper Lab
funnel (``automation.scraper_lab.lab_run``) and scores the result with the
existing PRD acceptance gate (``automation.field_audit.acceptance_check``),
collapsing both into one :class:`EvalReport` an agent loop can compare across
iterations.

Two design choices make this loop-friendly:

1. **A continuous ``fitness`` scalar, not just pass/fail.** ``acceptance_check``
   answers a binary "does this source clear 85% on every hard gate?". An agent
   iterating below that bar needs a *gradient* — is 60% -> 72% progress? So
   ``fitness`` blends the worst hard-gate ratio (the thing that must reach the
   threshold) with a bounded coverage bonus (more usable listings is better,
   with diminishing returns). Higher is always better; the keep/discard loop
   keeps the higher-fitness candidate.

2. **A ``live`` switch that is honest per use-case.** Onboarding bootstraps
   with one ``live=True`` fetch (a brand-new source has no fixture, so the
   fetched data is representative by construction) then iterates parsing
   offline against the cached raw HTML. Repair *must* use ``live=True`` every
   eval — a stale calibration fixture would let a broken scraper "pass" against
   HTML the live site no longer serves. The caller owns that decision; this
   module just plumbs it to ``lab_run(offline=not live)``.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from automation.field_audit import (
    ACCEPTANCE_HARD_GATE_THRESHOLD,
    ACCEPTANCE_SAMPLE_SIZE,
    HARD_GATE_FIELDS,
    acceptance_check,
)
from automation.scraper_lab import lab_run

# A scraper that parses a couple of listings perfectly is not yet a viable
# source. The harness primitive uses a permissive floor of 1 so it can score
# *any* signal; onboarding callers should pass a higher ``min_ranked`` (the
# product's min-shelf-listings bar is 10) before declaring a source shippable.
DEFAULT_MIN_RANKED = 1

# Weight of the coverage bonus relative to the gate ratio. The gate ratio lives
# in [0, 1]; the coverage bonus is bounded to [0, COVERAGE_BONUS_MAX) so a
# source can never "buy" a passing-looking fitness purely on volume — the gate
# ratio always dominates.
COVERAGE_BONUS_MAX = 0.1


@dataclass
class EvalReport:
    """One scored run of a single scraper. ``fitness`` is the loop's compare key."""

    slug: str
    ok: bool                                   # did the fetch/funnel run at all
    passed: bool                               # cleared the acceptance gate + min_ranked
    fitness: float                             # continuous, higher is better
    hard_gate_pct: dict[str, float]            # per HARD_GATE_FIELDS ratio
    ranked_count: int
    raw_count: int
    normalized_count: int
    validation: dict[str, int]
    failures: dict[str, int]                   # per-reason drop counts from the funnel
    duration_s: float
    live: bool
    error: Optional[str] = None
    write_dir: Optional[str] = None

    def to_json(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        gates = " ".join(
            f"{g}={int(self.hard_gate_pct.get(g, 0.0) * 100)}%" for g in HARD_GATE_FIELDS
        )
        verdict = "PASS" if self.passed else ("ERR" if not self.ok else "below-gate")
        return (
            f"{self.slug} [{verdict}] fitness={self.fitness:.3f} "
            f"ranked={self.ranked_count} {gates} ({self.duration_s:.2f}s)"
        )


def _fitness(hard_gate_pct: dict[str, float], ranked_count: int, ok: bool) -> float:
    """Collapse gate coverage + listing volume into one higher-is-better scalar.

    - ``0.0`` when the funnel failed or produced no shelf-eligible signal.
    - Otherwise the *minimum* hard-gate ratio (the binding constraint for the
      acceptance gate) plus a bounded coverage bonus that approaches
      ``COVERAGE_BONUS_MAX`` as listing count grows. The gate ratio dominates,
      so volume can only break ties between similar-coverage candidates.
    """
    if not ok or not hard_gate_pct:
        return 0.0
    gate_min = min(hard_gate_pct.values())
    coverage_bonus = COVERAGE_BONUS_MAX * (1.0 - 1.0 / (1.0 + max(0, ranked_count)))
    return round(gate_min + coverage_bonus, 4)


def evaluate_scraper(
    slug: str,
    *,
    live: bool,
    limit: int = ACCEPTANCE_SAMPLE_SIZE,
    threshold: float = ACCEPTANCE_HARD_GATE_THRESHOLD,
    sample_size: int = ACCEPTANCE_SAMPLE_SIZE,
    min_ranked: int = DEFAULT_MIN_RANKED,
    write_dir: Optional[Path] = None,
) -> EvalReport:
    """Score one scraper end-to-end. The agent loop's ``evaluate`` callback.

    ``live=False`` runs the funnel against the scraper's offline fixtures
    (deterministic, sub-second); ``live=True`` hits the network. When
    ``write_dir`` is given the funnel's ``ranked.json`` / ``raw.jsonl`` land
    there for reuse — onboarding caches the bootstrap fetch this way so
    subsequent parsing-only iterations can re-score offline.
    """
    own_tmp: Optional[tempfile.TemporaryDirectory] = None
    if write_dir is None:
        own_tmp = tempfile.TemporaryDirectory(prefix=f"scraper-eval-{slug}-")
        wd = Path(own_tmp.name)
    else:
        wd = Path(write_dir)
        wd.mkdir(parents=True, exist_ok=True)

    try:
        result = lab_run(slug, limit=limit, offline=not live, write_dir=wd)

        ranked: list[dict] = []
        ranked_path = wd / "ranked.json"
        if ranked_path.exists():
            try:
                ranked = json.loads(ranked_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                ranked = []

        # acceptance_check is per-source; lab_run is single-source, so at most
        # one report comes back for this slug. Missing report => no shelf-
        # eligible listings => zero coverage.
        _, reports = acceptance_check(
            ranked, threshold=threshold, sample_size=sample_size
        )
        report = next((r for r in reports if r.get("source") == slug), None)
        hard_gate_pct = (
            dict(report["hard_gate_pct"]) if report else {f: 0.0 for f in HARD_GATE_FIELDS}
        )

        passed = bool(
            result.ok
            and report is not None
            and not report["failures"]
            and result.ranked_count >= min_ranked
        )

        return EvalReport(
            slug=slug,
            ok=result.ok,
            passed=passed,
            fitness=_fitness(hard_gate_pct, result.ranked_count, result.ok),
            hard_gate_pct=hard_gate_pct,
            ranked_count=result.ranked_count,
            raw_count=result.raw_count,
            normalized_count=result.normalized_count,
            validation=dict(result.validation),
            failures=dict(result.failures),
            duration_s=result.duration_s,
            live=live,
            error=result.error,
            write_dir=str(wd),
        )
    finally:
        if own_tmp is not None:
            own_tmp.cleanup()
