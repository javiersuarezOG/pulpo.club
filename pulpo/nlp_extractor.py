"""
PRD §FR-2 — shared NLP keyword extractor.

Reads `nlp_keywords/{field}.json` files at startup, compiles regex patterns
once, and applies them per-listing across `title + description + location_text`.

Fields populated (all bool): has_water, has_power, has_paved_access,
has_ocean_view, has_mountain_view, has_water_body, is_flat, is_beachfront.

Negation handling (per PRD §FR-2.4 — only `is_flat` declares it today):
when a positive match overlaps with a negative pattern within a small
window, the match is suppressed. Implementation is a simple text-distance
check on the same blob — good enough for keyword-style extraction.

Schema deviation: PRD §FR-2.5 calls for YAML files. We use JSON to avoid
adding PyYAML as a dependency. Same structure, same intent. Migrate to
YAML if/when more deps are needed anyway.

Public API:
    from pulpo.nlp_extractor import extract, load_dictionaries
    dicts = load_dictionaries()
    extract(listing, dicts)   # mutates listing in-place

CLI:
    python3 -m pulpo.nlp_extractor --check web/data/ranked.json
        Run extractor over an existing ranked.json and print per-field
        population deltas vs. what's currently in the file. Useful when
        tuning a keyword dictionary.
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
KEYWORDS_DIR = REPO / "nlp_keywords"

# Negation suppression window (chars). When a positive hit lands within
# NEGATION_WINDOW chars of a negative pattern hit, suppress. PRD §FR-2.4
# specifies a "3-word window"; we use ~25 chars as a robust proxy that
# doesn't require word-tokenizing every match site.
NEGATION_WINDOW = 25


@dataclass
class CompiledDict:
    field:    str
    type_:    str          # "boolean" | "boolean_with_negation"
    positive: re.Pattern
    negative: re.Pattern | None


def load_dictionaries(base: Path = KEYWORDS_DIR) -> list[CompiledDict]:
    """Read all *.json files in nlp_keywords/, compile their regexes."""
    if not base.exists():
        return []
    out: list[CompiledDict] = []
    for path in sorted(base.glob("*.json")):
        try:
            spec = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            print(f"[nlp_extractor] WARN: bad JSON in {path}: {e}", file=sys.stderr)
            continue
        field    = spec.get("field") or path.stem
        type_    = spec.get("type") or "boolean"
        pos      = spec.get("positive") or []
        neg      = spec.get("negative") or []
        if not pos:
            continue
        pos_rx   = re.compile("|".join(pos), re.IGNORECASE)
        neg_rx   = re.compile("|".join(neg), re.IGNORECASE) if neg else None
        out.append(CompiledDict(field=field, type_=type_,
                                positive=pos_rx, negative=neg_rx))
    return out


def _text_blob(li: Any) -> str:
    """Concatenate searchable text from a Listing or dict."""
    def g(name: str) -> str:
        v = li.get(name) if isinstance(li, dict) else getattr(li, name, "")
        return str(v or "")
    return " ".join([
        g("title"),
        g("description"),
        g("location_text"),
        g("raw_size_text"),
    ]).lower()


def _is_match_negated(blob: str, match_start: int, match_end: int,
                      neg_rx: re.Pattern) -> bool:
    """True if any negative pattern hits within NEGATION_WINDOW of the positive."""
    lo = max(0, match_start - NEGATION_WINDOW)
    hi = min(len(blob), match_end + NEGATION_WINDOW)
    return bool(neg_rx.search(blob[lo:hi]))


def _has_field(li: Any, field: str) -> bool:
    """Check whether a listing object/dict actually has the field."""
    if isinstance(li, dict):
        return field in li
    return hasattr(li, field)


def _set_field(li: Any, field: str, value: bool) -> None:
    if isinstance(li, dict):
        li[field] = value
    else:
        setattr(li, field, value)


def _evaluate_field(blob: str, cd: CompiledDict) -> bool:
    """Return True iff any positive matches that isn't negated."""
    if not blob:
        return False
    for m in cd.positive.finditer(blob):
        if cd.type_ == "boolean_with_negation" and cd.negative is not None:
            if _is_match_negated(blob, m.start(), m.end(), cd.negative):
                continue
        # Even for plain "boolean" type, honor negative patterns if declared
        # at the global blob level (cheap defense against "no agua" → has_water).
        if cd.negative is not None and cd.type_ == "boolean":
            if _is_match_negated(blob, m.start(), m.end(), cd.negative):
                continue
        return True
    return False


def extract(listing: Any, dicts: list[CompiledDict]) -> dict[str, bool]:
    """Run all dictionaries against the listing, set fields, return what changed.

    Returns a dict {field: new_value} for fields whose computed value is True.
    Existing per-scraper True values are preserved (NLP only flips False→True).
    """
    blob = _text_blob(listing)
    if not blob.strip():
        return {}

    changes: dict[str, bool] = {}
    for cd in dicts:
        if not _has_field(listing, cd.field):
            continue
        # Don't override an existing True from the scraper — only fill False→True
        current = listing.get(cd.field) if isinstance(listing, dict) else getattr(listing, cd.field, False)
        if current is True:
            continue
        if _evaluate_field(blob, cd):
            _set_field(listing, cd.field, True)
            changes[cd.field] = True
    return changes


# ── CLI / report ─────────────────────────────────────────────────────────

def cmd_check(input_path: Path) -> int:
    """Run extractor over an existing ranked.json; print per-field population deltas."""
    if not input_path.exists():
        print(f"ERROR: {input_path} not found", file=sys.stderr)
        return 1
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        print(f"ERROR: {input_path} is not a non-empty list", file=sys.stderr)
        return 1

    dicts = load_dictionaries()
    print(f"loaded {len(dicts)} keyword dictionaries from {KEYWORDS_DIR}")
    print(f"input:  {input_path.name}  ({len(data)} records)\n")

    print(f"{'field':<22} {'before':>8} {'after':>8} {'delta':>8} {'pct':>7}")
    print("-" * 60)
    n = len(data)
    for cd in dicts:
        before = sum(1 for r in data if r.get(cd.field) is True)
        # Apply on a copy to count "after"
        after = 0
        for r in data:
            tmp = dict(r)
            if not _has_field(tmp, cd.field):
                tmp[cd.field] = False
            extract(tmp, [cd])
            if tmp.get(cd.field) is True:
                after += 1
        delta = after - before
        pct   = 100 * after / n if n else 0
        print(f"{cd.field:<22} {before:>8} {after:>8} {delta:>+8} {pct:>6.1f}%")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="PRD §FR-2 NLP keyword extractor")
    p.add_argument("--check", type=Path,
                   help="path to ranked.json — preview population deltas")
    args = p.parse_args()
    if args.check:
        return cmd_check(args.check)
    return cmd_check(REPO / "web" / "data" / "ranked.json")


if __name__ == "__main__":
    sys.exit(main())
