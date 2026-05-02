"""
Development / gated-community detection for pulpo.club land listings.

Add new developments to KNOWN_DEVELOPMENTS as they are identified.
Match is case-insensitive, partial-word matching applied via \b word
boundaries where appropriate.

Each entry: (canonical_name, compiled_regex).
"""
from __future__ import annotations
import re
from typing import Optional

# ── Generic indicators ────────────────────────────────────────────────────────
# Any match sets is_in_development=True with development_name left as None
# (unless a specific name also matches below).
_GENERIC_DEV_RE = re.compile(
    r"\b(comunidad\s+cerrada|condominio|residencial|fraccionamiento"
    r"|lotificaci[oó]n|subdivision|gated\s+community)\b",
    re.IGNORECASE,
)

# ── Known development names ───────────────────────────────────────────────────
# Order matters: more specific patterns first (Surf City 1 before Surf City).
KNOWN_DEVELOPMENTS: list[tuple[str, re.Pattern[str]]] = [
    # Specific named projects first (alphabetical within tier so order is predictable).
    # Surf City N variants before generic "Surf City" — more specific wins.
    ("Canarias",          re.compile(r"\bcanarias\b",                 re.IGNORECASE)),
    ("Las Luces",         re.compile(r"\blas\s+luces\b",              re.IGNORECASE)),
    ("Atami",             re.compile(r"\batami\b",                    re.IGNORECASE)),
    ("Surf City 1",       re.compile(r"\bsurf\s*city\s*1\b",          re.IGNORECASE)),
    ("Surf City 2",       re.compile(r"\bsurf\s*city\s*2\b",          re.IGNORECASE)),
    ("Surf City",         re.compile(r"\bsurf\s*city\b",              re.IGNORECASE)),
    ("San Blas",          re.compile(r"\bsan\s+blas\b",               re.IGNORECASE)),
    ("Solymar",           re.compile(r"\bsolymar\b",                  re.IGNORECASE)),
    ("El Cortijo",        re.compile(r"\bel\s+cortijo\b",             re.IGNORECASE)),
    ("Mirador del Mar",   re.compile(r"\bmirador\s+del\s+mar\b",      re.IGNORECASE)),
    ("Vistas Panorámicas",re.compile(r"\bvistas\s+panor[aá]micas\b",  re.IGNORECASE)),
]


def detect_development(title: str, description: str = "") -> tuple[bool, Optional[str]]:
    """Return (is_in_development, development_name | None).

    Checks title and description, case-insensitive.  Specific known names
    take priority and populate development_name; generic patterns (condominio,
    residencial, …) set the flag without a named match.
    """
    text = (title or "") + " " + (description or "")

    # Pass 1 — specific known developments (first match wins)
    for name, pattern in KNOWN_DEVELOPMENTS:
        if pattern.search(text):
            return True, name

    # Pass 2 — generic indicators
    if _GENERIC_DEV_RE.search(text):
        return True, None

    return False, None
