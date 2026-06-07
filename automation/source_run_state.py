"""Source-attempt state helpers for partial scraper runs."""
from __future__ import annotations

from collections.abc import Iterable, Mapping


def succeeded_sources_for_ledger(
    attempted_sources: Iterable[str],
    source_errors: Mapping[str, str],
) -> set[str]:
    """Sources whose absence signal is meaningful for the listing ledger.

    A scoped run such as ``PULPO_SOURCES=nexo`` only attempts ``nexo``.
    Unattempted registered sources must not be treated as successful,
    otherwise their listings get marked missing/stale during local smoke
    or single-source development runs.
    """
    attempted = {src.strip() for src in attempted_sources if src and src.strip()}
    failed = {src.strip() for src in source_errors.keys() if src and src.strip()}
    return attempted - failed
