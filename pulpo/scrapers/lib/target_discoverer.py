"""Read the source's own "X listings" UI claim.

The "stated number" feedback loop borrowed from the events-discovery
playbook (`~/.claude/plans/i-guess-we-can-fuzzy-swan.md`). Each scraper
parses the source's own catalog-count UI ("Mostrando 942 lotes...",
"Showing 1,247 results...") and uses it as the COVERAGE DENOMINATOR.
The dev loop is:

  1. Run scraper; observe coverage_ratio_vs_discovered.
  2. If < 0.8: bump MAX_PAGES, fix pagination edge case, escalate transport.
  3. Re-run until ratio >= 0.8.
  4. Merge.

Post-merge, regressions on coverage_ratio_vs_discovered are a leading
indicator that the source changed its layout (early-warning vs the
watchdog's median-based brownout which fires only after several nights
of drift).

The discoverer is regex-based. Each scraper supplies its own pattern
matching the source's wording. Common patterns:

- Spanish: ``r"(\\d[\\d,.]*)\\s+(?:Lotes|Casas|Apartamentos|propiedades|inmuebles)"``
- English: ``r"(\\d[\\d,.]*)\\s+(?:listings|properties|results)\\s+(?:found|available)"``
- Numeric-after-keyword: ``r"Total[:\\s]+(\\d[\\d,.]*)"``

Returns None on parse failure / pattern miss — never raises. Callers
treat None as "unknown target" (the coverage_pct_vs_discovered field
in kpi_dashboard becomes None for that source until the regex is fixed).
"""
from __future__ import annotations

import re
from typing import Iterable, Optional, Union


PatternLike = Union[str, re.Pattern]


def _to_pattern(p: PatternLike) -> re.Pattern:
    if isinstance(p, re.Pattern):
        return p
    return re.compile(p, re.IGNORECASE)


def discover_target(
    html: str,
    patterns: Union[PatternLike, Iterable[PatternLike]],
) -> Optional[int]:
    """Parse the source's UI listing count from `html`.

    Args:
        html: page body as a string.
        patterns: either a single regex (string or compiled) or an iterable
            of patterns to try in order. First pattern matching a numeric
            capture group wins. Patterns must have at least one capture
            group; the first group is parsed as an int (commas / periods
            stripped).

    Returns the parsed integer or None on miss.
    """
    if not html:
        return None
    if isinstance(patterns, (str, re.Pattern)):
        patterns_iter: Iterable[PatternLike] = [patterns]
    else:
        patterns_iter = patterns
    for raw in patterns_iter:
        pat = _to_pattern(raw)
        for match in pat.finditer(html):
            if not match.groups():
                continue
            raw_num = match.group(1) or ""
            cleaned = re.sub(r"[,.\s]", "", raw_num)
            if not cleaned.isdigit():
                continue
            try:
                return int(cleaned)
            except ValueError:
                continue
    return None
