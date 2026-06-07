"""Helpers for data sidecars that need country-specific filenames.

Public catalog files already dual-write ``ranked.json`` and
``ranked.<CC>.json``. Operator sidecars need the same treatment so a PA
scaffold run cannot make the SV dashboard read PA-shaped diagnostics.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from automation._atomic import atomic_write_json
from pulpo.countries import active as _active_country, data_filename


def country_code() -> str:
    """Return the active country code for this pipeline shard."""
    return _active_country().code


def country_path(path: Path, cc: str | None = None) -> Path:
    """Return ``path`` with ``.<CC>`` inserted before its extension."""
    code = cc or country_code()
    return path.with_name(data_filename(path.name, code))


def write_json_sidecar(
    path: Path,
    payload: Any,
    *,
    indent: int = 2,
    sort_keys: bool = True,
    trailing_newline: bool = True,
    write_legacy: bool = True,
) -> None:
    """Write a JSON sidecar to legacy and per-country filenames."""
    path = Path(path)
    if write_legacy:
        atomic_write_json(
            path,
            payload,
            indent=indent,
            sort_keys=sort_keys,
            trailing_newline=trailing_newline,
        )
    cc_path = country_path(path)
    if cc_path != path:
        atomic_write_json(
            cc_path,
            payload,
            indent=indent,
            sort_keys=sort_keys,
            trailing_newline=trailing_newline,
        )
