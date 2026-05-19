"""Defensive env-var readers.

GitHub Actions resolves a missing secret to the empty string, not to
"unset". That breaks every parser that assumes `os.environ.get(name,
"5")` returns "5" when the variable is missing — the variable IS set,
just to "". The legacy pattern across the codebase was:

    int(os.environ.get("LLM_VISION_TOP_PCT", "5"))    # raises ValueError("")
    int(os.environ.get("LLM_VISION_TOP_PCT") or "5")  # safe, but easy to forget

This module centralizes the safe pattern + adds telemetry on bad values
so an operator who typo'd a config sees a log line instead of silent
fallback. Helpers always return the typed default for:

  - unset variable
  - empty string (the GH Actions footgun)
  - whitespace-only string
  - unparseable value (with a `[config]` warning print)

Why a print rather than logging: the pipeline doesn't run a logger
framework and the print convention is what every other module uses.
"""
from __future__ import annotations
import os
from typing import Optional


_TRUTHY = frozenset(("1", "true", "yes", "on"))
_FALSY = frozenset(("0", "false", "no", "off", ""))


def env_str(name: str, default: str = "") -> str:
    """Return env var as a stripped string, or `default` if unset/blank."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    stripped = raw.strip()
    return stripped if stripped else default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        print(f"[config] {name}={raw!r} is not a valid int — using default {default}")
        return default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        print(f"[config] {name}={raw!r} is not a valid float — using default {default}")
        return default


def env_bool(name: str, default: bool = False) -> bool:
    """Parse the env var as a boolean. Accepts 1/true/yes/on (case-insensitive)
    and 0/false/no/off. Empty / unset → `default`. Anything else logs a
    warning and falls back to `default`."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    val = raw.strip().lower()
    if val in _TRUTHY:
        return True
    if val in _FALSY:
        return False
    print(f"[config] {name}={raw!r} is not a valid bool — using default {default}")
    return default


def env_csv(name: str, default: Optional[list[str]] = None) -> list[str]:
    """Parse a comma-separated env var into a list of stripped non-empty
    tokens. Unset / blank → `default` (or empty list)."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default) if default is not None else []
    return [tok.strip() for tok in raw.split(",") if tok.strip()]
