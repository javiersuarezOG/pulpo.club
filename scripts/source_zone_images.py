"""source_zone_images.py — download free, license-clear candidate establishing
photos of a zone from Wikimedia Commons, for human/agent visual verification.

This is the sourcing half of the curated zone-image library (ig_zone_images).
It does NOT decide anything: it fetches candidates + their license/attribution
so a reviewer can LOOK at them and pick the one that actually shows the place
and is beautiful. Wikimedia Commons is the source because its photos are real,
geotagged, and CC-licensed (unlike generic stock) — no API key needed.

Only landscape, decent-resolution, acceptably-licensed images are downloaded.
Acceptable licenses: CC0, Public Domain, CC BY, CC BY-SA (share-alike is
flagged in the manifest so the reviewer can prefer non-SA).

Usage:
    python3 scripts/source_zone_images.py --zones el-tunco,el-zonte --out /tmp/z
    python3 scripts/source_zone_images.py --zones-file zones.txt --out /tmp/z --per 3

Writes <out>/<zone>__<i>.jpg + <out>/manifest.json. The manifest is the input
to a verification step (a human or an agent Reads the jpgs and picks).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import urllib.parse
import urllib.request

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "PulpoClub/1.0 (javier@suarez.ventures) zone-image-sourcing"}
OK_LICENSE = ("cc0", "cc-by", "cc by", "public domain", "pd")
OK_LICENSE_SA = ("cc-by-sa", "cc by-sa")  # acceptable but share-alike → flagged


def _api(params: dict) -> dict:
    params["format"] = "json"
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _clean(html: str) -> str:
    t = re.sub(r"<[^>]+>", "", html or "")
    t = re.sub(r"&[a-z]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:80]


def _license_ok(lic: str) -> tuple[bool, bool]:
    """(acceptable, is_share_alike)."""
    s = (lic or "").lower()
    if any(k in s for k in OK_LICENSE_SA):
        return True, True
    if any(k in s for k in OK_LICENSE):
        return True, False
    return False, False


def _search_terms(zone: str) -> list[str]:
    name = zone.replace("-", " ")
    return [f"{name} El Salvador", name]


def source_zone(zone: str, out_dir: str, per: int = 3) -> list[dict]:
    from PIL import Image
    cands: list[dict] = []
    seen: set[str] = set()
    for term in _search_terms(zone):
        try:
            sr = _api({"action": "query", "list": "search", "srsearch": term,
                       "srnamespace": "6", "srlimit": "8"})
        except Exception:
            continue
        titles = [x["title"] for x in sr.get("query", {}).get("search", []) if x["title"] not in seen]
        if not titles:
            continue
        info = _api({"action": "query", "titles": "|".join(titles[:8]),
                     "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": "1400"})
        for pg in info.get("query", {}).get("pages", {}).values():
            ii = (pg.get("imageinfo") or [{}])[0]
            if not ii.get("url"):
                continue
            meta = ii.get("extmetadata", {})
            lic = (meta.get("LicenseShortName", {}) or {}).get("value", "")
            ok, sa = _license_ok(lic)
            w, h = ii.get("width", 0), ii.get("height", 0)
            if not ok or w < 900 or h < 600 or w < h:  # landscape + res only
                continue
            title = pg["title"]
            if title in seen:
                continue
            seen.add(title)
            cands.append({
                "zone": zone, "title": title, "thumb": ii.get("thumburl") or ii["url"],
                "full": ii["url"], "license": lic, "share_alike": sa,
                "credit": _clean((meta.get("Artist", {}) or {}).get("value", "")) or "Wikimedia Commons",
                "license_url": ii.get("descriptionurl", ""), "w": w, "h": h,
            })
        if len(cands) >= per:
            break

    os.makedirs(out_dir, exist_ok=True)
    saved: list[dict] = []
    for i, c in enumerate(cands[:per]):
        path = os.path.join(out_dir, f"{zone}__{i}.jpg")
        try:
            req = urllib.request.Request(c["thumb"], headers=UA)
            with urllib.request.urlopen(req, timeout=40) as r:
                im = Image.open(io.BytesIO(r.read())).convert("RGB")
            if im.width > 1000:
                im = im.resize((1000, round(im.height * 1000 / im.width)))
            im.save(path, "JPEG", quality=80)
            c["local"] = path
            saved.append(c)
        except Exception:
            continue
    return saved


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zones", default="", help="comma-separated zone slugs")
    ap.add_argument("--zones-file", default="", help="file with one zone slug per line")
    ap.add_argument("--out", required=True)
    ap.add_argument("--per", type=int, default=3)
    args = ap.parse_args()

    zones = [z.strip() for z in args.zones.split(",") if z.strip()]
    if args.zones_file:
        with open(args.zones_file) as f:
            zones += [ln.strip() for ln in f if ln.strip()]

    manifest: dict[str, list[dict]] = {}
    for z in zones:
        got = source_zone(z, args.out, args.per)
        manifest[z] = got
        flags = ",".join((c["license"] + ("*SA" if c["share_alike"] else "")) for c in got)
        print(f"{z:26} {len(got)} candidate(s): {flags or '— none'}")
    with open(os.path.join(args.out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"\nwrote {os.path.join(args.out, 'manifest.json')} — now LOOK at the jpgs and pick.")


if __name__ == "__main__":
    main()
