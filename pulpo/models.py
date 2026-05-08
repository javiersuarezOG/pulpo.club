"""Canonical Listing schema. Stays in stdlib (dataclasses) for portability."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

@dataclass
class Listing:
    # Identity
    source: str                       # "goodlife" | "oceanside" | "kazu" | ...
    source_id: str                    # site-specific ID
    url: str
    scraped_at: str                   # ISO8601 UTC

    # Headline
    title: str
    description: str = ""

    # Geography
    country: str = "SV"
    department: Optional[str] = None  # La Unión, San Miguel, La Libertad, ...
    municipality: Optional[str] = None
    zone: Optional[str] = None        # canonical zone slug: "el-cuco", "el-tunco", "el-zonte"
    zone_confidence: Optional[str] = None  # 'specific'|'municipality'|'department'|'unresolved'
    location_text: str = ""           # raw human-readable location string
    lat: Optional[float] = None
    lng: Optional[float] = None
    geocoding_confidence: Optional[str] = None  # 'high'|'low' (Mapbox) or 'medium' (HTML-extracted) per FR-5.4

    # Size — canonical is m²
    area_m2: Optional[float] = None
    raw_size_text: str = ""           # original text: "30 manzanas"

    # Price
    price_usd: Optional[float] = None
    raw_price_text: str = ""
    price_per_m2: Optional[float] = None  # derived

    # Property type
    property_type: str = "land"        # "land" | "house" | "condo"
    # Type-specific fields. All Optional — populated only for house/condo
    # listings. Default None for land so existing land code paths and
    # validation are unaffected. Built area is distinct from `area_m2`
    # (which is the LOT area for land, also-the-lot for house).
    bedrooms: Optional[int] = None
    bathrooms: Optional[float] = None  # half-baths land as 0.5 increments
    built_area_m2: Optional[float] = None
    # The ranking metric for built listings. price / built_area_m2 — derived
    # in normalize.py when both inputs are present. Optional because 80% of
    # bienesraices houses lack built_area_m2; those listings fall through to
    # the lot-based price_per_m2 metric in the value leg.
    price_per_built_m2: Optional[float] = None
    year_built: Optional[int] = None
    parking_spaces: Optional[int] = None
    floor: Optional[int] = None                  # condo only
    hoa_fee_usd_monthly: Optional[float] = None  # condo only

    is_beachfront: bool = False
    # Development / gated-community tagging
    is_in_development: bool = False    # inside a named development or gated community
    development_name: Optional[str] = None  # e.g. "Surf City 1", "Atami"
    has_paved_access: bool = False
    has_water: bool = False
    has_power: bool = False
    # PRD §FR-2 NLP-extracted booleans (Phase 1)
    has_ocean_view: bool = False
    has_mountain_view: bool = False
    has_water_body: bool = False
    is_flat: bool = False
    is_repriced: bool = False          # price has dropped vs. previous scrape

    # Activity
    days_listed: Optional[int] = None
    photos_count: int = 0
    photo_urls: list[str] = field(default_factory=list)   # broker-hosted; [0] is hero
    hero_photo_path: Optional[str] = None                  # local /photos/<source>_<id>.jpg
    # PR-7.6 — heuristic quality score (0..100) for hero_photo_path.
    # None = not yet scored (offline mode, OpenCV unavailable, or
    # download failed). Featured-listing picker filters on this.
    hero_photo_quality_score: Optional[int] = None
    first_seen_at: Optional[str] = None  # ISO8601 UTC, stable across re-scrapes via sidecar

    # Broker
    broker_name: Optional[str] = None
    broker_phone: Optional[str] = None
    broker_email: Optional[str] = None

    # Ranking output (filled by ranker)
    # Validation output (filled by validation layer, before ranker)
    validation_status: Optional[str] = None      # None | "flagged"
    validation_warnings: list[str] = field(default_factory=list)

    # PRD §FR-6 AI-enriched fields (Phase 1).
    # Schema v3 (bilingual + LOCATION HINTS): DeepSeek emits {en, es} dicts
    # for these. The fallback path in automation/ai_enrichment_fallback.py
    # still produces single-language strings for title_canonical and
    # reasons_to_buy when DeepSeek is skipped/fails — adapter on the FE
    # (`localizedFromAny` in web/app/data/listings.ts) handles both shapes.
    # short_description_canonical has no fallback; stays None when the LLM
    # didn't run.
    title_canonical: Optional[Any] = None              # {en, es} dict OR str (fallback)
    short_description_canonical: Optional[Any] = None  # {en, es} dict
    reasons_to_buy: list[Any] = field(default_factory=list)  # list of {en, es} OR list[str] (fallback)

    # PRD WS2 — single-call DeepSeek enrichment metadata (latlong block).
    # `lat`/`lng`/`geocoding_confidence` above are reused; these two carry
    # the LLM-only fields from the latlong response: 'extracted'|'estimated'
    # and the free-text geographic reference the model anchored on.
    geocoding_source: Optional[str] = None
    geocoding_reference: Optional[str] = None

    # Bookkeeping written by the enrichment pass on success — used to gate
    # re-runs on model change and to telemeter coverage over time.
    enriched_at: Optional[str] = None      # ISO8601 UTC, set when enrichment succeeds
    enrichment_model: Optional[str] = None # e.g. "deepseek-chat"
    # Schema v3 — detected dominant language of the source listing. FE uses
    # this to gate the "View on source" link (only show when the source URL
    # language matches the user's locale or is "mixed"). Stays None when
    # DeepSeek is skipped/fails — no fallback producer for this field.
    url_language: Optional[str] = None     # 'en' | 'es' | 'mixed' | None

    rank: Optional[int] = None               # 1-based position rank, 1 = best
    rank_score: Optional[float] = None       # composite 0..100
    zone_percentile: Optional[float] = None  # 0..100, lower = cheaper for zone
    value_score: Optional[float] = None      # 0..100, cheap-for-comp-pool leg
    location_score: Optional[float] = None   # 0..100, zone tier + airport + attributes + freshness
    momentum_score: Optional[float] = None   # 0..100, repriced-rate-per-zone (delta signal)
    rank_reasons: list[str] = field(default_factory=list)

    # PRD §FR-7 derived signals (Phase 1)
    data_quality_score: Optional[float] = None  # 0..1, populated_fields / scoreable_total
    investment_signal: Optional[str] = None     # 'deal'|'hot'|'stale'|'new'|None
    readiness_score: Optional[int] = None       # 0..3, has_water + has_power + has_paved_access
    source_label: list[str] = field(default_factory=list)  # display chips: Beachfront/Price Drop/etc.

    # PR-7 — UX-facing derived fields.
    # `source_type`: "off_market" if scraped from social/private channels
    # (whatsapp, facebook, private, instagram), else "on_market". Drives
    # the off-market shelf, the "View on source" link gating, and the
    # paywall on the detail panel.
    # `previous_price`: most-recent prior price from prices_history.json
    # when is_repriced=True. Surfaced on cards/detail as the strikethrough.
    source_type: Optional[str] = None           # 'off_market'|'on_market'
    previous_price: Optional[float] = None      # USD; only set when is_repriced

    # PRD §FR-7.5 zone medians (Phase 3) — computed each run from the full
    # catalog. None when the (zone, property_type) bucket has fewer than
    # 10 active comparable peers.
    price_vs_zone_median: Optional[float] = None  # USD/m² median of bucket peers
    price_vs_zone_pct: Optional[float] = None     # signed % vs. bucket median (negative=cheaper)

    # PRD §FR-5.5 distance fields (Phase 3) — populated either via haversine
    # from lat/lng (preferred) or via the per-zone airport distance table
    # in pulpo/airports.py (fallback for listings without coords). The
    # other three are stubbed and populate via haversine + SV reference
    # geometry in a follow-up PR.
    dist_airport_km: Optional[float] = None
    dist_beach_km: Optional[float] = None       # ships when SV coastline polylines land
    dist_highway_km: Optional[float] = None     # ships when SV highway shapefiles land
    dist_nearest_town_km: Optional[float] = None  # ships when populated-place table lands

    def to_dict(self) -> dict:
        return asdict(self)

    def to_public_dict(self) -> dict:
        """Public/teaser serialization: strips fields that should sit behind the paywall.

        Public viewers see: rank, zone, size, price band, headline tags, score badge —
        enough to know there ARE good deals, not enough to act on them without a login.
        """
        d = asdict(self)
        # Strip identifying / direct-contact fields
        d.pop("source", None)
        d.pop("source_id", None)
        d.pop("url", None)
        d.pop("description", None)
        d.pop("broker_name", None)
        d.pop("broker_phone", None)
        d.pop("broker_email", None)
        # Coarsen the title so brokers can't be reverse-searched from the headline
        title = d.get("title") or ""
        if title:
            # Keep first ~60 chars; anything past the first phrase tends to leak
            # broker shop names ("— GoodLife El Salvador") that defeat the gate.
            d["title"] = title.split(" — ")[0].split(" | ")[0][:60]
        # Coarsen the price into a band rather than the exact ask
        price = d.get("price_usd")
        if isinstance(price, (int, float)):
            d["price_band"] = _price_band(price)
        d.pop("price_usd", None)
        d.pop("raw_price_text", None)
        d.pop("price_per_m2", None)
        # Coarsen exact coordinates to ~1km grid (3 decimals)
        if isinstance(d.get("lat"), (int, float)):
            d["lat"] = round(d["lat"], 2)
        if isinstance(d.get("lng"), (int, float)):
            d["lng"] = round(d["lng"], 2)
        return d


def _price_band(price: float) -> str:
    """Map an exact USD price to a coarse band for the public teaser."""
    if price < 100_000:
        return "<$100k"
    if price < 250_000:
        return "$100k–$250k"
    if price < 500_000:
        return "$250k–$500k"
    if price < 1_000_000:
        return "$500k–$1M"
    if price < 2_500_000:
        return "$1M–$2.5M"
    if price < 5_000_000:
        return "$2.5M–$5M"
    return "$5M+"
