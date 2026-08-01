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

# License FAMILIES we accept for an establishing image, matched against the
# entry's license string (normalized). Anything else is rejected by _valid() —
# no broker photos, no unlicensed stock. CC BY-SA is accepted but share-alike:
# _is_share_alike() flags it so a reviewer can prefer non-SA where it matters.
APPROVED_LICENSES = frozenset({
    "pulpo_owned",     # shot by / for Pulpo
    "commissioned",    # paid, rights assigned to Pulpo
    "cc0",             # Creative Commons Zero (public-domain dedication)
    "public_domain",
    "cc-by",           # attribution required (emitted in the first comment)
    "cc-by-sa",        # attribution + share-alike
})


def _license_family(lic: str) -> str | None:
    """Normalize a license string ('CC BY-SA 4.0', 'CC0', 'pulpo_owned') to a
    family key in APPROVED_LICENSES, or None if unrecognised (→ rejected)."""
    s = (lic or "").lower().replace("_", " ").strip()
    if "share" in s or "by-sa" in s or "by sa" in s:
        return "cc-by-sa"
    if "cc0" in s or "zero" in s:
        return "cc0"
    if "public domain" in s or s == "pd":
        return "public_domain"
    if "by" in s and "cc" in s:
        return "cc-by"
    if "pulpo" in s or "owned" in s:
        return "pulpo_owned"
    if "commission" in s:
        return "commissioned"
    return None


def _requires_attribution(lic: str) -> bool:
    return _license_family(lic) in {"cc-by", "cc-by-sa"}

ZONE_DIR = "web/data/ig_assets/zones"

# The registry. EMPTY today by design — no image ships until a human vets it +
# its license. Each entry:
#   "<zone>": {
#       "image": f"{ZONE_DIR}/<zone>.jpg",   # local path (ig_publish makes it a URL)
#       "credit": "…",                        # photographer / source, for attribution
#       "license": "pulpo_owned",             # must be in APPROVED_LICENSES
#       "license_url": "",                    # required for cc0 / public_domain
#   }
ZONE_IMAGES: dict[str, dict] = {
    # Sourced from Wikimedia Commons + VISUALLY VERIFIED (each image was opened
    # and confirmed to show the actual location and be beautiful). Attribution
    # for CC-BY/BY-SA is emitted in the post's first comment (ig_render).
    "el-tunco": {
        "image": f"{ZONE_DIR}/el-tunco.jpg", "credit": "Rebevon11",
        "license": "CC BY-SA 4.0",
        "license_url": "https://commons.wikimedia.org/wiki/File:El_tunco.png",
    },
    "el-zonte": {
        "image": f"{ZONE_DIR}/el-zonte.jpg", "credit": "Wikimedia Commons",
        "license": "CC BY-SA 3.0",
        "license_url": "https://commons.wikimedia.org/wiki/File:El_Zonte_(11-2011)_-_Playa_-_panoramio.jpg",
    },
    "lago-coatepeque": {
        "image": f"{ZONE_DIR}/lago-coatepeque.jpg", "credit": "JMRAFFi",
        "license": "CC BY 4.0",
        "license_url": "https://commons.wikimedia.org/wiki/File:Coatepeque_Vista1.jpg",
    },
    "el-cuco": {
        "image": f"{ZONE_DIR}/el-cuco.jpg", "credit": "Ll1324",
        "license": "CC0",
        "license_url": "https://commons.wikimedia.org/wiki/File:El_Cuco_San_Miguel_El_Salvador_Playa_2011.jpg",
    },
    "lago-ilopango": {
        "image": f"{ZONE_DIR}/lago-ilopango.jpg", "credit": "Ll1324",
        "license": "CC0",
        "license_url": "https://commons.wikimedia.org/wiki/File:Lago_Ilopango_desde_Cojutepeque_2011.jpg",
    },
}

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
    if not (isinstance(entry, dict) and entry.get("image") and entry.get("credit")):
        return False
    fam = _license_family(entry.get("license"))
    if fam not in APPROVED_LICENSES:
        return False
    # anything sourced from the commons (not our own) must cite where it's from
    if fam in {"cc0", "public_domain", "cc-by", "cc-by-sa"} and not entry.get("license_url"):
        return False
    return True


def is_share_alike(zone: str | None) -> bool:
    """True if the zone's image is CC BY-SA (share-alike) — a reviewer may
    prefer to swap these for a non-SA image where licensing hygiene matters."""
    entry = get(zone)
    return bool(entry) and _license_family(entry.get("license")) == "cc-by-sa"


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
