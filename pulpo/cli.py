"""
Command-line entry point.

Examples:
    # Run all sources offline against fixtures, write samples/ranked.csv
    python -m pulpo.cli --offline

    # Run goodlife only against the live site, top 20
    python -m pulpo.cli --source goodlife --limit 20

    # Specify output path
    python -m pulpo.cli --offline --out /tmp/ranked.csv
"""
from __future__ import annotations
import argparse
import csv
import json
import sys
from pathlib import Path

from .agents import SOURCES as REGISTRY
import pulpo.scrapers  # noqa: F401 — triggers registration of all sources
from .normalize import normalize
from .ranker import rank
from .units import fmt_area
from .models import Listing

CSV_FIELDS = [
    "rank", "rank_score",
    "value_score", "location_score", "momentum_score",
    "zone_percentile",
    "source", "source_id", "title",
    "zone", "municipality", "department",
    "area_m2", "area_display",
    "price_usd", "price_per_m2",
    "is_beachfront", "has_paved_access", "is_repriced",
    "days_listed", "photos_count",
    "url", "rank_reasons_short",
]

def _row(li: Listing) -> dict:
    area_display = fmt_area(li.area_m2) if li.area_m2 else ""
    return {
        "rank": li.rank,
        "rank_score": li.rank_score,
        "value_score": li.value_score,
        "location_score": li.location_score,
        "momentum_score": li.momentum_score,
        "zone_percentile": li.zone_percentile,
        "source": li.source,
        "source_id": li.source_id,
        "title": li.title,
        "zone": li.zone or "",
        "municipality": li.municipality or "",
        "department": li.department or "",
        "area_m2": li.area_m2,
        "area_display": area_display,
        "price_usd": li.price_usd,
        "price_per_m2": li.price_per_m2,
        "is_beachfront": li.is_beachfront,
        "has_paved_access": li.has_paved_access,
        "is_repriced": li.is_repriced,
        "days_listed": li.days_listed,
        "photos_count": li.photos_count,
        "url": li.url,
        "rank_reasons_short": " | ".join(li.rank_reasons),
    }

# ── Subcommand dispatch ────────────────────────────────────────────────
# The original CLI was a flat argparse with --offline / --source / etc.
# To preserve every existing invocation (`python -m pulpo.cli`,
# `python -m pulpo.cli --offline`, `python -m pulpo.cli --source X`),
# main() pre-checks whether argv[0] matches a registered subcommand
# slug and dispatches there before argparse ever runs. Anything else
# falls through to the original rank-pipeline flow unchanged.

_SUBCOMMANDS = {"enrich-photos", "check-hero-pool", "backfill-listing-photo-meta"}


def _run_enrich_photos(argv: list[str]) -> int:
    """Idempotent walk over photo directories — write a sidecar JSON for
    each derivative that doesn't already have one.

    Doesn't fetch from the network, doesn't touch ranked.json. Pure
    filesystem operation. Safe to re-run; the only output is per-file
    metadata captured against the on-disk dimensions.

    Targets:
      thumbs (web/photos/*.jpg minus *.hero.jpg)
      hero   (web/photos/*.hero.jpg)
      hires  (web/photos-hires/*.hires.jpg)   ← plan v2
      all    (default; walk all of the above)

    Usage:
        python -m pulpo.cli enrich-photos
        python -m pulpo.cli enrich-photos --target hires
        python -m pulpo.cli enrich-photos --force   # re-write existing sidecars
    """
    sp = argparse.ArgumentParser(prog="pulpo enrich-photos",
                                 description="Write image-enrichment sidecars for existing photos.")
    sp.add_argument("--force", action="store_true",
                    help="Overwrite sidecars even if they already exist.")
    sp.add_argument("--photos-dir", type=str, default=None,
                    help="Override legacy photos directory (default: <repo>/web/photos).")
    sp.add_argument("--photos-hires-dir", type=str, default=None,
                    help="Override hires photos directory (default: <repo>/web/photos-hires).")
    sp.add_argument("--target", choices=["thumbs", "hero", "hires", "all"], default="all",
                    help="Which derivative set to walk (default: all).")
    args = sp.parse_args(argv)

    try:
        from automation.photo_quality import compute_image_metadata
    except ImportError as e:
        print(f"enrich-photos: cannot import photo_quality ({e!r})", file=sys.stderr)
        return 1

    repo_root = Path(__file__).resolve().parents[1]
    photos_dir = Path(args.photos_dir) if args.photos_dir else repo_root / "web" / "photos"
    photos_hires_dir = (
        Path(args.photos_hires_dir) if args.photos_hires_dir
        else repo_root / "web" / "photos-hires"
    )

    # Collect targets honoring --target. Each entry is (file iter, label).
    targets: list[tuple[list[Path], str]] = []
    if args.target in ("thumbs", "all"):
        if photos_dir.exists():
            thumbs = [f for f in sorted(photos_dir.glob("*.jpg")) if not f.name.endswith(".hero.jpg")]
            targets.append((thumbs, "thumbs"))
        elif args.target == "thumbs":
            print(f"enrich-photos: photos dir not found: {photos_dir}", file=sys.stderr)
            return 1
    if args.target in ("hero", "all"):
        if photos_dir.exists():
            heros = list(sorted(photos_dir.glob("*.hero.jpg")))
            targets.append((heros, "hero"))
        elif args.target == "hero":
            print(f"enrich-photos: photos dir not found: {photos_dir}", file=sys.stderr)
            return 1
    if args.target in ("hires", "all"):
        if photos_hires_dir.exists():
            hires = list(sorted(photos_hires_dir.glob("*.hires.jpg")))
            targets.append((hires, "hires"))
        elif args.target == "hires":
            print(f"enrich-photos: hires dir not found: {photos_hires_dir}", file=sys.stderr)
            return 1

    scanned = wrote = skipped = failed = 0
    for files, label in targets:
        for f in files:
            scanned += 1
            sidecar = f.parent / (f.name + ".meta.json")
            if sidecar.exists() and not args.force:
                skipped += 1
                continue
            try:
                raw = f.read_bytes()
            except OSError as e:
                print(f"enrich-photos[{label}]: read failed for {f.name}: {e}", file=sys.stderr)
                failed += 1
                continue
            meta = compute_image_metadata(raw, file_size_bytes=len(raw))
            if meta is None:
                print(f"enrich-photos[{label}]: undecodable or Pillow missing for {f.name}")
                failed += 1
                continue
            sidecar.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
            wrote += 1

    print(f"[enrich-photos] target={args.target} scanned={scanned} wrote={wrote} "
          f"skipped={skipped} failed={failed}")
    return 0


def _run_check_hero_pool(argv: list[str]) -> int:
    """Report per-bucket (master_category × subcategory) eligibility
    coverage for the homepage proof row.

    Reads web/data/ranked.json and counts records where
    ``hero_eligible == True`` and ``card_eligible == True``, bucketed
    by ``master_category`` × ``subcategory``. Prints a summary table.

    Exit code 1 if the eligible pool is too small to render the
    proof-row diversity-pick (< 1 listing in each of beach + lake).
    Useful as a pre-deploy guard in CI.

    Usage:
        python -m pulpo.cli check-hero-pool
        python -m pulpo.cli check-hero-pool --min-per-master 3
    """
    sp = argparse.ArgumentParser(prog="pulpo check-hero-pool",
                                 description="Report image-enrichment pool coverage.")
    sp.add_argument("--min-per-master", type=int, default=1,
                    help="Minimum hero_eligible per master_category to pass (default 1).")
    sp.add_argument("--ranked-path", type=str, default=None,
                    help="Override ranked.json path (default: <repo>/web/data/ranked.json).")
    args = sp.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    ranked_path = Path(args.ranked_path) if args.ranked_path else repo_root / "web" / "data" / "ranked.json"
    if not ranked_path.exists():
        print(f"check-hero-pool: ranked.json not found: {ranked_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(ranked_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"check-hero-pool: malformed ranked.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(data, list):
        print("check-hero-pool: ranked.json is not a list", file=sys.stderr)
        return 1

    # Bucket counters: (master, sub) → {hero, card, total}
    from collections import defaultdict
    buckets: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: {"hero": 0, "card": 0, "total": 0}
    )
    master_totals: dict[str, int] = defaultdict(int)
    for rec in data:
        if not isinstance(rec, dict):
            continue
        master = rec.get("master_category") or "none"
        sub    = rec.get("subcategory")     or "none"
        key = (master, sub)
        buckets[key]["total"] += 1
        if rec.get("hero_eligible") is True:
            buckets[key]["hero"] += 1
            if master in ("beach", "lake"):
                master_totals[master] += 1
        if rec.get("card_eligible") is True:
            buckets[key]["card"] += 1

    print(f"\n[check-hero-pool] {ranked_path}")
    print(f"  total listings: {len(data)}\n")
    print(f"  {'bucket':<28} {'total':>7} {'card':>7} {'hero':>7}")
    print(f"  {'-'*28} {'-'*7} {'-'*7} {'-'*7}")
    for (master, sub) in sorted(buckets):
        b = buckets[(master, sub)]
        bucket_label = f"{master} × {sub}"
        print(f"  {bucket_label:<28} {b['total']:>7} {b['card']:>7} {b['hero']:>7}")

    print()
    print(f"  hero-eligible by master: {dict(master_totals)}")
    min_per = args.min_per_master
    failures = [m for m in ("beach", "lake") if master_totals.get(m, 0) < min_per]
    # Flush stdout BEFORE the PASS/FAIL line so terminal output stays
    # in order (stderr is unbuffered; without the flush the FAIL line
    # can appear above the table).
    sys.stdout.flush()
    if failures:
        print(
            f"\n[check-hero-pool] FAIL: master categories below "
            f"--min-per-master={min_per}: {failures}",
            file=sys.stderr,
        )
        return 1
    print(f"\n[check-hero-pool] PASS: every master has ≥ {min_per} hero-eligible listings")
    return 0


def _run_backfill_listing_photo_meta(argv: list[str]) -> int:
    """Propagate per-photo sidecar metadata onto existing ranked.json rows.

    For each listing in web/data/ranked.json:
      1. Locate the on-disk hero sidecar (web/photos/<source>_<id>.hero.jpg.meta.json)
         and the thumbnail sidecar (web/photos/<source>_<id>.jpg.meta.json).
      2. Populate the listing's source_width / source_height fields from the
         hero sidecar when available (the hero file was created via Pillow's
         thumbnail() which only ever downsamples, so hero dimensions equal
         source dimensions clamped to <=1920x1080). Fall back to the thumb
         sidecar's dimensions when no hero sidecar exists.
      3. Set hero_eligible / card_eligible from whichever sidecar provides them.

    Idempotent — re-running on a listing whose sidecar has the same numbers
    produces an identical row.

    Usage:
        python -m pulpo.cli backfill-listing-photo-meta
        python -m pulpo.cli backfill-listing-photo-meta --dry-run
        python -m pulpo.cli backfill-listing-photo-meta --ranked-path /tmp/r.json
    """
    sp = argparse.ArgumentParser(
        prog="pulpo backfill-listing-photo-meta",
        description="Propagate photo sidecar metadata onto ranked.json rows.",
    )
    sp.add_argument("--dry-run", action="store_true",
                    help="Report counts without writing ranked.json.")
    sp.add_argument("--ranked-path", type=str, default=None,
                    help="Override ranked.json path (default: <repo>/web/data/ranked.json).")
    sp.add_argument("--photos-dir", type=str, default=None,
                    help="Override photos dir (default: <repo>/web/photos).")
    args = sp.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    ranked_path = Path(args.ranked_path) if args.ranked_path else repo_root / "web" / "data" / "ranked.json"
    photos_dir = Path(args.photos_dir) if args.photos_dir else repo_root / "web" / "photos"

    if not ranked_path.exists():
        print(f"backfill: ranked.json not found at {ranked_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(ranked_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"backfill: malformed ranked.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(data, list):
        print("backfill: ranked.json is not a list", file=sys.stderr)
        return 1

    scanned = updated = missing = unchanged = 0
    for rec in data:
        if not isinstance(rec, dict):
            continue
        scanned += 1
        source = rec.get("source")
        source_id = rec.get("source_id")
        if not source or not source_id:
            continue
        fname_stem = f"{source}_{source_id}"
        thumb_meta_path = photos_dir / f"{fname_stem}.jpg.meta.json"
        hero_meta_path = photos_dir / f"{fname_stem}.hero.jpg.meta.json"

        # Prefer hero sidecar; thumbnail is downsampled to 600x400 max so its
        # width/height understates the source.
        meta_src = None
        if hero_meta_path.exists():
            try:
                meta_src = json.loads(hero_meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta_src = None
        if meta_src is None and thumb_meta_path.exists():
            try:
                meta_src = json.loads(thumb_meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta_src = None
        if meta_src is None:
            missing += 1
            continue

        new_w = meta_src.get("width")
        new_h = meta_src.get("height")
        new_hero_eligible = meta_src.get("hero_eligible")
        new_card_eligible = meta_src.get("card_eligible")

        # Only patch fields that resolve; leave existing values alone otherwise.
        changed = False
        if new_w is not None and rec.get("source_width") != int(new_w):
            rec["source_width"] = int(new_w)
            changed = True
        if new_h is not None and rec.get("source_height") != int(new_h):
            rec["source_height"] = int(new_h)
            changed = True
        # Eligibility flags only update when reading from the *hero* sidecar
        # (thumbnail-only listings have meaningless hero_eligible). Detect by
        # whether the source dict came from the hero path.
        if hero_meta_path.exists() and meta_src is not None:
            if new_hero_eligible is not None and rec.get("hero_eligible") != bool(new_hero_eligible):
                rec["hero_eligible"] = bool(new_hero_eligible)
                changed = True
        if new_card_eligible is not None and rec.get("card_eligible") != bool(new_card_eligible):
            rec["card_eligible"] = bool(new_card_eligible)
            changed = True

        if changed:
            updated += 1
        else:
            unchanged += 1

    if args.dry_run:
        print(f"[backfill] DRY RUN — scanned={scanned} would_update={updated} "
              f"unchanged={unchanged} no_sidecar={missing}")
        return 0

    ranked_path.write_text(json.dumps(data, indent=2, default=str) + "\n",
                           encoding="utf-8")
    print(f"[backfill] scanned={scanned} updated={updated} "
          f"unchanged={unchanged} no_sidecar={missing}")
    return 0


def _dispatch_subcommand(name: str, argv: list[str]) -> int:
    if name == "enrich-photos":
        return _run_enrich_photos(argv)
    if name == "check-hero-pool":
        return _run_check_hero_pool(argv)
    if name == "backfill-listing-photo-meta":
        return _run_backfill_listing_photo_meta(argv)
    print(f"pulpo: unknown subcommand '{name}'", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    # Subcommand fast-path. Has to live BEFORE argparse so that existing
    # invocations (`python -m pulpo.cli --offline`) keep working unchanged.
    if args and args[0] in _SUBCOMMANDS:
        return _dispatch_subcommand(args[0], args[1:])

    p = argparse.ArgumentParser(prog="pulpo", description="pulpo.club aggregator pipeline")
    p.add_argument("--source", action="append", default=None,
                   help="Source slug, repeatable. Default: all (goodlife,oceanside,kazu).")
    p.add_argument("--limit", type=int, default=30, help="Max listings per source")
    p.add_argument("--offline", action="store_true", help="Use fixtures, skip network")
    p.add_argument("--out", type=str, default="samples/ranked.csv",
                   help="Output CSV path (relative to repo root)")
    p.add_argument("--json-out", type=str, default=None,
                   help="Optional JSON output path for full Listing records")
    args = p.parse_args(args)

    sources = args.source or list(REGISTRY.keys())
    repo_root = Path(__file__).resolve().parents[1]

    # Crawl
    all_raw: list[dict] = []
    for src in sources:
        mod = REGISTRY.get(src)
        if not mod:
            print(f"unknown source: {src}", file=sys.stderr)
            continue
        recs = mod.crawl(limit=args.limit, offline=args.offline or None)
        print(f"[{src}] crawled {len(recs)} raw records")
        for r in recs:
            r.setdefault("source", src)
            all_raw.append(r)

    # Normalize
    listings: list[Listing] = []
    dropped = 0
    for r in all_raw:
        li = normalize(r, source=r.get("source") or "unknown")
        if li:
            listings.append(li)
        else:
            dropped += 1
    print(f"normalized {len(listings)} listings ({dropped} dropped)")

    # Rank
    ranked = rank(listings)
    print(f"ranked {len(ranked)} listings")

    # Write CSV
    out_path = repo_root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for li in ranked:
            w.writerow(_row(li))
    print(f"wrote {out_path.relative_to(repo_root)}")

    if args.json_out:
        jp = repo_root / args.json_out
        jp.parent.mkdir(parents=True, exist_ok=True)
        with jp.open("w", encoding="utf-8") as f:
            json.dump([li.to_dict() for li in ranked], f, indent=2, default=str)
        print(f"wrote {jp.relative_to(repo_root)}")

    # Print top 5 to stdout
    print("\nTop 5 (rank | composite | V/L/M | zone | price | $/m² | title):")
    for li in ranked[:5]:
        print(
            f" #{li.rank:<2} {li.rank_score:>5.1f}  "
            f"V{li.value_score:>4.0f} L{li.location_score:>4.0f} "
            f"M{li.momentum_score:>4.0f}  "
            f"{li.zone or '?':<13} "
            f"${(li.price_usd or 0):>10,.0f}  "
            f"${li.price_per_m2 or 0:>7.2f}/m²  "
            f"{li.title[:50]}"
        )
    return 0

if __name__ == "__main__":
    sys.exit(main())
