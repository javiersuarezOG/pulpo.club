"""Tests for automation/ig_queue_io.py — read either queue shape, write dict."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_queue_io import normalize, as_dict, load   # noqa: E402


def test_normalize_bare_list():
    items, meta = normalize([{"day": 1}, {"day": 2}])
    assert len(items) == 2
    assert meta["batch"] and meta["version"]


def test_normalize_dict():
    items, meta = normalize({"version": 3, "batch": "x", "items": [{"day": 1}]})
    assert items == [{"day": 1}]
    assert meta == {"version": 3, "batch": "x"}


def test_normalize_junk():
    assert normalize(None) == ([], {"version": 1, "batch": "autopilot"})


def test_as_dict_embeds_items_by_reference():
    items = [{"day": 1, "posted": False}]
    d = as_dict(items, {"batch": "b"})
    assert list(d.keys())[-1] == "items" and d["batch"] == "b"
    items[0]["posted"] = True                 # in-place edit
    assert d["items"][0]["posted"] is True     # persists through the wrapper


def test_load_reads_list_and_dict(tmp_path):
    lst = tmp_path / "list.json"
    lst.write_text(json.dumps([{"day": 1}]))
    assert load(lst)[0] == [{"day": 1}]
    dct = tmp_path / "dict.json"
    dct.write_text(json.dumps({"items": [{"day": 2}], "batch": "z"}))
    items, meta = load(dct)
    assert items == [{"day": 2}] and meta["batch"] == "z"
    assert load(tmp_path / "missing.json")[0] == []
