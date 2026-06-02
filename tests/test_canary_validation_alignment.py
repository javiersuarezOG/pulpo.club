"""Contract test: nightly-workflow data-quality canary thresholds
must stay consistent with automation/validation_bounds.py.

Why this exists
---------------
On 2026-06-01 nightly #26774794593 succeeded through the full
pipeline + 6 earlier canaries (including the narrowed top-10 hero
canary), recovered all 3 broken sources, and produced 956 fresh
listings — then failed at the Data-quality canary on ONE legitimate
listing (a $7,666/m² premium SV beach micro-lot at Jaltepeque). Root
cause was a long-standing config mismatch:

  PR-NR-G: canary PPM ceiling = 5_000  (matched validation FLAG_MAX)
  automation/validation_bounds.PPM_FLAG_MAX = 5_000  (kept + flagged)
  automation/validation_bounds.PPM_DROP_MAX = 10_000 (dropped)

So the validation layer kept + flagged listings in the 5k-10k band,
the canary then hard-failed the workflow on those same listings, and
the data PR froze. PR #618 raised the canary ceiling to match
PPM_DROP_MAX. This test asserts the alignment so the next person who
touches either side surfaces the dependency before it bites a nightly.

Contract
--------
For each numeric canary threshold in pulpo-nightly.yml's
"Data-quality canaries" step, this test asserts:

  - canary upper bound ≥ validation FLAG upper bound
    (canary must NOT fire on listings the validation layer only flags
     — those are kept + warning-tagged; failing the workflow on them
     blocks fresh data for valid input).
  - canary upper bound  ≤ validation DROP upper bound + slack
    (canary should fire roughly when the validation layer drops, as
     a defensive backup for unit-conversion bugs; "slack" allows the
     canary to be looser/wider than DROP — that's safe).

A failure here means EITHER:
  - The canary ceiling moved without updating the corresponding
    validation bound (canary will start blocking legit data again).
  - The validation bound moved without updating the canary (canary's
    safety net no longer aligns with what validation actually drops).

Either way, re-decide which side is correct, update both intentionally,
and bump the assertion. Do not silence by exception.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.validation_bounds import (  # noqa: E402
    AREA_DROP_MAX,
    PPM_DROP_MAX,
    PPM_DROP_MIN,
    PPM_FLAG_MAX,
    PPM_FLAG_MIN,
    PRICE_DROP_MAX,
)

NIGHTLY_YML = REPO / ".github" / "workflows" / "pulpo-nightly.yml"


def _extract_canary_thresholds(yml_text: str) -> dict[str, float]:
    """Parse the inline Python in the 'Data-quality canaries' step and
    extract the numeric thresholds. Returns a dict of named values.

    The regexes target the literal numeric expressions in the workflow
    script — when the script changes shape (e.g. someone factors the
    canary into a separate file), this test will fail with a clear
    "could not extract" message and the maintainer updates both the
    extractor and the contract.
    """
    out: dict[str, float] = {}
    # area > 15_000_000
    m = re.search(r"area is not None and area > ([\d_]+)", yml_text)
    if m:
        out["area_ceiling"] = float(m.group(1).replace("_", ""))
    # price > 50_000_000
    m = re.search(r"price is not None and price > ([\d_]+)", yml_text)
    if m:
        out["price_ceiling"] = float(m.group(1).replace("_", ""))
    # ppm_floor = 0.10 if is_agri else 1.0
    m = re.search(r"ppm_floor = ([\d.]+) if is_agri else ([\d.]+)", yml_text)
    if m:
        out["ppm_floor_agri"] = float(m.group(1))
        out["ppm_floor_nonagri"] = float(m.group(2))
    # ppm > 10_000  (the upper PPM bound — caught both with floor in one line)
    m = re.search(r"ppm < ppm_floor or ppm > ([\d_]+)", yml_text)
    if m:
        out["ppm_ceiling"] = float(m.group(1).replace("_", ""))
    return out


def test_canary_thresholds_extracted_from_workflow():
    """Sanity: the YAML parser still finds every threshold the contract
    below depends on. If this fails the canary script was restructured;
    update _extract_canary_thresholds()."""
    yml = NIGHTLY_YML.read_text()
    thresholds = _extract_canary_thresholds(yml)
    for key in ("area_ceiling", "price_ceiling", "ppm_ceiling",
                "ppm_floor_agri", "ppm_floor_nonagri"):
        assert key in thresholds, (
            f"Could not extract '{key}' from pulpo-nightly.yml's "
            f"data-quality canary step. Did the script change shape?"
        )


def test_canary_ppm_ceiling_matches_validation_drop_max():
    """The bug that froze the 2026-06-01 nightly. PPM canary ceiling
    must equal PPM_DROP_MAX so the canary fires only on listings the
    validation layer would have dropped as structurally broken.

    Loosening canary below DROP_MAX → canary fires on flagged-but-kept
    listings → workflow hard-fails on valid premium properties → data
    PR freezes (the exact 2026-06-01 incident, fixed in PR #618)."""
    yml = NIGHTLY_YML.read_text()
    canary_ceiling = _extract_canary_thresholds(yml)["ppm_ceiling"]
    assert canary_ceiling == PPM_DROP_MAX, (
        f"Drift detected: canary PPM ceiling = {canary_ceiling}, "
        f"validation_bounds.PPM_DROP_MAX = {PPM_DROP_MAX}. "
        f"Decide which side is correct and update both — see "
        f"PR #618 for the original alignment rationale."
    )


def test_canary_area_ceiling_above_validation_drop_max():
    """Area canary is a defensive backup for catastrophic unit-conversion
    bugs (e.g. someone treats ha as m²). It should fire at or above the
    validation DROP threshold — never below FLAG, because validation
    keeps + flags listings between FLAG and DROP and the canary would
    block them."""
    yml = NIGHTLY_YML.read_text()
    canary_ceiling = _extract_canary_thresholds(yml)["area_ceiling"]
    assert canary_ceiling >= AREA_DROP_MAX, (
        f"Drift: canary area ceiling = {canary_ceiling}, "
        f"validation AREA_DROP_MAX = {AREA_DROP_MAX}. Canary is "
        f"now TIGHTER than validation — will block legit data."
    )


def test_canary_price_ceiling_relationship_documented():
    """Today's canary price ceiling ($50M) is tighter than validation
    PRICE_DROP_MAX ($100M) — a $80M listing would be kept-flagged by
    validation but blocked by the canary. Currently a theoretical risk
    (no observed $50M+ listings on the SV market), but the relationship
    should be intentional, not accidental.

    Asserts the current values; if either side moves, this test fails
    and forces the maintainer to re-decide whether the canary should
    track DROP_MAX or stay tighter as a manual-approval gate."""
    yml = NIGHTLY_YML.read_text()
    canary_ceiling = _extract_canary_thresholds(yml)["price_ceiling"]
    assert canary_ceiling == 50_000_000, (
        f"Canary price ceiling changed: {canary_ceiling}. If this is "
        f"intentional, update this assertion + add a comment in the "
        f"workflow explaining why it diverges from PRICE_DROP_MAX = "
        f"{PRICE_DROP_MAX}."
    )
    # And document the validation-side value so a future bump there
    # also surfaces here.
    assert PRICE_DROP_MAX == 100_000_000, (
        f"validation_bounds.PRICE_DROP_MAX changed to {PRICE_DROP_MAX}. "
        f"Decide whether the workflow canary should track the new value."
    )


def test_canary_ppm_floor_nonagri_relationship():
    """Non-agri PPM canary floor (1.0) matches PPM_FLAG_MIN exactly,
    meaning the canary fires on flagged-but-kept low-PPM listings.
    Theoretical risk only (no observed sub-$1/m² SV listings outside
    the agricultural cohort, which has its own looser floor), but
    documented + asserted so any future change is intentional."""
    yml = NIGHTLY_YML.read_text()
    floor_nonagri = _extract_canary_thresholds(yml)["ppm_floor_nonagri"]
    assert floor_nonagri == PPM_FLAG_MIN, (
        f"Canary non-agri PPM floor = {floor_nonagri}, "
        f"PPM_FLAG_MIN = {PPM_FLAG_MIN}. Update both intentionally."
    )
    # Sanity: agri floor should be below DROP_MIN — the canary is a
    # defensive backup for agricultural-scale unit slips.
    floor_agri = _extract_canary_thresholds(yml)["ppm_floor_agri"]
    assert floor_agri < PPM_DROP_MIN, (
        f"Canary agri floor {floor_agri} >= PPM_DROP_MIN {PPM_DROP_MIN}. "
        f"This means the canary fires on listings validation flags; "
        f"intentional?"
    )


def test_log_only_default_enforces_canary():
    """The data-quality canary defaults to enforcing (LOG_ONLY=false).
    A repo variable `DATA_QUALITY_LOG_ONLY=true` can temporarily flip
    it to log-only for incident response — but the workflow default
    must stay 'false' so the canary continues to gate fresh data in
    the normal path."""
    yml = NIGHTLY_YML.read_text()
    # The workflow uses ${{ vars.DATA_QUALITY_LOG_ONLY || 'false' }}
    # for the data-quality step.
    assert "DATA_QUALITY_LOG_ONLY" in yml, (
        "Repo-variable escape hatch removed? Re-introduce so a future "
        "canary trip on legit data can be unblocked without a PR."
    )
    assert "DATA_QUALITY_LOG_ONLY || 'false'" in yml, (
        "Default for DATA_QUALITY_LOG_ONLY must remain 'false' — the "
        "canary should enforce by default, and only be downgraded "
        "explicitly via the repo variable."
    )


def test_ppm_flag_max_documented_value():
    """If validation_bounds.PPM_FLAG_MAX moves, the data-quality canary
    has to be re-evaluated against it. Locking the expected value here
    means any change to validation_bounds surfaces this test."""
    assert PPM_FLAG_MAX == 5_000.0
    assert PPM_DROP_MAX == 10_000.0
