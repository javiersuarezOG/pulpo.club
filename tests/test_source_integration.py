"""Source-integration contract — guards the new-source deployment path.

The `/admin/sources` widget auto-discovers any source that appears in
``web/data/source_health_history.jsonl``, which the nightly populates
from the ``PULPO_SOURCES`` env var declared in
``.github/workflows/pulpo-nightly.yml``. That means a new scraper is
visible in the dashboard the day after it ships — no widget code
change required.

But that auto-integration only works if the surrounding pieces are
wired up. This test fails CI when any source slug in PULPO_SOURCES is
missing one of the four required surfaces:

  1. ``pulpo/scrapers/<source>.py``                       — scraper module
  2. ``tests/scrapers/test_<source>.py``                  — test file
  3. registered in ``pulpo.agents.SOURCES``               — runtime registry
  4. (informational, not blocking) entry in ``_policy.py``  — falls back
     to DEFAULT_POLICY when missing, but the dashboard surfaces this

Adding a new source:
  1. Drop the scraper at ``pulpo/scrapers/<slug>.py`` with the standard
     ``register(SOURCES, "<slug>", _scraper)`` call.
  2. Drop ``tests/scrapers/test_<slug>.py`` covering at minimum the
     offline-fixture path.
  3. (Recommended) Add a ``Policy(...)`` row to ``POLICIES`` in
     ``pulpo/scrapers/_policy.py``. Unset = DEFAULT_POLICY.
  4. Append the slug to ``PULPO_SOURCES`` in the nightly workflow.
  5. Next nightly writes a row to ``source_health_history.jsonl``.
  6. The admin widget at ``/admin/sources`` displays it automatically.

If you skip step 1 or 2, this test fails before the deploy. If you
skip step 3, the policy module logs the fallback. If you skip step 4
the source isn't crawled. If you skip 5/6 they happen automatically.
"""
from __future__ import annotations
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

NIGHTLY_WORKFLOW = REPO / ".github" / "workflows" / "pulpo-nightly.yml"
SCRAPERS_DIR     = REPO / "pulpo" / "scrapers"
TESTS_DIR        = REPO / "tests" / "scrapers"


def _parse_pulpo_sources() -> list[str]:
    """Extract the PULPO_SOURCES value from the nightly workflow YAML.

    Hand-parsed instead of using PyYAML so this test has no extra
    runtime dep. The line shape is stable in the workflow:
        PULPO_SOURCES: "a,b,c,d"
    """
    text = NIGHTLY_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r'PULPO_SOURCES:\s*"([^"]+)"', text)
    if match is None:
        raise AssertionError(
            "PULPO_SOURCES line not found in .github/workflows/pulpo-nightly.yml — "
            "this test parses that line to know which sources should be wired. "
            "If you renamed the env var update _parse_pulpo_sources()."
        )
    return [s.strip() for s in match.group(1).split(",") if s.strip()]


@pytest.fixture(scope="module")
def declared_sources() -> list[str]:
    sources = _parse_pulpo_sources()
    assert sources, "PULPO_SOURCES is empty — nothing for the nightly to crawl"
    return sources


# ── required surfaces ─────────────────────────────────────────────────


def test_every_source_has_scraper_module(declared_sources):
    """Every slug in PULPO_SOURCES must have a matching
    pulpo/scrapers/<slug>.py — otherwise the nightly logs
    'unknown source' and the source is silently dropped."""
    missing = [s for s in declared_sources if not (SCRAPERS_DIR / f"{s}.py").exists()]
    assert not missing, (
        f"PULPO_SOURCES declares {missing} but pulpo/scrapers/<slug>.py is missing. "
        f"Either drop the scraper file or remove the slug from the nightly workflow."
    )


def test_every_source_has_test_file(declared_sources):
    """Every slug in PULPO_SOURCES must have a matching test file under
    tests/scrapers/test_<slug>.py — every scraper's contract is
    pinned with at least the offline-fixture path."""
    missing = [s for s in declared_sources if not (TESTS_DIR / f"test_{s}.py").exists()]
    assert not missing, (
        f"PULPO_SOURCES declares {missing} but tests/scrapers/test_<slug>.py is missing. "
        f"Drop at minimum the offline-fixture smoke before merging."
    )


def test_every_source_registers_in_SOURCES(declared_sources):
    """Importing pulpo.scrapers triggers register() in each module. After
    that, every declared source slug must be a key in pulpo.agents.SOURCES.
    Catches the failure mode where a scraper file exists but the register()
    call is missing or its slug differs from the env-var entry."""
    # Force-import all scraper modules so their register() side effects run.
    for slug in declared_sources:
        try:
            __import__(f"pulpo.scrapers.{slug}")
        except ImportError:
            # The missing-module case is already covered by the previous test;
            # we don't want to mask that signal here.
            pass

    from pulpo.agents import SOURCES  # noqa: WPS433 — late import is intentional
    missing = [s for s in declared_sources if s not in SOURCES]
    assert not missing, (
        f"PULPO_SOURCES declares {missing} but they are not registered in pulpo.agents.SOURCES. "
        f"Confirm each scraper module calls register(SOURCES, '<slug>', _scraper) "
        f"with a slug that matches the env-var entry."
    )


# ── informational (warn but don't block) ──────────────────────────────


def test_policy_entry_exists_for_each_source(declared_sources):
    """Soft check — sources without an explicit Policy entry fall back
    to DEFAULT_POLICY (0.5 rps, default UA pool, auto_repair=True).
    That's a safe default, but it's worth seeing in the test output
    when a source is implicitly inheriting it — high-volume scrapers
    usually want a tuned policy.

    Asserts on the union — failure means *all* sources are missing —
    so the test is a tripwire on the policy file itself disappearing,
    not on individual omissions."""
    from pulpo.scrapers._policy import POLICIES

    explicit = [s for s in declared_sources if s in POLICIES]
    assert explicit, (
        "No declared source has an explicit policy entry in _policy.py — "
        "the file may have been emptied or the import broke. "
        "Sources should each carry an explicit Policy(...) row."
    )
    # Informational warning (test passes either way) — surfaces in -v output.
    implicit = [s for s in declared_sources if s not in POLICIES]
    if implicit:
        print(
            f"\n[source_integration] {implicit} use DEFAULT_POLICY (no explicit "
            f"entry in pulpo/scrapers/_policy.py). That's safe but consider "
            f"adding a tuned Policy(...) row if rate-limit or UA pool matters."
        )


# ── reverse direction ────────────────────────────────────────────────


def test_no_orphan_scraper_modules(declared_sources):
    """A scraper module under pulpo/scrapers/<slug>.py whose slug is NOT
    in PULPO_SOURCES is either WIP (fine) or vestigial (not fine).
    Surfacing this in the test output makes the orphan visible without
    blocking — some scrapers are intentionally parked, some are dead
    code waiting to be deleted."""
    KNOWN_HELPERS = {"_policy", "_runtime", "_type_classifier", "_photo_url_upgrade", "__init__"}
    module_slugs = {
        p.stem for p in SCRAPERS_DIR.glob("*.py")
        if p.stem not in KNOWN_HELPERS and not p.stem.startswith(".")
    }
    declared = set(declared_sources)
    orphans = module_slugs - declared
    if orphans:
        print(
            f"\n[source_integration] orphan scraper modules (file exists, "
            f"slug not in PULPO_SOURCES): {sorted(orphans)} — confirm they're "
            f"parked WIP and not dead code."
        )
