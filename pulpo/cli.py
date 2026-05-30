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

_SUBCOMMANDS = {"enrich-photos", "check-hero-pool", "check-hero-variants", "backfill-listing-photo-meta", "scrape-external"}


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


def _list_origin_main_photos(repo_root: Path) -> set[str]:
    """Return every blob path under web/photos/ at origin/main's tip.

    Used by ``check-hero-variants`` to treat "exists in committed main"
    as "present" — production serves photos from main, so a file that
    exists there will be live regardless of the runner's working-tree
    state. Returns an empty set if git is unavailable, the repo isn't
    a git checkout, or origin/main isn't fetched; the caller treats an
    empty result as "no fallback", which collapses cleanly to the strict
    working-tree-only check.

    Output paths are relative to repo root, e.g. ``web/photos/foo.hero.jpg``.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "origin/main", "web/photos/"],
            cwd=repo_root, capture_output=True, text=True, timeout=30,
            check=False,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        # git missing or repo isn't a checkout — degrade to strict mode
        # silently. Same effect as --no-main-fallback.
        return set()
    if result.returncode != 0:
        return set()
    return {ln.strip() for ln in result.stdout.splitlines() if ln.strip()}


def _run_check_hero_variants(argv: list[str]) -> int:
    """Verify every ranked.json listing's `.hero.jpg` variant will be
    present on `main` after this nightly's data commit lands.

    Frontend regression guard for the home-hero LCP fix (PR-perf-hero,
    2026-05-21). HeroV4 derives a local `/photos/<id>.hero.jpg` path
    from `hero_photo_path` (`/photos/<id>.jpg`) and routes it through
    /api/img for WebP optimization. If the pipeline ever stops producing
    `.hero.jpg`, /api/img 404s and the hero quietly falls back to the
    broker URL — re-introducing the 14.5s P95 LCP regression we just
    closed.

    What "present" means
    --------------------
    Production serves photos from `main` (Vercel deploys the committed
    tree). The check therefore treats a hero variant as present if EITHER:

      (a) it exists in the runner's working tree (the just-produced
          pipeline output), OR
      (b) it exists in `origin/main` and the nightly's commit step
          isn't removing it (`git add` is additive — files in main
          stay in main unless explicitly `git rm`-ed).

    The origin/main fallback fixes a false-alarm class first observed
    2026-05-27: the canary failed 4 nightlies in a row claiming 182/200
    top hero variants were missing, yet every offender was present on
    `main` and serving cleanly via /api/img. Production was unaffected
    but the data commit was blocked for 4 days, masking the
    source_health_history updates that drive /admin/sources. Consulting
    origin/main as a fallback eliminates that false-positive class
    while keeping the regression guard intact: a hero variant truly
    missing from BOTH the working tree AND main will still fail.

    Exit code:
        0 — every listing with a `hero_photo_path` will have a safe
            `.hero.jpg` variant on main after this nightly commits.
        1 — at least one listing's variant is missing from both the
            working tree AND main, OR a filename is unsafe. Stdout
            summarises; stderr lists offenders.

    Usage:
        python3 -m pulpo.cli check-hero-variants
        python3 -m pulpo.cli check-hero-variants --top-only 50
        python3 -m pulpo.cli check-hero-variants --no-main-fallback
    """
    import re

    sp = argparse.ArgumentParser(
        prog="pulpo check-hero-variants",
        description="Verify .hero.jpg variants exist for every ranked listing.",
    )
    sp.add_argument(
        "--ranked-path", type=str, default=None,
        help="Override ranked.json path (default: <repo>/web/data/ranked.json).",
    )
    sp.add_argument(
        "--repo-root", type=str, default=None,
        help="Override the repo root used to resolve photo paths and to "
             "consult origin/main (default: auto-detected from this script's "
             "location). Tests use this to run against a temp repo.",
    )
    sp.add_argument(
        "--top-only", type=int, default=0,
        help="Restrict the check to the N highest-rank_score listings (default: 0 = all).",
    )
    sp.add_argument(
        "--no-main-fallback", action="store_true",
        help="Skip the origin/main fallback. Strict working-tree-only check; "
             "useful for local debugging when you want the pre-2026-05-30 "
             "behaviour. Not appropriate for nightly CI — see docstring.",
    )
    args = sp.parse_args(argv)

    repo_root = Path(args.repo_root) if args.repo_root else Path(__file__).resolve().parents[1]
    ranked_path = Path(args.ranked_path) if args.ranked_path else repo_root / "web" / "data" / "ranked.json"
    if not ranked_path.exists():
        print(f"check-hero-variants: ranked.json not found: {ranked_path}", file=sys.stderr)
        return 1

    try:
        data = json.loads(ranked_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"check-hero-variants: malformed ranked.json: {e}", file=sys.stderr)
        return 1
    if not isinstance(data, list):
        print("check-hero-variants: ranked.json is not a list", file=sys.stderr)
        return 1

    records = [r for r in data if isinstance(r, dict)]
    if args.top_only > 0:
        records = sorted(records, key=lambda r: r.get("rank_score") or 0, reverse=True)[: args.top_only]

    # /api/img path-traversal guard (api/img.js:70). Anything outside this
    # regex returns 400; the FE then falls back to the raw broker URL —
    # which is exactly the regression this check exists to catch.
    SAFE_FILENAME = re.compile(r"^[a-z0-9_.-]+$", re.IGNORECASE)

    # ── origin/main file index (lazy, single git call) ────────────────
    # `git ls-tree -r origin/main web/photos/` returns every blob path
    # under web/photos at the current tip of main. Converting to a set
    # makes membership checks O(1) and avoids ~200 git subprocess calls
    # in the hot loop. Returns an empty set if the repo isn't a git
    # checkout (test environments, distribution tarballs) or if
    # origin/main isn't fetched — in both cases the fallback degrades
    # gracefully and the check behaves like the pre-2026-05-30 version.
    main_files = _list_origin_main_photos(repo_root) if not args.no_main_fallback else set()

    missing: list[tuple[float, str]] = []
    unsafe: list[str] = []
    rescued_from_main = 0
    skipped_no_path = 0
    checked = 0

    for rec in records:
        hp = rec.get("hero_photo_path")
        if not isinstance(hp, str) or not hp.startswith("/photos/") or not hp.endswith(".jpg"):
            skipped_no_path += 1
            continue
        checked += 1
        hero_rel = hp[:-4] + ".hero.jpg"
        hero_fs = repo_root / "web" / hero_rel.lstrip("/")
        if not hero_fs.exists():
            # Fallback: file is "present" if origin/main has it and our
            # commit step won't remove it. Path in git is relative to
            # repo root, so strip the leading "/" and prepend "web".
            main_path = "web" + hero_rel  # e.g. "web/photos/foo.hero.jpg"
            if main_path in main_files:
                rescued_from_main += 1
            else:
                missing.append((rec.get("rank_score") or 0.0, hp))
        # Filename safety
        filename = hero_rel.rsplit("/", 1)[-1]
        if not SAFE_FILENAME.match(filename):
            unsafe.append(filename)

    print(f"\n[check-hero-variants] {ranked_path}")
    print(f"  total records:        {len(records)}")
    print(f"  checked (have path):  {checked}")
    print(f"  skipped (no path):    {skipped_no_path}")
    print(f"  missing .hero.jpg:    {len(missing)}")
    if rescued_from_main:
        # Surfaced so a sustained non-zero value (working tree drifting
        # away from main mid-pipeline) is visible without parsing JSON.
        # Zero is the goal; a large number means something is removing
        # working-tree files between checkout and this step.
        print(f"  rescued from main:    {rescued_from_main}")
    print(f"  unsafe filenames:     {len(unsafe)}")
    sys.stdout.flush()

    if missing or unsafe:
        if missing:
            fallback_note = (
                " (not in working tree AND not in origin/main)"
                if not args.no_main_fallback else ""
            )
            print(
                f"\n[check-hero-variants] FAIL: {len(missing)} listing(s) "
                f"missing .hero.jpg{fallback_note}",
                file=sys.stderr,
            )
            for rs, hp in missing[:20]:
                print(f"  rank={rs} hero_photo_path={hp}", file=sys.stderr)
            if len(missing) > 20:
                print(f"  ... and {len(missing) - 20} more", file=sys.stderr)
        if unsafe:
            print(
                f"\n[check-hero-variants] FAIL: {len(unsafe)} unsafe filename(s) (would 400 at /api/img)",
                file=sys.stderr,
            )
            for fn in unsafe[:20]:
                print(f"  {fn}", file=sys.stderr)
        return 1

    print("\n[check-hero-variants] PASS: every checked listing has a safe .hero.jpg variant")
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


def _run_scrape_external(argv: list[str]) -> int:
    """Scrape a comma-separated list of sources from this host and write
    the records to <out>/<source>.json for the main nightly to pick up.

    Purpose
    -------
    realtyelsalvador + elagente's WAFs block GitHub-hosted (Azure)
    runner IPs, so the main nightly on Azure can't reach them.
    Confirmed 2026-05-30 via probes from GH-runner, Vercel/AWS Lambda,
    Google Cloud Shell, and a laptop residential IP. GCP IPs pass.
    This command runs on a GCP self-hosted runner (label
    `gcp-residential`, see scripts/setup-gcp-runner.sh), scrapes the
    two blocked sources live, and writes a cache file the main
    nightly's scrapers fall back to.

    Output
    ------
    For each source, ``<out>/<source>.json`` of the form:

        {
          "ts":      "2026-05-30T01:34:12Z",
          "source":  "realtyelsalvador",
          "scraper_version": "html-v2-2026-05",
          "count":   118,
          "records": [...]   // same dict-per-listing shape produced
                              //   by ``scraper.crawl()`` — the main
                              //   nightly consumes these directly
        }

    The ts is the wall-clock time the scrape completed. The main
    nightly's scrapers treat the cache as authoritative if ts is
    within a freshness window (configurable, default 25h — one
    nightly + slack); otherwise they fall through to the live fetch
    (which will still 403 on Azure, surfacing the staleness as a red
    source-health row that's actionable).

    Exit code
    ---------
    0 — every requested source produced a non-empty cache file.
    1 — at least one source produced zero records OR raised an
        exception. The shim workflow uses this to decide whether to
        commit + push (we never commit a regression).

    Usage
    -----
        # Run by the scrape-shim workflow on the GCP self-hosted runner:
        python3 -m pulpo.cli scrape-external \\
            --sources realtyelsalvador,elagente \\
            --out web/data/scrape_cache
    """
    from datetime import datetime, timezone

    sp = argparse.ArgumentParser(
        prog="pulpo scrape-external",
        description="Scrape one or more sources and write cache files for the main nightly.",
    )
    sp.add_argument(
        "--sources", type=str, required=True,
        help="Comma-separated source slugs (e.g. realtyelsalvador,elagente).",
    )
    sp.add_argument(
        "--out", type=str, required=True,
        help="Output directory for <source>.json cache files (created if absent).",
    )
    sp.add_argument(
        "--limit", type=int, default=200,
        help="Max records per source (default 200 — enough for realty+elagente "
             "current catalogues with headroom).",
    )
    args = sp.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = repo_root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Import lazily so a fresh checkout that hasn't installed scraper
    # deps yet still loads the CLI without errors. The scrape itself
    # will obviously need the deps; we want a clean stack trace from
    # the scrape, not a CLI import-time crash.
    from pulpo.agents import SOURCES

    requested = [s.strip() for s in args.sources.split(",") if s.strip()]
    if not requested:
        print("scrape-external: --sources is empty", file=sys.stderr)
        return 2

    overall_ok = True
    for slug in requested:
        scraper = SOURCES.get(slug)
        if scraper is None:
            print(f"scrape-external: unknown source {slug!r} (registered: "
                  f"{sorted(SOURCES.keys())})", file=sys.stderr)
            overall_ok = False
            continue

        print(f"[scrape-external] scraping {slug} (limit={args.limit})")
        try:
            records = scraper.crawl(limit=args.limit, offline=False)
        except Exception as e:
            # Surfacing the exception in the cache file would let the
            # main nightly distinguish "WAF block downstream" from
            # "scraper code raised" — but a corrupted cache is worse
            # than no cache. Skip the write so the main nightly falls
            # through to the live path (which will also fail, but in
            # the existing failure mode that the watchdog already
            # understands).
            print(f"[scrape-external] {slug} crawl raised: {e!r}", file=sys.stderr)
            overall_ok = False
            continue

        if not records:
            print(f"[scrape-external] {slug} produced 0 records — "
                  f"not writing cache (would mask the failure)", file=sys.stderr)
            overall_ok = False
            continue

        # ts uses Z suffix (UTC) rather than the ISO offset form to
        # match the rest of Pulpo's telemetry files
        # (last_updated.json's started_at, source_health_history's ts).
        envelope = {
            "ts":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source":  slug,
            "count":   len(records),
            "records": records,
        }
        cache_path = out_dir / f"{slug}.json"
        cache_path.write_text(json.dumps(envelope, indent=2, default=str) + "\n",
                              encoding="utf-8")
        print(f"[scrape-external] {slug}: wrote {len(records)} records to {cache_path}")

    return 0 if overall_ok else 1


def _dispatch_subcommand(name: str, argv: list[str]) -> int:
    if name == "enrich-photos":
        return _run_enrich_photos(argv)
    if name == "check-hero-pool":
        return _run_check_hero_pool(argv)
    if name == "check-hero-variants":
        return _run_check_hero_variants(argv)
    if name == "backfill-listing-photo-meta":
        return _run_backfill_listing_photo_meta(argv)
    if name == "scrape-external":
        return _run_scrape_external(argv)
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
