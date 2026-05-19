"""Tests for automation/_atomic.py.

The whole point of the helper is that readers never see a half-written
file. These tests pin three guarantees:

1. Happy path: target ends up with the new contents byte-for-byte.
2. Mid-write crash: the tmp file is cleaned up and the previous target
   file (if any) is left intact.
3. Existing file: replacement is atomic — at no point does the target
   path point to a truncated or absent file.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation._atomic import atomic_write_json, atomic_write_text  # noqa: E402


def test_atomic_write_text_creates_file(tmp_path):
    p = tmp_path / "out.txt"
    atomic_write_text(p, "hello\n")
    assert p.read_text() == "hello\n"
    # No leftover tmp file
    assert list(tmp_path.iterdir()) == [p]


def test_atomic_write_json_default_no_trailing_newline(tmp_path):
    """Matches the legacy `json.dump(..., indent=2)` byte sequence — no
    trailing newline unless the caller asks for one. Several call sites
    in the pipeline diff against committed files; an unexpected newline
    would churn every nightly commit."""
    p = tmp_path / "out.json"
    atomic_write_json(p, {"a": 1}, indent=2)
    assert p.read_text() == '{\n  "a": 1\n}'


def test_atomic_write_json_trailing_newline_opt_in(tmp_path):
    p = tmp_path / "out.json"
    atomic_write_json(p, {"a": 1}, indent=2, trailing_newline=True)
    assert p.read_text() == '{\n  "a": 1\n}\n'


def test_atomic_write_json_compact(tmp_path):
    """Pipeline writes prices_history.json and listings_history.json
    without indent — must produce compact output that round-trips."""
    p = tmp_path / "history.json"
    atomic_write_json(p, {"k": [1, 2, 3]})
    assert json.loads(p.read_text()) == {"k": [1, 2, 3]}


def test_atomic_write_unicode_passthrough(tmp_path):
    """ensure_ascii defaults to False — matches the legacy behavior of
    the call sites we replaced and keeps Spanish text readable in git."""
    p = tmp_path / "out.json"
    atomic_write_json(p, {"loc": "Conchagüita, La Unión"})
    assert "Conchagüita" in p.read_text()


def test_atomic_write_replaces_existing(tmp_path):
    p = tmp_path / "out.txt"
    p.write_text("old")
    atomic_write_text(p, "new")
    assert p.read_text() == "new"


def test_atomic_write_failure_preserves_existing_target(tmp_path, monkeypatch):
    """If the tmp write blows up mid-flight (disk full, OSError, anything),
    the existing target file MUST be left untouched. That's the whole
    reliability win — readers see old contents until the new write is
    complete and renamed."""
    p = tmp_path / "out.json"
    p.write_text('{"a": 1}')

    # Force os.replace to fail AFTER the tmp file is written
    import automation._atomic as _atomic_mod

    def boom(src, dst):
        raise OSError("simulated rename failure")

    monkeypatch.setattr(_atomic_mod.os, "replace", boom)

    with pytest.raises(OSError, match="simulated rename failure"):
        atomic_write_json(p, {"a": 2}, indent=2)

    # Target unchanged — readers never observed a partial state
    assert p.read_text() == '{"a": 1}'
    # Tmp file cleaned up
    assert list(tmp_path.iterdir()) == [p]


def test_atomic_write_creates_parent_dir(tmp_path):
    p = tmp_path / "sub" / "nested" / "out.json"
    atomic_write_json(p, [1, 2, 3])
    assert json.loads(p.read_text()) == [1, 2, 3]
