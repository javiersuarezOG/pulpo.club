"""Guard policy matrix (RESILIENCE-AUDIT-PRD R2) — first slice.

The nightly's guards historically *crashed the run* on any violation, which
strands an otherwise-valid catalogue: a guard exits non-zero, the candidate
never promotes, and the site silently goes stale. The fix is to have guards
return a SEVERITY-tagged decision instead, so a *shippable degradation* no
longer hard-fails — only genuine corruption refuses promotion.

Severity vocabulary (PRD §R2):
  block       catastrophic — zero/near-zero inventory, corruption. Refuse to ship.
  warn        shippable degradation — log, alert, ship anyway.
  quarantine  unknown state needing a human.

This slice converts the population-regression guard, the exact case that froze
run 27050642483 (``is_motivated`` 15.3% → 8.1% while 2107 valid listings
existed — a population-MIX shift, not an unusable catalogue). The remaining
guards move into ``automation/guards/`` in later R2 slices; the dataclass +
report writer here are the shared scaffold.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

BLOCK = "block"
WARN = "warn"
QUARANTINE = "quarantine"
SEVERITIES = (BLOCK, WARN, QUARANTINE)


@dataclass
class GuardDecision:
    """One guard's verdict, in the PRD §R2 shape."""

    name: str
    severity: str            # block | warn | quarantine
    decision: str            # mirrors severity
    recoverable: bool
    message: str
    metrics: dict[str, Any] = field(default_factory=dict)
    evidence_uri: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_population_regression(
    regressions: list[str],
    *,
    visible_count: int,
    floor: int,
) -> GuardDecision:
    """Classify a population-rate regression as block vs warn.

    Population-MIX shifts (a derived field's rate dropping) are a *quality
    warning*, not corruption, as long as the catalogue itself is healthy —
    i.e. visible inventory is at or above the count floor. Below the floor the
    drop coincides with a genuine collapse and must block. This is the PRD §R2
    acceptance criterion: "Population percentage shifts no longer hard-fail if
    total visible inventory is above floor; true catastrophic count collapse
    still blocks."

    Caller passes a non-empty ``regressions`` list (the messages from
    ``check_population_regression``); an empty list means there's nothing to
    classify and this should not be called.
    """
    healthy = visible_count >= floor
    severity = WARN if healthy else BLOCK
    summary = "; ".join(regressions[:20])
    message = (
        f"population-rate drop(s) [{len(regressions)}] with "
        f"visible={visible_count} floor={floor}: {summary}"
    )
    return GuardDecision(
        name="population_regression",
        severity=severity,
        decision=severity,
        recoverable=(severity != BLOCK),
        message=message,
        metrics={
            "visible_count": visible_count,
            "floor": floor,
            "regression_count": len(regressions),
            "regressions": regressions[:20],
            "healthy_above_floor": healthy,
        },
    )


def append_guard_report(web_data_dir: Path | str, decision: GuardDecision) -> None:
    """Append a decision to ``web/data/guard_report.json`` (a JSON list).

    Best-effort: guard reporting must never crash the pipeline. The report is
    a diagnostic surface (uploaded with the nightly artifacts); it does not
    gate anything on its own.
    """
    path = Path(web_data_dir) / "guard_report.json"
    try:
        existing: list = []
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                if isinstance(loaded, list):
                    existing = loaded
            except Exception:
                existing = []
        existing.append(decision.to_dict())
        path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"[guard_report] write failed (non-fatal): {e!r}")
