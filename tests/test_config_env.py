"""Tests for automation/_config.py — pins the empty-string contract.

The recurring bug: GitHub Actions resolves missing secrets to "" rather
than unset. `int(os.environ.get("X", "5"))` is "" when X is the secret
slot, which raises ValueError and crashes the nightly. Every reader in
this codebase must treat "" identically to unset. These tests pin that
contract — break them and the nightly will start crashing again.

Each helper is tested for:
  1. Unset env var → typed default
  2. Empty string env var → typed default (the GH Actions footgun)
  3. Whitespace-only env var → typed default
  4. Valid value → parsed value
  5. Unparseable value → typed default + a warning log line
"""
from __future__ import annotations
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation._config import (   # noqa: E402
    env_bool,
    env_csv,
    env_float,
    env_int,
    env_str,
)


# ── env_str ────────────────────────────────────────────────────────────

def test_env_str_unset_returns_default(monkeypatch):
    monkeypatch.delenv("PULPO_TEST_KEY", raising=False)
    assert env_str("PULPO_TEST_KEY", "fallback") == "fallback"


def test_env_str_empty_returns_default(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "")
    assert env_str("PULPO_TEST_KEY", "fallback") == "fallback"


def test_env_str_whitespace_returns_default(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "   ")
    assert env_str("PULPO_TEST_KEY", "fallback") == "fallback"


def test_env_str_strips_whitespace(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "  value  ")
    assert env_str("PULPO_TEST_KEY", "fallback") == "value"


# ── env_int ────────────────────────────────────────────────────────────

def test_env_int_unset_returns_default(monkeypatch):
    monkeypatch.delenv("PULPO_TEST_KEY", raising=False)
    assert env_int("PULPO_TEST_KEY", 42) == 42


def test_env_int_empty_returns_default(monkeypatch):
    """The bug a527237 fixed — GH Actions secret resolves to '' and the
    legacy `int(os.environ.get(..., default))` crashed."""
    monkeypatch.setenv("PULPO_TEST_KEY", "")
    assert env_int("PULPO_TEST_KEY", 42) == 42


def test_env_int_whitespace_returns_default(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "  ")
    assert env_int("PULPO_TEST_KEY", 42) == 42


def test_env_int_valid(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "7")
    assert env_int("PULPO_TEST_KEY", 42) == 7


def test_env_int_negative_valid(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "-3")
    assert env_int("PULPO_TEST_KEY", 42) == -3


def test_env_int_garbage_returns_default_with_warning(monkeypatch, capsys):
    monkeypatch.setenv("PULPO_TEST_KEY", "not-a-number")
    assert env_int("PULPO_TEST_KEY", 42) == 42
    captured = capsys.readouterr()
    assert "PULPO_TEST_KEY" in captured.out
    assert "not a valid int" in captured.out


# ── env_float ──────────────────────────────────────────────────────────

def test_env_float_unset_returns_default(monkeypatch):
    monkeypatch.delenv("PULPO_TEST_KEY", raising=False)
    assert env_float("PULPO_TEST_KEY", 1.5) == 1.5


def test_env_float_empty_returns_default(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "")
    assert env_float("PULPO_TEST_KEY", 1.5) == 1.5


def test_env_float_valid(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "0.25")
    assert env_float("PULPO_TEST_KEY", 1.5) == 0.25


def test_env_float_int_parses_as_float(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "3")
    assert env_float("PULPO_TEST_KEY", 1.5) == 3.0


def test_env_float_garbage_returns_default_with_warning(monkeypatch, capsys):
    monkeypatch.setenv("PULPO_TEST_KEY", "abc")
    assert env_float("PULPO_TEST_KEY", 1.5) == 1.5
    captured = capsys.readouterr()
    assert "not a valid float" in captured.out


# ── env_bool ───────────────────────────────────────────────────────────

def test_env_bool_unset_returns_default(monkeypatch):
    monkeypatch.delenv("PULPO_TEST_KEY", raising=False)
    assert env_bool("PULPO_TEST_KEY", False) is False
    assert env_bool("PULPO_TEST_KEY", True) is True


def test_env_bool_empty_returns_default(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "")
    assert env_bool("PULPO_TEST_KEY", False) is False
    assert env_bool("PULPO_TEST_KEY", True) is True


def test_env_bool_truthy_values(monkeypatch):
    for raw in ("1", "true", "TRUE", "Yes", "on", "  true  "):
        monkeypatch.setenv("PULPO_TEST_KEY", raw)
        assert env_bool("PULPO_TEST_KEY", False) is True, raw


def test_env_bool_falsy_values(monkeypatch):
    for raw in ("0", "false", "FALSE", "No", "off"):
        monkeypatch.setenv("PULPO_TEST_KEY", raw)
        assert env_bool("PULPO_TEST_KEY", True) is False, raw


def test_env_bool_garbage_returns_default_with_warning(monkeypatch, capsys):
    monkeypatch.setenv("PULPO_TEST_KEY", "maybe")
    assert env_bool("PULPO_TEST_KEY", False) is False
    captured = capsys.readouterr()
    assert "not a valid bool" in captured.out


# ── env_csv ────────────────────────────────────────────────────────────

def test_env_csv_unset_returns_default(monkeypatch):
    monkeypatch.delenv("PULPO_TEST_KEY", raising=False)
    assert env_csv("PULPO_TEST_KEY", ["a", "b"]) == ["a", "b"]
    assert env_csv("PULPO_TEST_KEY") == []


def test_env_csv_empty_returns_default(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "")
    assert env_csv("PULPO_TEST_KEY", ["a"]) == ["a"]


def test_env_csv_strips_and_filters_blanks(monkeypatch):
    monkeypatch.setenv("PULPO_TEST_KEY", "a, b , ,c,")
    assert env_csv("PULPO_TEST_KEY") == ["a", "b", "c"]


def test_env_csv_default_is_copied_not_aliased(monkeypatch):
    """Mutating the returned list should not mutate the caller's default."""
    monkeypatch.delenv("PULPO_TEST_KEY", raising=False)
    default = ["a", "b"]
    result = env_csv("PULPO_TEST_KEY", default)
    result.append("c")
    assert default == ["a", "b"]
