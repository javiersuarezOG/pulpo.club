"""Site-specific scrapers — auto-discovered.

How a new scraper gets wired in
-------------------------------
Drop ``pulpo/scrapers/<slug>.py`` with the standard register() call —
that's it. This module imports every non-underscore sibling at startup,
so the scraper's ``register(SOURCES, "<slug>", _scraper)`` side effect
fires automatically. The nightly's ``automation/run.py:1240`` then
defaults to ``REGISTRY.keys()`` when ``PULPO_SOURCES`` is unset, so the
new source is crawled without a workflow-YAML edit. The
``/admin/sources`` widget picks it up on its next refresh from the
source-health JSONL.

Skipped
-------
- Files starting with ``_`` (helpers like ``_runtime``, ``_policy``,
  ``_type_classifier``, ``_photo_url_upgrade``) — not scrapers, no
  ``register()`` call, importing them is fine but listing them in
  REGISTRY would be wrong.
- ``__init__.py`` itself, obviously.

Failure handling
----------------
A buggy scraper module (syntax error, broken dep) should NOT take down
the rest of the nightly. We catch ImportError + any startup-time
exception, log it, and continue. The failing scraper is absent from
SOURCES so the nightly skips it; the watchdog notices the missing row
in source_health_history.jsonl and surfaces it.

Contract enforcement
--------------------
``tests/test_source_integration.py`` asserts every discovered scraper
module imports cleanly + has a matching test file. That's the
deployment guard — CI fails before the data PR merges if onboarding is
incomplete.
"""
from __future__ import annotations
import importlib
import sys
from pathlib import Path

from pulpo.agents import SOURCES

_DIR = Path(__file__).parent


def _autodiscover() -> list[str]:
    """Import every non-underscore sibling module. Returns the slug list
    that was attempted (whether or not it registered)."""
    attempted: list[str] = []
    for path in sorted(_DIR.glob("*.py")):
        name = path.stem
        if name.startswith("_") or name == "__init__":
            continue
        attempted.append(name)
        try:
            importlib.import_module(f"{__name__}.{name}")
        except Exception as e:
            # Telemetry-style log to stderr — never propagate. The
            # missing-source signal surfaces via the source_health
            # JSONL not having a row for this slug, plus the contract
            # test catches it in CI before merge.
            print(
                f"[scrapers] auto-import failed for {name}: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
    return attempted


_DISCOVERED = _autodiscover()


# Backward-compat alias — use pulpo.agents.SOURCES in new code.
REGISTRY = SOURCES
