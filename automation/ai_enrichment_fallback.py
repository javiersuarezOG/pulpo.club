"""
Deterministic fallbacks for two of three PRD §FR-6 AI tasks.

When OPENAI_API_KEY is missing, the key has no credits, the API rate-
limits us, or any other reason makes a live call impossible, we still
ship 2 of 3 Phase 1 AI fields populated:

- `title_canonical` — PRD §8.1 format is `[Land Type] · [Size] · [Zone]
  · [Top Feature]`. Top-Feature priority list is fully deterministic
  (beachfront → ocean view → water body → off-market → price reduced
  → utilities connected → flat → omitted). Build from existing fields.

- `reasons_to_buy` — PRD §8.3 USP trigger table has 14 deterministic
  rules. Pick the first 3 that apply, substitute placeholders, ship.

- `short_description_canonical` — PQAB structure (§8.2) genuinely needs
  natural-language flow. Cannot be templated cleanly. Stays None when
  AI is unavailable.

All three functions are pure: same inputs → same outputs, no I/O. They
read from a Listing dict (or any object with the same field names) so
they're equally usable in production (run.py) and in tests.
"""
from __future__ import annotations
from typing import Any

from automation.property_types import PROPERTY_TYPES


# PRD §8.1 — Land-type labels for the title.
# Legacy strings only — pre-PR-#64 normalize.detect_property_type emitted
# these as `property_type` values. Kept for backwards compat with old
# fixtures + already-shipped data. Canonical types (land/house/condo)
# read from PROPERTY_TYPES via _type_label() instead so the label stays
# in sync with property_types.py's title_canonical_template.
_LEGACY_TYPE_LABELS = {
    "residential":  "Residential Lot",
    "commercial":   "Commercial Land",
    "recreational": "Recreational Land",
    "mixed":        "Mixed-Use Land",
    "raw":          "Raw Land",
    "lot":          "Residential Lot",
}

# Backwards-compat alias for any external test/import that still uses the
# old name. New code should call _type_label() instead.
LAND_TYPE_LABELS = _LEGACY_TYPE_LABELS


def _type_label(pt: str) -> str:
    """Return the title-prefix label for a property_type.

    Resolution order:
      1. PROPERTY_TYPES[pt]: derive from title_canonical_template's
         leading segment ("Beach House · {zone}" → "Beach House"). This
         keeps the label in lockstep with property_types.py — change one,
         change both. Covers land/house/condo (the canonical 3 types).
      2. _LEGACY_TYPE_LABELS: pre-PR-#64 strings that historical data
         may carry (lot/finca/residential/etc.).
      3. "Raw Land" default.
    """
    cfg = PROPERTY_TYPES.get(pt)
    if cfg:
        template = cfg.get("title_canonical_template", "")
        # Templates are "{prefix} · {placeholder}" — split on the first
        # " · {" so the prefix survives even if the template gains more
        # placeholders later.
        prefix = template.split(" · {", 1)[0]
        return prefix or "Raw Land"
    return _LEGACY_TYPE_LABELS.get(pt) or "Raw Land"


def _g(li: Any, name: str) -> Any:
    return li.get(name) if isinstance(li, dict) else getattr(li, name, None)


# ── title_canonical fallback ───────────────────────────────────────────

def _format_size(area_m2: Any) -> str | None:
    """PRD §8.1: ≥10,000 m² → ha; else m². Comma-separate thousands."""
    if not isinstance(area_m2, (int, float)) or area_m2 <= 0:
        return None
    if area_m2 >= 10_000:
        ha = round(area_m2 / 10_000, 1)
        # Drop trailing .0 for whole numbers
        return f"{ha:g} ha"
    return f"{int(round(area_m2)):,} m²"


def _top_feature(li: Any) -> str | None:
    """PRD §8.1 priority order — first match wins."""
    if _g(li, "is_beachfront") is True:
        return "Beachfront"
    if _g(li, "has_ocean_view") is True:
        return "Ocean View"
    if _g(li, "has_water_body") is True:
        return "Waterfront"
    if _g(li, "source_type") == "off_market":
        return "Off-Market"
    if _g(li, "is_repriced") is True:
        return "Price Reduced"
    if _g(li, "readiness_score") == 3:
        return "Utilities Connected"
    if _g(li, "is_flat") is True:
        return "Flat Terrain"
    return None


def _zone_name(li: Any) -> str | None:
    """Prefer the canonical zone slug; fall back to municipality / department."""
    z = _g(li, "zone")
    if isinstance(z, str) and z:
        # Title-case the slug: "el-tunco" → "El Tunco"
        return " ".join(part.capitalize() for part in z.split("-"))
    m = _g(li, "municipality")
    if isinstance(m, str) and m:
        return m
    d = _g(li, "department")
    if isinstance(d, str) and d:
        return d
    return None


def fallback_title(li: Any) -> str | None:
    """Build [Type Label] · [Size] · [Zone] · [Top Feature]. Omit empty parts.

    Type label is now type-aware — houses produce "Beach House · …",
    condos produce "Beach Condo · …". Pre-PR-#64 every listing got
    "Raw Land · …" because LAND_TYPE_LABELS had no entry for built
    types and fell through to the default; the goodlife villa shipped
    as "Raw Land · Costa Del Sol" until this fix.
    """
    parts: list[str] = []
    pt = (_g(li, "property_type") or "land")
    parts.append(_type_label(pt))

    size = _format_size(_g(li, "area_m2"))
    if size:
        parts.append(size)

    zone = _zone_name(li)
    if zone:
        parts.append(zone)

    feature = _top_feature(li)
    if feature:
        parts.append(feature)

    title = " · ".join(parts)
    # PRD §8.1 hard cap: 80 chars.
    return title[:80] if title else None


# ── reasons_to_buy fallback ────────────────────────────────────────────

# PRD §8.3 USP trigger table — first 3 applicable wins. Each entry is
# (predicate, template). Templates use {placeholders} resolved from the
# listing dict via _fill_template().
def _trigger_rules() -> list:
    """Each entry: (predicate(li) -> bool, template(str))."""
    return [
        (lambda li: _g(li, "is_beachfront") is True,
         "🏖 Direct beach access — oceanfront parcel on the {zone} coast"),
        (lambda li: _g(li, "source_type") == "off_market",
         "✂ Off-market deal — not listed on any public real estate portal"),
        (lambda li: _g(li, "is_repriced") is True,
         "📉 Price recently reduced — potential motivated seller, negotiate from strength"),
        (lambda li: _g(li, "readiness_score") == 3,
         "⚡ Fully connected — water, electricity, and paved road confirmed"),
        (lambda li: _g(li, "readiness_score") == 2,
         "✓ Two of three utilities confirmed — lower development friction"),
        (lambda li: isinstance(_g(li, "days_listed"), int) and _g(li, "days_listed") <= 7,
         "🆕 Just listed — one of {zone}'s newest additions this week"),
        (lambda li: _g(li, "has_ocean_view") is True,
         "🌅 Ocean views — {zone} sea views from the parcel"),
        (lambda li: _g(li, "is_flat") is True,
         "📐 Flat terrain — minimal earthwork needed, lower build costs"),
        (lambda li: _g(li, "has_water_body") is True,
         "💧 Natural water feature on or bordering the parcel"),
        (lambda li: _g(li, "has_paved_access") is True,
         "🛣 Paved road access — direct vehicle access, year-round usability"),
        (lambda li: isinstance(_g(li, "photos_count"), int) and _g(li, "photos_count") >= 10,
         "📸 Well-documented listing — {photos_count} photos available for review"),
        (lambda li: _g(li, "is_in_development") is True
                    and isinstance(_g(li, "development_name"), str)
                    and len(_g(li, "development_name") or "") > 0,
         "🏘 Inside {development_name} — development infrastructure already in place"),
        (lambda li: _g(li, "zone_confidence") == "specific",
         "📍 Located in {zone} — established zone with active comparable inventory"),
    ]


def _fill_template(template: str, li: Any) -> str | None:
    """Substitute {zone} / {photos_count} / {development_name} from listing.

    When a template references {zone} but the listing has no resolvable
    zone/municipality/department, return None to skip the rule. Rendering
    with an empty zone produced broken bullets like "one of 's newest
    additions" or "on the  coast" — observed in the 2026-05-07 nightly's
    fallback path for two zone-unresolved bienesraices listings.
    """
    z = _zone_name(li)
    if "{zone}" in template and not z:
        return None
    pc = _g(li, "photos_count") or 0
    dn = _g(li, "development_name") or "this development"
    try:
        return template.format(
            zone           = z or "",
            photos_count   = pc,
            development_name = dn,
        )
    except (KeyError, IndexError):
        return None


def fallback_reasons_to_buy(li: Any, max_n: int = 3) -> list[str]:
    """Apply the §8.3 trigger table; return first max_n applicable bullets."""
    out: list[str] = []
    for predicate, template in _trigger_rules():
        try:
            if not predicate(li):
                continue
        except Exception:
            continue
        bullet = _fill_template(template, li)
        if not bullet:
            continue
        # PRD §8.3 size cap: 10-15 words. Truncate at 18 words for safety.
        words = bullet.split()
        if len(words) > 18:
            bullet = " ".join(words[:18])
        out.append(bullet)
        if len(out) >= max_n:
            break
    return out


# ── orchestrator ───────────────────────────────────────────────────────

def apply_fallbacks(li: Any) -> dict:
    """Set title_canonical and reasons_to_buy on the listing in-place.

    Does NOT touch short_description_canonical — that field requires
    real natural-language generation and stays None when AI is
    unavailable.

    Returns a dict of what was written (for logging).
    """
    title = fallback_title(li)
    reasons = fallback_reasons_to_buy(li)
    written: dict[str, Any] = {}
    if title:
        if isinstance(li, dict):
            li.setdefault("title_canonical", None)
            if not li.get("title_canonical"):
                li["title_canonical"] = title
                written["title_canonical"] = title
        else:
            if not getattr(li, "title_canonical", None):
                setattr(li, "title_canonical", title)
                written["title_canonical"] = title
    if reasons:
        if isinstance(li, dict):
            existing = li.get("reasons_to_buy") or []
            if not existing:
                li["reasons_to_buy"] = reasons
                written["reasons_to_buy"] = reasons
        else:
            existing = getattr(li, "reasons_to_buy", None) or []
            if not existing:
                setattr(li, "reasons_to_buy", reasons)
                written["reasons_to_buy"] = reasons
    return written
