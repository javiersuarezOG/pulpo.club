"""ig_prune_assets.py — delete autopilot slide assets no longer needed.

The autopilot renders a slide image per post and commits it so the
publisher can serve it to Instagram at post time. Once a post is published
(or skipped), its assets are dead weight — and photographic slides
accumulate fast: on 2026-07-26 they grew the repo past Vercel's deploy size
limit and every deploy started failing.

This prunes any ``web/data/ig_assets/autopilot/<dir>`` NOT referenced by a
currently **approved + unposted + not-skipped** queue item — i.e. keep only
what still needs to be served. Run it in the autopilot + publish workflows
so the repo stays lean automatically.

CLI:
    python3 -m automation.ig_prune_assets [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

DEFAULT_QUEUE = Path("web/data/ig_queue.json")
DEFAULT_ASSETS_ROOT = Path("web/data/ig_assets/autopilot")


def dirs_to_keep(queue: dict) -> set:
    """Asset-dir basenames still needed (approved, unposted, not skipped)."""
    keep: set = set()
    for it in queue.get("items", []):
        if it.get("approved") and not it.get("posted") and not it.get("skipped"):
            d = it.get("assets_dir") or ""
            if d:
                keep.add(Path(d).name)
    return keep


def prune(
    queue_path: Path = DEFAULT_QUEUE,
    assets_root: Path = DEFAULT_ASSETS_ROOT,
    *,
    dry_run: bool = False,
) -> list:
    """Remove asset dirs no longer referenced. Returns the removed paths."""
    if not assets_root.exists():
        return []
    keep = dirs_to_keep(json.loads(queue_path.read_text(encoding="utf-8"))) if queue_path.exists() else set()
    removed: list = []
    for d in sorted(p for p in assets_root.iterdir() if p.is_dir()):
        if d.name not in keep:
            removed.append(str(d))
            if not dry_run:
                shutil.rmtree(d)
    return removed


def main(argv: list | None = None) -> int:
    p = argparse.ArgumentParser(description="Prune autopilot slide assets no longer needed.")
    p.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    p.add_argument("--assets-root", type=Path, default=DEFAULT_ASSETS_ROOT)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    removed = prune(args.queue, args.assets_root, dry_run=args.dry_run)
    verb = "would remove" if args.dry_run else "removed"
    print(f"[ig_prune_assets] {verb} {len(removed)} dead asset dir(s)")
    for r in removed:
        print(f"  {verb}: {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
