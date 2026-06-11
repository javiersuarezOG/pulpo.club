"""Scope-limited, reversible edits for the scraper-agent loop.

The loop edits exactly one scraper module (and optionally its test) over and
over, keeping the best version and discarding regressions. ``Sandbox`` is the
guardrail and the undo buffer:

- **Scope.** It will only write ``pulpo/scrapers/<slug>.py`` and
  ``tests/scrapers/test_<slug>.py``. Any other path raises
  :class:`ScopeViolation`. This is the same blast-radius limit the shadow-mode
  ``scripts/scraper_autorepair.py`` enforces in its prompt — here it's enforced
  in code, so a misbehaving agent physically cannot touch normalize.py, the
  ranker, a data file, or another scraper.
- **Keep/discard.** ``checkpoint()`` snapshots the current files as "best";
  ``rollback()`` restores them. The loop checkpoints when fitness improves and
  rolls back when it regresses — the autoresearch keep-or-discard step.
- **Clean exit.** Used as a context manager, the sandbox restores the original
  on-disk state on exit unless ``commit()`` was called. A brand-new scraper
  file that the loop failed to make viable is deleted, not left behind.

It also owns the **module-reload** detail: because the loop rewrites the file
in-process, the previously-imported module is cached in ``sys.modules`` with
the *old* source. ``reload_scraper`` evicts that cache so the next
``lab_run`` import reflects the edit instead of re-running stale code.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Optional


class ScopeViolation(RuntimeError):
    """Raised when a write targets a path outside the sandbox's allowlist."""


def reload_scraper(slug: str) -> None:
    """Evict a scraper module (and its lab cache) so the next import re-reads
    the file from disk. Call after every edit, before re-evaluating."""
    importlib.invalidate_caches()
    for name in list(sys.modules):
        if name == f"pulpo.scrapers.{slug}" or name.startswith(
            f"pulpo.scrapers.{slug}."
        ):
            del sys.modules[name]


class Sandbox:
    """A reversible, scope-limited editor for one scraper and its test file."""

    def __init__(self, repo_root: Path, slug: str):
        self.repo_root = Path(repo_root).resolve()
        self.slug = slug
        self.scraper_path = self.repo_root / "pulpo" / "scrapers" / f"{slug}.py"
        self.test_path = self.repo_root / "tests" / "scrapers" / f"test_{slug}.py"
        self._allowed = {self.scraper_path.resolve(), self.test_path.resolve()}
        # path -> original bytes, or None if the file did not exist on entry.
        self._original: dict[Path, Optional[str]] = {}
        # path -> best-known-good bytes captured by checkpoint().
        self._best: dict[Path, Optional[str]] = {}
        self._committed = False
        self._entered = False

    # ── lifecycle ────────────────────────────────────────────────────
    def __enter__(self) -> "Sandbox":
        for p in self._allowed:
            self._original[p] = p.read_text(encoding="utf-8") if p.exists() else None
        self._best = dict(self._original)
        self._entered = True
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if not self._committed:
            self.restore_original()
        reload_scraper(self.slug)

    # ── scope ────────────────────────────────────────────────────────
    def _resolve_allowed(self, path: Path) -> Path:
        resolved = Path(path).resolve()
        if resolved not in self._allowed:
            raise ScopeViolation(
                f"sandbox refuses to write {resolved} — only "
                f"{sorted(str(p) for p in self._allowed)} are in scope"
            )
        return resolved

    # ── edits ────────────────────────────────────────────────────────
    def read(self, path: Path) -> Optional[str]:
        resolved = self._resolve_allowed(path)
        return resolved.read_text(encoding="utf-8") if resolved.exists() else None

    def apply(self, path: Path, content: str) -> None:
        """Write ``content`` to an allowed path and evict the module cache."""
        resolved = self._resolve_allowed(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(content, encoding="utf-8")
        reload_scraper(self.slug)

    # ── keep / discard ───────────────────────────────────────────────
    def checkpoint(self) -> None:
        """Record the current on-disk content of all allowed paths as best."""
        for p in self._allowed:
            self._best[p] = p.read_text(encoding="utf-8") if p.exists() else None

    def rollback(self) -> None:
        """Restore all allowed paths to the last checkpoint (best-known-good)."""
        self._write_snapshot(self._best)
        reload_scraper(self.slug)

    def restore_original(self) -> None:
        """Restore all allowed paths to their pre-sandbox state."""
        self._write_snapshot(self._original)
        reload_scraper(self.slug)

    def _write_snapshot(self, snapshot: dict[Path, Optional[str]]) -> None:
        for p, content in snapshot.items():
            if content is None:
                if p.exists():
                    p.unlink()
            else:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")

    # ── commit ───────────────────────────────────────────────────────
    def commit(self) -> None:
        """Promote best-known-good to disk and skip restore-on-exit, leaving
        the winning scraper in the worktree for a human to review and PR."""
        self._write_snapshot(self._best)
        reload_scraper(self.slug)
        self._committed = True
