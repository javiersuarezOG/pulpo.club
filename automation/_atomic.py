"""Atomic file-write helpers.

A crash, OOM, SIGKILL, or `kill -9` during `path.open("w")` leaves the
destination file truncated or half-written. For files the frontend reads
(`web/data/ranked.json`) or the pipeline depends on across runs
(`listings_history.json`, `prices_history.json`, the LLM enrichment
sidecar) that corruption is silent and only surfaces as a blank
production page or a fresh round of LLM spend.

Pattern: write to `<path>.tmp.<pid>` in the same directory as the target
(so the rename stays on one filesystem) and `os.replace()` onto the final
path. `os.replace` is atomic on POSIX and Windows — readers see either
the old contents or the new contents, never a partial mix.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Any


def _tmp_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.tmp.{os.getpid()}")


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp_path(path)
    try:
        with tmp.open("w", encoding=encoding) as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(
    path: Path,
    data: Any,
    *,
    trailing_newline: bool = False,
    **dump_kwargs: Any,
) -> None:
    """Serialize `data` to JSON and atomically replace `path`.

    `dump_kwargs` forwards to `json.dumps` (indent, ensure_ascii, default,
    etc.). Set `trailing_newline=True` to match call sites that previously
    wrote `json.dumps(...) + "\\n"`; default is off so output matches the
    legacy `json.dump(...)` byte-for-byte.
    """
    dump_kwargs.setdefault("ensure_ascii", False)
    payload = json.dumps(data, **dump_kwargs)
    if trailing_newline and not payload.endswith("\n"):
        payload += "\n"
    atomic_write_text(path, payload)
