"""
Selector calibration harness.

Why this exists: every scraper module declares CSS selectors for the title,
price, area, location, and description on a detail page. Those selectors are
fragile — themes change, plugins update, sites swap stacks. This script lets
you point at a saved HTML detail page (or a list of them) and instantly see
which selectors hit and which miss, without running the full pipeline.

Usage:
    # Single page
    python3 automation/calibrate.py --source goodlife --html path/to/page.html

    # Whole directory of saved pages (each .html runs once)
    python3 automation/calibrate.py --source goodlife --dir samples/calibration/goodlife/

    # All sources, all calibration samples
    python3 automation/calibrate.py --all

Saving a calibration sample:
    1. Open one detail page in a browser (e.g. https://goodlifeelsalvador.com/property/some-lot/)
    2. Right-click → "Save Page As" → "Webpage, HTML Only"
    3. Drop the .html into samples/calibration/<source>/
    4. Re-run this script — green = parsed, red = empty selector

Output:
    field         | selector                                  | matched | preview
    title         | h1.entry-title, h1.property-title         | YES     | "5 manzanas El Cuco — beachfront…"
    price         | .property-price, .price, span.amount      | NO      | (no node found)
    area          | .property-area, .lot-size, li.area        | YES     | "5 manzanas (34,945 m²)"
    location      | .property-location, .location             | YES     | "El Cuco, Chirilagua, San Miguel"
    description   | .entry-content, .property-description     | YES     | "Beachfront parcel with paved access…"
    RAW HEAD     <head> tag preview (first 200 chars)

Per-source target: ≥95% field coverage across ≥3 saved pages before flipping
PULPO_OFFLINE=0 in production cron.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# Lazy import so `--help` works even if no parser is installed yet.
# Two backends supported: selectolax (fast, preferred) and BeautifulSoup
# (slower, but pre-installed in many sandboxes). Whichever is available
# gets wrapped in a uniform shim with .css() and .css_first() methods so
# the rest of this script doesn't care which one it's talking to.
_PARSER = None  # ("selectolax" | "bs4", parse_callable)


class _Bs4Tree:
    """selectolax-shaped facade over a BeautifulSoup tree."""
    def __init__(self, soup):
        self._s = soup

    def css(self, sel):
        return [_Bs4Node(n) for n in self._s.select(sel)]

    def css_first(self, sel):
        n = self._s.select_one(sel)
        return _Bs4Node(n) if n is not None else None


class _Bs4Node:
    def __init__(self, node):
        self._n = node

    def text(self, strip=True):
        t = self._n.get_text(separator=" ", strip=False)
        return t.strip() if strip else t

    @property
    def attributes(self):
        return self._n.attrs


def _ensure_parser():
    global _PARSER
    if _PARSER is not None:
        return
    try:
        from selectolax.parser import HTMLParser as _HP
        _PARSER = ("selectolax", lambda h: _HP(h))
        return
    except ImportError:
        pass
    try:
        from bs4 import BeautifulSoup
        # lxml parser preferred; fall back to html.parser if lxml is missing.
        try:
            import lxml  # noqa: F401
            _backend = "lxml"
        except ImportError:
            _backend = "html.parser"
        _PARSER = ("bs4", lambda h: _Bs4Tree(BeautifulSoup(h, _backend)))
        return
    except ImportError:
        pass
    print(
        "ERROR: no HTML parser available. Install selectolax (preferred) or bs4+lxml.\n"
        "  pip install selectolax\n"
        "  pip install beautifulsoup4 lxml",
        file=sys.stderr,
    )
    sys.exit(2)


def _parse(html: str):
    return _PARSER[1](html)

from pulpo.scrapers import REGISTRY  # noqa: E402

# Map of (label, selector_attribute_name) for parse_detail_page selector audit.
DETAIL_FIELDS = [
    ("title",       "DETAIL_TITLE_SEL"),
    ("price",       "DETAIL_PRICE_SEL"),
    ("area",        "DETAIL_AREA_SEL"),
    ("location",    "DETAIL_LOC_SEL"),
    ("description", "DETAIL_DESC_SEL"),
]
INDEX_FIELDS = [
    ("index card",  "INDEX_CARD_SEL"),
    ("index link",  "INDEX_LINK_SEL"),
]

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"


def _scraper_class(source: str):
    mod = REGISTRY.get(source)
    if not mod:
        raise SystemExit(f"unknown source: {source}. Known: {list(REGISTRY)}")
    # The scraper module exposes a `crawl` function; the class is the only
    # subclass of BaseScraper defined in the module.
    from pulpo.scrapers.base import BaseScraper
    for v in vars(mod).values():
        if isinstance(v, type) and issubclass(v, BaseScraper) and v is not BaseScraper:
            return v
    raise SystemExit(f"no BaseScraper subclass found in pulpo.scrapers.{source}")


def calibrate_file(source: str, html_path: Path, mode: str = "detail") -> dict:
    _ensure_parser()
    cls = _scraper_class(source)
    html = html_path.read_text(encoding="utf-8", errors="replace")
    tree = _parse(html)
    fields = INDEX_FIELDS if mode == "index" else DETAIL_FIELDS

    backend = _PARSER[0]
    print(f"\n{BOLD}=== {source} | {html_path.name} ({mode} page) ==={RESET} {DIM}[{backend}]{RESET}")
    head = tree.css_first("head title")
    if head:
        print(f"{DIM}page title: {head.text(strip=True)[:120]}{RESET}")

    rows = []
    for label, attr in fields:
        sel = getattr(cls, attr, None)
        if sel is None:
            print(f"  {label:<12} | {DIM}<no selector defined>{RESET}")
            continue
        nodes = tree.css(sel) if mode == "index" else [tree.css_first(sel)]
        nodes = [n for n in nodes if n is not None]
        matched = bool(nodes)
        preview = ""
        if matched:
            if mode == "index":
                preview = f"{len(nodes)} cards found"
            else:
                preview = nodes[0].text(strip=True)[:80].replace("\n", " ")
        color = GREEN if matched else RED
        flag = "YES" if matched else "NO "
        print(f"  {label:<12} | {DIM}{sel[:48]:<48}{RESET} | {color}{flag}{RESET} | {preview}")
        rows.append({"field": label, "matched": matched, "selector": sel, "preview": preview})

    matched_count = sum(1 for r in rows if r["matched"])
    total = len(rows)
    pct = 100 * matched_count / total if total else 0
    print(f"  {BOLD}coverage: {matched_count}/{total} ({pct:.0f}%){RESET}")
    return {"source": source, "file": str(html_path), "mode": mode, "rows": rows, "coverage_pct": pct}


def calibrate_dir(source: str, base_dir: Path) -> list[dict]:
    if not base_dir.exists():
        print(f"{DIM}(no calibration samples at {base_dir} — skipping){RESET}")
        return []
    results = []
    for html_path in sorted(base_dir.glob("*.html")):
        # Heuristic: filename containing "index" or "search" or "list" -> index page
        mode = "index" if any(k in html_path.stem.lower() for k in ("index", "search", "list")) else "detail"
        results.append(calibrate_file(source, html_path, mode=mode))
    return results


def main(argv=None):
    p = argparse.ArgumentParser(description="Calibrate scraper selectors against saved HTML.")
    p.add_argument("--source", help="goodlife | oceanside | kazu")
    p.add_argument("--html", help="single HTML file to calibrate against")
    p.add_argument("--dir", help="directory of saved HTML files for one source")
    p.add_argument("--all", action="store_true", help="run all sources against samples/calibration/<source>/")
    p.add_argument("--mode", choices=["detail", "index"], default="detail")
    args = p.parse_args(argv)

    if args.all:
        results = []
        for source in REGISTRY.keys():
            base = REPO / "samples" / "calibration" / source
            results.extend(calibrate_dir(source, base))
        if not results:
            print(f"\n{DIM}No calibration samples found yet. To get started:")
            print("  mkdir -p samples/calibration/goodlife")
            print("  # save a detail page to samples/calibration/goodlife/page1.html")
            print(f"  python3 automation/calibrate.py --all{RESET}")
        else:
            avg = sum(r["coverage_pct"] for r in results) / len(results)
            color = GREEN if avg >= 95 else (RED if avg < 60 else "\033[33m")
            print(f"\n{BOLD}Overall coverage: {color}{avg:.1f}%{RESET}{BOLD} across {len(results)} pages{RESET}")
        return 0

    if not args.source:
        p.error("--source is required (or use --all)")
    if args.html:
        calibrate_file(args.source, Path(args.html), mode=args.mode)
    elif args.dir:
        calibrate_dir(args.source, Path(args.dir))
    else:
        # default: try samples/calibration/<source>/
        calibrate_dir(args.source, REPO / "samples" / "calibration" / args.source)
    return 0


if __name__ == "__main__":
    sys.exit(main())
