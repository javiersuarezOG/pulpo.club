"""ig_zone_images.py — the curated per-zone establishing-image library.

The opener slide of every post should be a BEAUTIFUL, REAL image of the actual
zone the listing is in — with the designed typographic hook laid over it. Not
a raw broker land photo (dusty, sometimes watermarked, land-only), and not
generic stock (misleading — a beach that isn't the property's).

The only source that satisfies "real place + beautiful + brand-safe + license-
clear" is a small CURATED library: one stunning, license-verified establishing
shot per zone we operate in (~15-20 zones, sourced once). This module is that
registry. It is deliberately DATA, not scraping — a human vets each image and
its license before it lands here.

Sourcing policy — an entry is valid ONLY if its `license` is in
APPROVED_LICENSES (Pulpo-owned, commissioned, or genuinely CC0 / public-domain).
Broker photos and "some stock site" are NOT acceptable — that's the whole point.
Every entry carries `credit` + `license` + `license_url` so attribution is
always shippable.

How the engine uses it (ig_story opener): `get(zone)` → if a curated image
exists, the opener is that image + the hook; otherwise the opener falls back to
the designed gradient poster (still beautiful, still brand-safe). So the library
can grow zone-by-zone without ever blocking a post.

To add a zone: drop the vetted image at `web/data/ig_assets/zones/<zone>.jpg`
and add one entry below. `missing_shots()` prints the shot-list still to source.
"""
from __future__ import annotations

# Licenses we accept for an establishing image. Anything else is rejected by
# _valid() — no broker photos, no unlicensed stock.
APPROVED_LICENSES = frozenset({
    "pulpo_owned",     # shot by / for Pulpo
    "commissioned",    # paid, rights assigned to Pulpo
    "cc0",             # Creative Commons Zero (public-domain dedication)
    "public_domain",
})

ZONE_DIR = "web/data/ig_assets/zones"

# The registry. EMPTY today by design — no image ships until a human vets it +
# its license. Each entry:
#   "<zone>": {
#       "image": f"{ZONE_DIR}/<zone>.jpg",   # local path (ig_publish makes it a URL)
#       "credit": "…",                        # photographer / source, for attribution
#       "license": "pulpo_owned",             # must be in APPROVED_LICENSES
#       "license_url": "",                    # required for cc0 / public_domain
#   }
ZONE_IMAGES: dict[str, dict] = {}

# The shot-list: the scenic zones worth a curated establishing shot, most-
# featured first. Sourcing these unlocks real-location openers for the bulk of
# the feed; everything else falls back to the designed poster until sourced.
TARGET_ZONES: tuple[tuple[str, str], ...] = (
    ("la-libertad",   "surf capital — Punta Roca, the pier at sunset"),
    ("el-tunco",      "the iconic rock formations at golden hour"),
    ("el-zonte",      "Bitcoin Beach — the cove and point break"),
    ("el-sunzal",     "the long right-hander, palm line"),
    ("costa-del-sol", "estuary + open Pacific, the sandbar"),
    ("mizata",        "the empty point, cliffs meeting the sea"),
    ("el-cuco",       "east-coast dawn, Las Flores / Punta Mango"),
    ("punta-mango",   "the jungle-backed point break"),
    ("la-union",      "Gulf of Fonseca, volcanic islands on the water"),
    ("conchagua",     "the volcano over the gulf"),
    ("acajutla",      "Los Cóbanos reef, the west-coast light"),
    ("lago-coatepeque", "the crater lake, turquoise from above"),
    ("lago-ilopango", "the caldera lake at dusk"),
    ("santa-tecla",   "the coffee-hill greens above the city"),
)


def _valid(entry: dict) -> bool:
    return (
        isinstance(entry, dict)
        and bool(entry.get("image"))
        and entry.get("license") in APPROVED_LICENSES
        and bool(entry.get("credit"))
        # cc0 / public_domain must cite where it came from
        and (entry["license"] not in {"cc0", "public_domain"} or bool(entry.get("license_url")))
    )


def get(zone: str | None) -> dict | None:
    """The curated establishing image for a zone, or None if none is vetted yet
    (→ the opener falls back to the designed poster). Invalid/unlicensed entries
    are treated as absent — brand safety fails closed, never open."""
    if not zone:
        return None
    entry = ZONE_IMAGES.get(zone)
    return entry if entry and _valid(entry) else None


def has(zone: str | None) -> bool:
    return get(zone) is not None


def all_zones() -> list[str]:
    """Zones with a valid curated image today."""
    return [z for z in ZONE_IMAGES if _valid(ZONE_IMAGES[z])]


def missing_shots() -> list[tuple[str, str]]:
    """Target zones still needing a curated establishing shot — the sourcing
    to-do list. `python3 -c "from automation import ig_zone_images as z;
    print(z.missing_shots())"`."""
    have = set(all_zones())
    return [(z, note) for z, note in TARGET_ZONES if z not in have]
