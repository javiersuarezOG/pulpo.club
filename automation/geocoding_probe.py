"""
PRD WS2 — Day 4 — Geocoding extraction probe.

Fetches a sample of listing pages and measures how many can be geocoded
WITHOUT a paid API call, by parsing HTML for embedded coordinates first.
Per PRD §FR-5.2 the priority chain is:

  1. Embedded map coordinates (Google Maps URL / iframe src / `data-lat`)
  2. Structured metadata (`og:latitude`, Schema.org GeoCoordinates JSON-LD)
  3. Mapbox geocoding API (paid fallback)

This probe answers: at production scale, what fraction of listings would
hit (1) or (2) and never need a Mapbox call? PRD §10 caps geocoding spend
at the Mapbox 100k-req/month free tier — if the steps-1-and-2 hit rate is
high (>50%), the budget never gets close. If low (<10%), the cost-cap math
needs re-baselining.

    python3 automation/geocoding_probe.py
        Live HTTP probe of 50 listings (default). Polite 1.5s delay between
        requests. Writes:
            samples/geocoding_probe.csv      — per-listing extraction results
            samples/geocoding_probe.md       — per-source hit-rate summary

    python3 automation/geocoding_probe.py --no-fetch
        Skips HTTP, just reports what would be probed. Useful in CI.
"""
from __future__ import annotations
import argparse
import csv
import json
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
DEFAULT_INPUT   = REPO / "web" / "data" / "ranked.json"
DEFAULT_OUT_CSV = REPO / "samples" / "geocoding_probe.csv"
DEFAULT_OUT_MD  = REPO / "samples" / "geocoding_probe.md"

DEFAULT_N = 50
DEFAULT_DELAY_S = 1.5
USER_AGENT = ("PulpoClubGeocodeProbe/0.1 "
              "(+https://pulpo.club; feasibility study, not a crawler)")


# ── HTML extraction patterns ──────────────────────────────────────────────
# Order matters — first hit wins, per PRD §FR-5.2.

# 1a. Google Maps URL with lat,lng query: maps.google.com/?q=13.5,-89.7 etc.
RX_GMAPS_Q = re.compile(
    r'https?://(?:www\.)?(?:maps\.)?google\.[a-z.]+/[^"\']*?[?&!]'
    r'(?:q|ll|center|sll|destination|origin)=([+-]?\d{1,2}\.\d+)[,%]([+-]?\d{1,3}\.\d+)',
    re.IGNORECASE,
)

# 1b. Google Maps iframe src with !3dLAT!4dLNG (the modern embed format)
RX_GMAPS_3D4D = re.compile(r'!3d([+-]?\d{1,2}\.\d+)!4d([+-]?\d{1,3}\.\d+)')

# 1c. data-lat / data-lng on any element
RX_DATA_LATLNG = re.compile(
    r'data-lat(?:itude)?=["\']([+-]?\d{1,2}\.\d+)["\'][^>]*?'
    r'data-lng=["\']([+-]?\d{1,3}\.\d+)["\']|'
    r'data-lng=["\']([+-]?\d{1,3}\.\d+)["\'][^>]*?'
    r'data-lat(?:itude)?=["\']([+-]?\d{1,2}\.\d+)["\']',
    re.IGNORECASE,
)

# 2a. og:latitude / og:longitude meta tags
RX_OG_LAT = re.compile(
    r'<meta[^>]+property=["\']og:latitude["\'][^>]+content=["\']([+-]?\d{1,2}\.\d+)["\']',
    re.IGNORECASE,
)
RX_OG_LNG = re.compile(
    r'<meta[^>]+property=["\']og:longitude["\'][^>]+content=["\']([+-]?\d{1,3}\.\d+)["\']',
    re.IGNORECASE,
)

# 2b. Schema.org GeoCoordinates JSON-LD
RX_JSONLD = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


# El Salvador bounding box (rough): lat 13.0-14.6, lng -90.5 to -87.6
def _looks_like_sv(lat: float, lng: float) -> bool:
    return 13.0 <= lat <= 14.6 and -90.6 <= lng <= -87.6


@dataclass
class ProbeResult:
    listing_id:  str
    source:      str
    url:         str
    http_status: Optional[int] = None
    http_error:  Optional[str] = None
    html_bytes:  Optional[int] = None
    method:      Optional[str] = None     # which extraction tier hit
    lat:         Optional[float] = None
    lng:         Optional[float] = None
    sv_plausible: Optional[bool] = None
    notes:       list[str] = field(default_factory=list)


def _try_gmaps_q(html: str) -> Optional[tuple[float, float, str]]:
    m = RX_GMAPS_Q.search(html)
    if m:
        try:
            return float(m.group(1)), float(m.group(2)), "gmaps_q_param"
        except ValueError:
            return None
    return None


def _try_gmaps_3d4d(html: str) -> Optional[tuple[float, float, str]]:
    m = RX_GMAPS_3D4D.search(html)
    if m:
        try:
            return float(m.group(1)), float(m.group(2)), "gmaps_3d4d_embed"
        except ValueError:
            return None
    return None


def _try_data_attrs(html: str) -> Optional[tuple[float, float, str]]:
    m = RX_DATA_LATLNG.search(html)
    if m:
        # Two alternation branches; pick whichever matched
        if m.group(1) and m.group(2):
            try:
                return float(m.group(1)), float(m.group(2)), "data_lat_lng_attrs"
            except ValueError:
                return None
        if m.group(3) and m.group(4):
            try:
                return float(m.group(4)), float(m.group(3)), "data_lat_lng_attrs"
            except ValueError:
                return None
    return None


def _try_og_meta(html: str) -> Optional[tuple[float, float, str]]:
    lat = RX_OG_LAT.search(html)
    lng = RX_OG_LNG.search(html)
    if lat and lng:
        try:
            return float(lat.group(1)), float(lng.group(1)), "og_meta"
        except ValueError:
            return None
    return None


def _try_jsonld(html: str) -> Optional[tuple[float, float, str]]:
    for m in RX_JSONLD.finditer(html):
        body = m.group(1).strip()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        # JSON-LD can be an object, list, or @graph
        candidates = [data] if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for c in candidates:
            if not isinstance(c, dict):
                continue
            raw_graph = c.get("@graph")
            graph: list = raw_graph if isinstance(raw_graph, list) else []
            for sub in [c, *graph]:
                if not isinstance(sub, dict):
                    continue
                geo = sub.get("geo") or {}
                if isinstance(geo, dict) and "latitude" in geo and "longitude" in geo:
                    try:
                        return float(geo["latitude"]), float(geo["longitude"]), "jsonld_geo"
                    except (TypeError, ValueError):
                        pass
                if "latitude" in sub and "longitude" in sub:
                    try:
                        return float(sub["latitude"]), float(sub["longitude"]), "jsonld_root"
                    except (TypeError, ValueError):
                        pass
    return None


_EXTRACTORS = [
    _try_gmaps_q,
    _try_gmaps_3d4d,
    _try_data_attrs,
    _try_og_meta,
    _try_jsonld,
]


def _extract_coords(html: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    for fn in _EXTRACTORS:
        result = fn(html)
        if result:
            lat, lng, method = result
            return lat, lng, method
    return None, None, None


def _stratified_sample(data: list[dict], k: int, seed: int) -> list[dict]:
    """Same logic as precision_goldset — reserve 1 per source then random-fill."""
    by_source: dict[str, list[dict]] = {}
    for li in data:
        src = li.get("source") or "unknown"
        by_source.setdefault(src, []).append(li)

    rng = random.Random(seed)
    reserved: list[dict] = []
    for src in sorted(by_source):
        items = by_source[src]
        if items:
            reserved.append(rng.choice(items))

    pool = [li for li in data if li not in reserved]
    rng.shuffle(pool)
    return (reserved + pool[: max(0, k - len(reserved))])[:k]


def _probe_listing(li: dict, fetch: bool, timeout_s: float) -> ProbeResult:
    res = ProbeResult(
        listing_id = f"{li.get('source')}|{li.get('source_id')}",
        source     = li.get("source") or "?",
        url        = li.get("url") or "",
    )
    if not res.url or not res.url.startswith("http"):
        res.notes.append("no usable url")
        return res

    if not fetch:
        res.notes.append("fetch skipped (--no-fetch)")
        return res

    try:
        import httpx
    except ImportError:
        res.http_error = "httpx not installed"
        return res

    try:
        r = httpx.get(res.url, timeout=timeout_s, follow_redirects=True,
                      headers={"User-Agent": USER_AGENT})
        res.http_status = r.status_code
        if r.status_code != 200:
            res.notes.append("non-200")
            return res
        html = r.text
        res.html_bytes = len(html)
    except Exception as e:
        res.http_error = repr(e)[:200]
        return res

    lat, lng, method = _extract_coords(html)
    if lat is not None and lng is not None:
        res.lat, res.lng, res.method = lat, lng, method
        res.sv_plausible = _looks_like_sv(lat, lng)
        if not res.sv_plausible:
            res.notes.append("coords outside El Salvador bbox")
    return res


def _summary_md(results: list[ProbeResult], n_total: int) -> str:
    lines: list[str] = []
    lines.append("# Geocoding Extraction Probe")
    lines.append("")
    lines.append(f"Sampled **{len(results)}** of {n_total} catalog listings  ")
    lines.append("Goal: measure free-tier (HTML-only) geocoding hit rate per "
                 "PRD §FR-5.2 priority chain.  ")
    lines.append("")

    fetched = [r for r in results if r.http_status is not None]
    extracted = [r for r in fetched if r.method]
    sv_ok = [r for r in extracted if r.sv_plausible]

    lines.append("## Headline")
    lines.append("")
    if results:
        lines.append(f"- HTTP fetch success: **{len(fetched)} / {len(results)}** "
                     f"({100 * len(fetched) / len(results):.0f}%)")
    if fetched:
        lines.append(f"- Coordinates extracted (any method): **{len(extracted)} / {len(fetched)}** "
                     f"({100 * len(extracted) / len(fetched):.0f}% of fetched)")
        lines.append(f"- Plausible SV coords (within bbox): **{len(sv_ok)} / {len(fetched)}** "
                     f"({100 * len(sv_ok) / len(fetched):.0f}% of fetched)")
    lines.append("")

    # Per-source breakdown
    lines.append("## Per-source hit rate")
    lines.append("")
    lines.append("| Source | n | Fetched | Extracted | SV-plausible |")
    lines.append("|---|---:|---:|---:|---:|")
    by_source: dict[str, list[ProbeResult]] = {}
    for r in results:
        by_source.setdefault(r.source, []).append(r)
    for src in sorted(by_source):
        rs = by_source[src]
        f  = sum(1 for r in rs if r.http_status is not None)
        e  = sum(1 for r in rs if r.method)
        sv = sum(1 for r in rs if r.sv_plausible)
        lines.append(f"| `{src}` | {len(rs)} | {f} | {e} | {sv} |")
    lines.append("")

    # Method distribution
    lines.append("## Extraction method (priority order)")
    lines.append("")
    lines.append("| Method | Hits |")
    lines.append("|---|---:|")
    by_method: dict[str, int] = {}
    for r in extracted:
        by_method[r.method or "?"] = by_method.get(r.method or "?", 0) + 1
    for m in ("gmaps_q_param", "gmaps_3d4d_embed", "data_lat_lng_attrs",
              "og_meta", "jsonld_geo", "jsonld_root"):
        lines.append(f"| `{m}` | {by_method.get(m, 0)} |")
    lines.append("")

    # Mapbox cost projection at full scale
    lines.append("## Cost implications")
    lines.append("")
    if fetched:
        free_rate = len(extracted) / len(fetched)
        miss_rate = 1 - free_rate
        full_misses = round(n_total * miss_rate)
        # Mapbox: 100k free/month, then $0.75/1k
        within_free = full_misses <= 100_000
        lines.append(f"- HTML free-tier hit rate: **{free_rate*100:.0f}%**")
        lines.append(f"- At full catalog ({n_total}), Mapbox API calls per refresh: "
                     f"~**{full_misses}**")
        lines.append(f"- Mapbox free tier (100k/mo): "
                     f"**{'within budget' if within_free else 'OVER BUDGET'}**")
        if not within_free:
            extra = full_misses - 100_000
            cost = extra * 0.75 / 1_000
            lines.append(f"- Excess: {extra} requests × $0.75/1k = ${cost:.2f}/mo")
    lines.append("")

    # Failure mode breakdown
    failures = [r for r in results if r.http_error or
                (r.http_status is not None and r.http_status != 200)]
    if failures:
        lines.append("## Failures")
        lines.append("")
        lines.append("| Source | URL | Error / Status |")
        lines.append("|---|---|---|")
        for r in failures[:15]:
            err = r.http_error or f"HTTP {r.http_status}"
            url = (r.url or "")[:80]
            lines.append(f"| `{r.source}` | {url} | {err[:80]} |")
        if len(failures) > 15:
            lines.append(f"| … | … | (+{len(failures)-15} more) |")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="PRD WS2 geocoding-extraction probe")
    p.add_argument("--input",  type=Path, default=DEFAULT_INPUT)
    p.add_argument("--n",      type=int,  default=DEFAULT_N)
    p.add_argument("--seed",   type=int,  default=20260504)
    p.add_argument("--delay",  type=float, default=DEFAULT_DELAY_S,
                   help="seconds between fetches (be polite)")
    p.add_argument("--timeout", type=float, default=8.0,
                   help="HTTP request timeout (seconds)")
    p.add_argument("--no-fetch", action="store_true",
                   help="skip HTTP entirely, just report what would be probed")
    p.add_argument("--out-csv", type=Path, default=DEFAULT_OUT_CSV)
    p.add_argument("--out-md",  type=Path, default=DEFAULT_OUT_MD)
    args = p.parse_args()

    if not args.input.exists():
        print(f"ERROR: {args.input} not found", file=sys.stderr)
        return 1
    data = json.loads(args.input.read_text(encoding="utf-8"))
    if not data:
        print("ERROR: ranked.json is empty", file=sys.stderr)
        return 1

    sample = _stratified_sample(data, args.n, args.seed)
    print(f"[geocode] sampling {len(sample)} listings, fetch={not args.no_fetch}")

    results: list[ProbeResult] = []
    for i, li in enumerate(sample, 1):
        r = _probe_listing(li, fetch=not args.no_fetch, timeout_s=args.timeout)
        results.append(r)
        marker = (r.method or
                  (f"http_{r.http_status}" if r.http_status else
                   ("err" if r.http_error else "skip")))
        print(f"[geocode] {i:>3}/{len(sample)} {r.source:<20} {marker}")
        if not args.no_fetch and i < len(sample):
            time.sleep(args.delay)

    # Write outputs
    args.out_csv.parent.mkdir(parents=True, exist_ok=True)
    with args.out_csv.open("w", newline="", encoding="utf-8") as fh:
        cols = ["listing_id", "source", "url", "http_status", "http_error",
                "html_bytes", "method", "lat", "lng", "sv_plausible", "notes"]
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in results:
            d = asdict(r)
            d["notes"] = "; ".join(d.get("notes") or [])
            w.writerow(d)

    args.out_md.write_text(_summary_md(results, len(data)), encoding="utf-8")

    fetched = sum(1 for r in results if r.http_status is not None)
    hits    = sum(1 for r in results if r.method)
    sv_ok   = sum(1 for r in results if r.sv_plausible)
    print(f"[geocode] fetched={fetched} extracted={hits} sv_plausible={sv_ok} "
          f"of {len(results)} sampled")
    print(f"[geocode] wrote {args.out_csv} and {args.out_md}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
