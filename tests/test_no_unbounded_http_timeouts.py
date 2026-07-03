"""Guardrail: ban bare-float httpx timeouts in the fetch hot path.

Born from the 2026-06-13 nightly freeze (postmortem: bug-postmortem-nightly-
freeze-tfull). A bare-float ``httpx.get(url, timeout=8.0)`` sets the
*between-bytes read* timer, which resets on every byte — so an on-demand CDN
(Cloudinary t_full) that dribbles bytes while generating a derivative hangs
the call FAR past the nominal timeout, stuck in ssl.read. Three call sites
hung this way and froze the nightly for a multi-day stretch.

The fix everywhere is an explicit ``httpx.Timeout(connect=, read=, write=,
pool=)`` so every phase is bounded. This test fails the build if a bare
numeric ``timeout=`` is passed to an httpx verb in the scrape/photo/pipeline
hot path. Legitimate exceptions carry ``# bounded-exempt: <reason>``.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The SCRAPE/PHOTO fetch hot path — where on-demand-CDN dribble hangs live.
# Deliberately NOT automation/newsletter/: those are transactional Clerk-API
# calls (well-behaved JSON, not dribbling derivative CDNs) and editing them
# trips the newsletter TEMPLATE_VERSION guard for no resilience gain.
SCAN_DIRS = ["pulpo/scrapers"]
SCAN_FILES = ["automation/run.py", "automation/aesthetic_vision.py"]

_HTTPX_VERB = re.compile(r"\bhttpx\s*\.\s*(get|head|post|put|patch|stream|request)\b")
# bare numeric timeout (float/int), NOT httpx.Timeout(...)
_BARE_TIMEOUT_NUMERIC = re.compile(r"\btimeout\s*=\s*\d+(?:\.\d+)?\b")
_EXEMPT = re.compile(r"#\s*bounded-exempt:")


def _py_files():
    for d in SCAN_DIRS:
        base = REPO / d
        if base.exists():
            yield from sorted(base.rglob("*.py"))
    for f in SCAN_FILES:
        p = REPO / f
        if p.exists():
            yield p


def test_no_bare_float_httpx_timeouts_in_hot_path():
    offenders: list[str] = []
    for path in _py_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if not _HTTPX_VERB.search(text):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if _EXEMPT.search(line):
                continue
            # Flag only when an httpx verb AND a bare numeric timeout are on the
            # same line — avoids false hits on unrelated timeout= kwargs and on
            # httpx.Timeout(...) (which contains digits but not `timeout=<num>`).
            if _HTTPX_VERB.search(line) and _BARE_TIMEOUT_NUMERIC.search(line):
                offenders.append(f"{path.relative_to(REPO)}:{i}: {line.strip()}")

    assert not offenders, (
        "Bare-float httpx timeout(s) in the fetch hot path. These do NOT bound a "
        "dribbling on-demand-CDN response (froze the nightly 2026-06-13; see "
        "bug-postmortem-nightly-freeze-tfull). Use "
        "httpx.Timeout(connect=, read=, write=, pool=). If a call genuinely "
        "doesn't need it, add '# bounded-exempt: <reason>' on the line.\n  "
        + "\n  ".join(offenders)
    )
