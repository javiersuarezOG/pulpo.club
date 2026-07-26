"""Tests for automation/ig_prune_assets.py — keep only still-needed assets."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from automation.ig_prune_assets import dirs_to_keep, prune   # noqa: E402


def test_dirs_to_keep_only_approved_unposted():
    queue = {"items": [
        {"assets_dir": "web/data/ig_assets/autopilot/d301__a", "approved": True, "posted": False},
        {"assets_dir": "web/data/ig_assets/autopilot/d302__b", "approved": True, "posted": True},   # posted
        {"assets_dir": "web/data/ig_assets/autopilot/d303__c", "approved": False, "skipped": True},  # skipped
    ]}
    assert dirs_to_keep(queue) == {"d301__a"}


def test_prune_removes_dead_keeps_live(tmp_path):
    root = tmp_path / "autopilot"
    for name in ("d301__a", "d302__b", "d303__c"):
        (root / name).mkdir(parents=True)
        (root / name / "slide_1.jpg").write_bytes(b"x")
    queue = tmp_path / "q.json"
    queue.write_text(json.dumps({"items": [
        {"assets_dir": "web/data/ig_assets/autopilot/d301__a", "approved": True, "posted": False},
        {"assets_dir": "web/data/ig_assets/autopilot/d302__b", "approved": True, "posted": True},
        {"assets_dir": "web/data/ig_assets/autopilot/d303__c", "approved": True, "skipped": True},
    ]}))
    removed = prune(queue, root)
    assert (root / "d301__a").exists()          # live one kept
    assert not (root / "d302__b").exists()      # posted pruned
    assert not (root / "d303__c").exists()      # skipped pruned
    assert len(removed) == 2


def test_prune_dry_run_removes_nothing(tmp_path):
    root = tmp_path / "autopilot"
    (root / "d999__x").mkdir(parents=True)
    queue = tmp_path / "q.json"
    queue.write_text(json.dumps({"items": []}))
    removed = prune(queue, root, dry_run=True)
    assert (root / "d999__x").exists()
    assert removed == [str(root / "d999__x")]
