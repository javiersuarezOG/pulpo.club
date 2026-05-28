#!/usr/bin/env python3
"""Country-hardcode guardrail.

Scans the country-agnostic infrastructure (pulpo/, automation/, web/app/)
for string literals that hardcode a specific country (SV / El Salvador /
non-USD currencies / multi-country regex alternations). These are exactly
the bugs PR #489 fixed — three of them silently dropped every PA listing
in the MC-PA-1 smoke run.

Goal: fail CI when a NEW hardcode is introduced. Existing hits are
either (a) genuinely country-specific code (e.g. the SV-only scrapers
in pulpo/scrapers/ — those sites only serve SV) and live on the
ALLOWED_FILES allowlist, or (b) accepted lurkers tracked elsewhere and
inline-marked with `# multi-country-exempt: <reason>`.

Run locally:
    python scripts/check_country_hardcodes.py

Runs in CI via .github/workflows/ci.yml — exit code 1 fails the job.

Adding a new country (e.g. GT) doesn't require updating this script;
the patterns flag any country *literal*, not specifically PA's.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent


# ── Allowlist: files exempt from scanning entirely ──────────────────────
#
# Each entry is either a relative-path glob (matched with Path.match)
# or a literal relative path. The rule of thumb: a file goes here when
# being SV-specific is its job, not a bug. SV-only scrapers, SV
# manifest, tests that assert SV-flavored behavior, etc.
#
# When adding a country, you'll be ADDING entries here (the new
# country's manifest, any country-specific scrapers) — never removing.
ALLOWED_FILES: tuple[str, ...] = (
    # SV-only source scrapers (single-country sites; their `country = "SV"`
    # class attr and "El Salvador" location fallbacks are correct).
    "pulpo/scrapers/bienesraices.py",
    "pulpo/scrapers/century21.py",
    "pulpo/scrapers/citymax.py",
    "pulpo/scrapers/elagente.py",
    "pulpo/scrapers/essurf.py",
    "pulpo/scrapers/goodlife.py",
    "pulpo/scrapers/nexo.py",
    "pulpo/scrapers/oceanside.py",
    "pulpo/scrapers/realtyelsalvador.py",
    "pulpo/scrapers/remax.py",
    # The country manifest files themselves carry their own code/name.
    "pulpo/countries/sv.json",
    "pulpo/countries/pa.json",
    "web/app/config/countries/sv.json",
    "web/app/config/countries/pa.json",
    # The manifest loader's docstrings and default-fallback to "SV" are
    # documented design choices (active() defaults to SV when env unset).
    "pulpo/countries/__init__.py",
    # The Listing dataclass default — unreachable in practice (normalize.py
    # always overrides) but kept as a defensive fallback. Flagged via
    # inline marker rather than file-level allowlist, so future drift is
    # visible.
    # NOTE: pulpo/models.py is NOT allowlisted; it carries a per-line marker.
    # i18n.jsx legitimately contains "El Salvador" as the SV display name.
    "web/app/i18n.jsx",
    # Legal-entity config: tracks the COMPANY's legal incorporation
    # jurisdiction (NL/ES/SV) — orthogonal to the LISTING active country.
    # Selected by VITE_LEGAL_JURISDICTION, not by PULPO_ACTIVE_COUNTRY.
    "web/app/config/legal-entity.ts",
    # ISO-3166-1 full country list used by the Account profile picker
    # (any user can live anywhere). Not the listing-country logic.
    "web/app/lib/countries.js",
    # Newsletter copy template — "El Salvador" appears in SV-flavored
    # example strings inside docstrings.
    "automation/newsletter/i18n.py",
    # Schema is auto-generated; the generator itself reads from
    # loaded() manifests (no const). The output schema is data, not code.
    "web/data/ranked.schema.json",
)


# ── Patterns to flag ────────────────────────────────────────────────────
#
# Each pattern is a re.compile()-able expression. Match a substring in
# any line of a scanned file (with the per-line exemption marker
# honoured). Patterns describe the SHAPE of a country hardcode — they
# don't need updating when adding a new country, because the bug class
# is the same across countries.
PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    (
        "quoted-SV-literal",
        re.compile(r'(["\'])SV\1'),
    ),
    (
        "quoted-El-Salvador",
        re.compile(r'(["\'])El\s+Salvador\1', re.IGNORECASE),
    ),
    (
        "quoted-el-salvador-slug",
        re.compile(r'(["\'])el[-_]salvador\1', re.IGNORECASE),
    ),
    (
        "quoted-PAB-currency",
        # PAB is a real currency code but Pulpo's pricing layer
        # treats it as at-par USD. Hardcoding "PAB" anywhere besides
        # the validated `_AT_PAR_USD` set is almost certainly a bug.
        re.compile(r'(["\'])PAB\1'),
    ),
    (
        "multi-country-regex-alternation",
        # The exact bug class from PR #489's validation.py: a regex
        # literal that lists multiple country names. Should always
        # come from a dynamic builder, never a string literal.
        re.compile(
            r'guatemala\s*\|\s*honduras|'
            r'panam.*\|\s*m.*xico|'
            r'costa.?rica\s*\|\s*nicaragua',
            re.IGNORECASE,
        ),
    ),
)


# ── Files to scan ───────────────────────────────────────────────────────
#
# Glob patterns relative to repo root. Tight scope: only country-
# agnostic infrastructure. NOT scanned: tests/, docs/, web/data/,
# samples/, scripts/, .github/.
SCAN_GLOBS: tuple[str, ...] = (
    "pulpo/**/*.py",
    "automation/**/*.py",
    "web/app/**/*.ts",
    "web/app/**/*.tsx",
    "web/app/**/*.jsx",
    "web/app/**/*.js",
    "web/app/**/*.mjs",
)


EXEMPT_MARKER = "multi-country-exempt"


def _is_allowed(path: Path) -> bool:
    rel = path.relative_to(REPO).as_posix()
    if rel in ALLOWED_FILES:
        return True
    # Test files legitimately assert country-specific values.
    if rel.endswith(".test.ts") or rel.endswith(".test.tsx") or rel.endswith(".test.js"):
        return True
    return False


def _is_exempt_line(line: str) -> bool:
    return EXEMPT_MARKER in line


_TRIPLE_QUOTE_RE = re.compile(r'"""|\'\'\'')


def _is_comment_line(stripped: str) -> bool:
    return (
        stripped.startswith("#")
        or stripped.startswith("//")
        or stripped.startswith("*")
    )


def _classify_lines(text: str) -> list[bool]:
    """Return a per-line list of `is_code` flags. False means the line
    is a comment or inside a triple-quoted docstring/string. Naive
    state-machine — doesn't handle nested quotes or string-in-comment
    edge cases, but good enough for the codebase's hand-written style.
    """
    is_code: list[bool] = []
    inside_triple = False
    for line in text.splitlines():
        # Count triple-quote occurrences on this line. Even count means
        # the line opens/closes a triple-quote pair on the same line
        # (still includes runtime content). Odd count flips state.
        triples = len(_TRIPLE_QUOTE_RE.findall(line))
        opened_on_this_line = (not inside_triple) and triples >= 1
        if inside_triple:
            # Whole line is inside a docstring/string-literal block.
            is_code.append(False)
            if triples % 2 == 1:
                inside_triple = False
            continue
        # Not inside a triple block at start of line.
        stripped = line.lstrip()
        if _is_comment_line(stripped):
            is_code.append(False)
        elif opened_on_this_line and triples % 2 == 1:
            # Line opens a docstring that continues on later lines.
            is_code.append(False)
            inside_triple = True
        else:
            is_code.append(True)
    return is_code


def scan() -> list[tuple[str, int, str, str]]:
    """Return a list of (path, lineno, pattern_name, line) hits."""
    hits: list[tuple[str, int, str, str]] = []
    seen: set[Path] = set()
    for glob in SCAN_GLOBS:
        for path in REPO.glob(glob):
            if path in seen:
                continue
            seen.add(path)
            if not path.is_file():
                continue
            if _is_allowed(path):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lines = text.splitlines()
            code_flags = _classify_lines(text)
            for i, (line, is_code) in enumerate(
                    zip(lines, code_flags), start=1):
                if not is_code:
                    continue
                if _is_exempt_line(line):
                    continue
                for name, rx in PATTERNS:
                    if rx.search(line):
                        hits.append((
                            path.relative_to(REPO).as_posix(),
                            i,
                            name,
                            line.rstrip(),
                        ))
    return hits


def main() -> int:
    hits = scan()
    if not hits:
        print("country-hardcodes: clean")
        return 0

    print("country-hardcodes: hits found\n")
    for path, lineno, name, line in hits:
        # GitHub Actions annotation format — surfaces as inline review
        # comments on PRs when this runs in CI.
        print(f"::error file={path},line={lineno}::"
              f"{name}: hardcoded country literal")
        print(f"  {path}:{lineno}  [{name}]")
        print(f"    {line}\n")
    print(
        f"\n{len(hits)} hit(s). Fix by reading from "
        "`pulpo.countries.active()` (or `loaded()` for a list-of-codes "
        "schema), OR mark the line with `# multi-country-exempt: "
        "<reason>` if it's a legitimate single-country reference."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
