"""
PR-7.5 — one-time migration: nuke the LLM enrichment sidecar so the
next pipeline run re-enriches every listing with the new bilingual
{en, es} prompt.

Why a script (not part of the nightly):
- The sidecar (`web/data/llm_enrichment.json`) caches DeepSeek responses
  to skip the API call on listings that already have title_canonical /
  short_description_canonical / reasons_to_buy / latlong populated.
- PR-7.5 changes the schema (schema_version 1 → 2: bilingual). The cached
  responses are pre-bilingual and would never trigger a re-enrich because
  the eligibility check sees the old fields populated and skips.
- Wiping the sidecar one time forces a full re-enrich (~$10 in DeepSeek
  tokens, ~15 min wall-clock).

Run:
    python -m scripts.reenrich_all              # nuke sidecar + clear stale fields
    python -m scripts.reenrich_all --dry-run    # show what would change

After running, kick off the regular nightly:
    python -m automation.run

The next run will see every listing as eligible, hit the API, and
populate the new bilingual shape. Subsequent runs go back to the
cached path.

This script is one-time. After the cutover, delete it (or keep it
around as a recipe for future schema bumps — the same pattern).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


# Fields the LLM enrichment populates. Listed here (rather than imported
# from llm_enrichment_schema) because this script is intentionally
# decoupled — it must be runnable even when the schema is mid-edit.
LLM_TARGET_FIELDS = (
    "title_canonical",
    "short_description_canonical",
    "reasons_to_buy",
    "url_language",
    # latlong-derived — leave these alone because the prompt produces
    # them but a Mapbox/manual fallback may also have populated them.
    # If you genuinely want a full re-geocode, drop "lat"/"lng" too.
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reenrich_all", description=__doc__)
    p.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be removed/cleared without touching files."
    )
    args = p.parse_args(argv)

    sidecar = REPO / "web" / "data" / "llm_enrichment.json"
    ranked = REPO / "web" / "data" / "ranked.json"

    if sidecar.exists():
        try:
            sidecar_data = json.loads(sidecar.read_text())
            n_entries = len(sidecar_data) if isinstance(sidecar_data, dict) else 0
        except Exception:
            n_entries = 0
        print(f"sidecar: {sidecar.relative_to(REPO)} ({n_entries} entries)")
        if args.dry_run:
            print("  [dry-run] would delete this file")
        else:
            sidecar.unlink()
            print("  deleted")
    else:
        print(f"sidecar: {sidecar.relative_to(REPO)} — not present (already clean)")

    if not ranked.exists():
        print(f"ranked.json: not present — skipping field clear")
        return 0

    data = json.loads(ranked.read_text())
    if not isinstance(data, list):
        print("ranked.json: not an array — aborting", file=sys.stderr)
        return 1

    cleared = 0
    listings_modified = 0
    for li in data:
        if not isinstance(li, dict):
            continue
        modified = False
        for f in LLM_TARGET_FIELDS:
            if f in li and li[f] not in (None, [], {}):
                if not args.dry_run:
                    li[f] = None if f != "reasons_to_buy" else []
                cleared += 1
                modified = True
        if modified:
            listings_modified += 1

    print(f"ranked.json: {len(data)} listings, "
          f"{listings_modified} listings touched, {cleared} fields cleared")
    if args.dry_run:
        print("  [dry-run] would write the cleared file back")
        return 0

    ranked.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print("  written")
    print(
        "\nNext step: run `python -m automation.run` to re-enrich.\n"
        "Approximate cost: ~$10 in DeepSeek tokens, ~15 min wall-clock."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
