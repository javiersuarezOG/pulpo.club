"""Source-integration contract — guards the new-source onboarding chain.

How a new scraper is wired in (the goal of this test)
-----------------------------------------------------
1. Drop the scraper at ``pulpo/scrapers/<slug>.py`` with the standard
   ``register(SOURCES, "<slug>", _scraper)`` call.
2. Drop ``tests/scrapers/test_<slug>.py`` covering at minimum the
   offline-fixture path.
3. (optional) Add a ``Policy(...)`` row to ``POLICIES`` in
   ``pulpo/scrapers/_policy.py``. When omitted, the runtime uses
   ``DEFAULT_POLICY`` (0.5 rps, default UA pool, auto_repair=True).

That's the whole onboarding. ``pulpo/scrapers/__init__.py`` autodiscovers
every non-underscore sibling module so the scraper is auto-imported and
auto-registered. ``automation/run.py`` falls back to ``REGISTRY.keys()``
when ``PULPO_SOURCES`` is unset, so the nightly picks up the new source
without a workflow-YAML edit. The ``/admin/sources`` widget displays it
after its first nightly row lands in ``source_health_history.jsonl``.

What this test catches
----------------------
- A scraper file under ``pulpo/scrapers/`` that errors on import
  (syntax error, broken dep, bad refactor) — would silently drop the
  source from the registry, hiding it from the nightly + dashboard.
- A scraper module that doesn't call ``register(SOURCES, ...)`` — same
  effect: file exists, source absent.
- A registered source with no matching test file — every scraper's
  contract is pinned with at least the offline-fixture smoke.
- Informational: sources implicitly using ``DEFAULT_POLICY`` (printed
  to the test log so a future tuned policy gets considered).

Why this test changed
---------------------
Before the autodiscovery refactor this test parsed ``PULPO_SOURCES``
from the nightly workflow YAML to know which sources should be wired.
PULPO_SOURCES is now optional, so the registry itself is the source of
truth — these assertions iterate ``pulpo.agents.SOURCES`` instead.
"""
from __future__ import annotations
import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

SCRAPERS_DIR = REPO / "pulpo" / "scrapers"
TESTS_DIR    = REPO / "tests" / "scrapers"

# Helper modules in pulpo/scrapers/ that aren't sources. Treat as
# explicit allow-list — non-underscore additions get caught by the
# scraper-file glob below.
KNOWN_HELPERS = {
    "_base", "_policy", "_runtime", "_type_classifier", "_photo_url_upgrade",
    "__init__",
}


def _scraper_module_slugs() -> list[str]:
    """Return slugs of all non-helper scraper modules on disk."""
    return sorted(
        p.stem for p in SCRAPERS_DIR.glob("*.py")
        if p.stem not in KNOWN_HELPERS and not p.stem.startswith(".")
    )


# ── every scraper module imports cleanly ──────────────────────────────


def test_every_scraper_module_imports_cleanly():
    """A buggy scraper module — syntax error, broken dep, bad refactor —
    would silently drop the source from the autodiscovered registry.
    The nightly would skip it, the watchdog would notice the missing
    row a day later. This test makes that failure mode loud at CI time.
    """
    broken: dict[str, str] = {}
    for slug in _scraper_module_slugs():
        try:
            importlib.import_module(f"pulpo.scrapers.{slug}")
        except Exception as e:
            broken[slug] = f"{type(e).__name__}: {e}"
    assert not broken, (
        "Scraper modules failed to import — these silently drop from "
        "the autodiscovered registry:\n  "
        + "\n  ".join(f"{s}: {msg}" for s, msg in broken.items())
    )


# ── every scraper module ends up in the registry ──────────────────────


def test_every_scraper_module_registers_in_SOURCES():
    """Confirms each scraper module's ``register(SOURCES, "<slug>", _scraper)``
    side effect fired. Catches "file exists, registration missing" and
    "slug typo" — both produce a present-but-not-crawled scraper."""
    # Trigger autodiscovery via the package __init__.
    import pulpo.scrapers  # noqa: F401
    from pulpo.agents import SOURCES

    expected = set(_scraper_module_slugs())
    actual = set(SOURCES.keys())
    missing = expected - actual
    assert not missing, (
        f"Scraper modules on disk that didn't register in SOURCES: {sorted(missing)}. "
        f"Each scraper file must call register(SOURCES, '<slug>', _scraper) "
        f"with a slug that matches its filename stem."
    )


# ── every registered source has a test file ───────────────────────────


def test_every_registered_source_has_test_file():
    """Every source in the registry needs at minimum the offline-fixture
    smoke test, by convention at tests/scrapers/test_<slug>.py."""
    import pulpo.scrapers  # noqa: F401  — fires autodiscovery
    from pulpo.agents import SOURCES

    missing = [
        slug for slug in sorted(SOURCES.keys())
        if not (TESTS_DIR / f"test_{slug}.py").exists()
    ]
    assert not missing, (
        f"Registered sources without test files: {missing}. "
        f"Add tests/scrapers/test_<slug>.py covering at minimum the "
        f"offline-fixture path before merging."
    )


# ── policy fallback (informational, not blocking) ─────────────────────


def test_policy_entries_or_graceful_fallback():
    """Sources without an explicit ``Policy(...)`` row in
    pulpo/scrapers/_policy.py fall back to DEFAULT_POLICY at runtime.
    The fallback is safe — auto_repair=True, 0.5 rps, default UA pool —
    but high-volume or fragile scrapers benefit from explicit tuning.
    Surfaces the implicit-default list in the test log without
    blocking; explicit failure only if the policy module itself
    disappears."""
    import pulpo.scrapers  # noqa: F401
    from pulpo.agents import SOURCES
    from pulpo.scrapers._policy import POLICIES

    declared = sorted(SOURCES.keys())
    explicit = [s for s in declared if s in POLICIES]
    assert explicit, (
        "No source has an explicit policy entry — _policy.py may be "
        "empty or the import broke."
    )
    implicit = [s for s in declared if s not in POLICIES]
    if implicit:
        print(
            f"\n[source_integration] using DEFAULT_POLICY (implicit): "
            f"{implicit}. Safe but consider adding tuned Policy(...) "
            f"rows if rate-limit or UA pool matters."
        )


# ── PULPO_SOURCES override (when set) must be a subset ────────────────


def test_pulpo_sources_override_if_present_is_subset_of_registry():
    """The nightly workflow's optional PULPO_SOURCES env var is for
    debugging / temporary subset crawls (e.g., disable one noisy source).
    When set, every slug in it MUST be in the registry — a typo in the
    override would silently produce zero crawls for that slug.
    Hand-parses the YAML so this test has no PyYAML dep."""
    import re
    workflow = REPO / ".github" / "workflows" / "pulpo-nightly.yml"
    if not workflow.exists():
        return
    text = workflow.read_text(encoding="utf-8")
    # The line shape is `PULPO_SOURCES: "..."` (when set) — match only
    # the un-commented form so commented examples in the docs don't
    # trigger the assertion.
    pattern = re.compile(r'^\s*PULPO_SOURCES:\s*"([^"]+)"', re.MULTILINE)
    matches = pattern.findall(text)
    if not matches:
        # Not set → autodiscovery path, nothing to check.
        return
    import pulpo.scrapers  # noqa: F401
    from pulpo.agents import SOURCES
    for raw in matches:
        slugs = [s.strip() for s in raw.split(",") if s.strip()]
        missing = [s for s in slugs if s not in SOURCES]
        assert not missing, (
            f"PULPO_SOURCES override declares {missing} but they are "
            f"not in the registry. Remove the slug or fix the typo."
        )
