/**
 * Pulpo frontend type definitions — mirror of pulpo.models.Listing.
 *
 * These types describe the shape of records the frontend reads from
 * web/data/ranked.json. The Python dataclass at pulpo/models.py is the
 * single source of truth; this file is a hand-mirror of it kept in sync
 * via tests/test_ranked_schema.py.
 *
 * To get type-aware autocomplete + error detection in JS files, add this
 * triple-slash directive at the top of any .js file under web/assets/:
 *
 *   // @ts-check
 *   /// <reference path="./types.d.ts" />
 *
 * Then JSDoc-style annotations on function parameters carry the types:
 *
 *   /** @param {Listing} r * /
 *   function panelHTML(r) { ... }
 *
 * VS Code (and any editor with TypeScript Language Server) will then
 * flag typos like `r.price_USD` or `r.bedroom` (singular) immediately.
 *
 * Workflow when a Listing field changes:
 *   1. Update pulpo/models.py
 *   2. Run `python -m automation.generate_ranked_schema` to refresh the
 *      JSON Schema
 *   3. Update this file to match
 *   4. tests/test_ranked_schema.py will fail loudly if any of the three
 *      drifts.
 */

/** Canonical property type tag. */
export type PropertyType = "land" | "house" | "condo";

/** Confidence levels for zone resolution. */
export type ZoneConfidence =
    | "specific"
    | "municipality"
    | "department"
    | "unresolved";

/** Confidence levels for geocoding. */
export type GeocodingConfidence = "high" | "medium" | "low";

/** Geocoding source — extracted from broker text vs estimated by LLM. */
export type GeocodingSource = "extracted" | "estimated";

/** Listing-level validation outcome. `null` = passed all gates. */
export type ValidationStatus = "flagged" | null;

/** Investment-signal badge tag (PRD §FR-7). */
export type InvestmentSignal = "deal" | "hot" | "stale" | "new" | null;

/**
 * One row in `web/data/ranked.json`.
 *
 * Nullability mirrors the Python dataclass: every field is ALWAYS present
 * in the JSON (asdict() emits all of them), but Optional[T] fields can
 * carry null. Lists default to empty arrays — never null.
 */
export interface Listing {
    // ── Identity ──────────────────────────────────────────────────────
    source: string;                    // "goodlife" | "oceanside" | ...
    source_id: string;                 // site-specific ID
    url: string;
    scraped_at: string;                // ISO8601 UTC

    // ── Headline ──────────────────────────────────────────────────────
    title: string;
    description: string;

    // ── Geography ────────────────────────────────────────────────────
    country: "SV";
    department: string | null;
    municipality: string | null;
    zone: string | null;               // canonical slug: "el-tunco", ...
    zone_confidence: ZoneConfidence | null;
    location_text: string;
    lat: number | null;
    lng: number | null;
    geocoding_confidence: GeocodingConfidence | null;

    // ── Size + Price ─────────────────────────────────────────────────
    area_m2: number | null;
    raw_size_text: string;
    price_usd: number | null;
    raw_price_text: string;
    price_per_m2: number | null;       // derived

    // ── Property type ────────────────────────────────────────────────
    property_type: PropertyType;

    // Type-specific fields. All optional — populated only for house/condo.
    bedrooms: number | null;
    bathrooms: number | null;          // half-baths land as 0.5 increments
    built_area_m2: number | null;
    price_per_built_m2: number | null;
    year_built: number | null;
    parking_spaces: number | null;
    floor: number | null;              // condo only
    hoa_fee_usd_monthly: number | null;

    // ── Boolean attributes ───────────────────────────────────────────
    is_beachfront: boolean;
    is_in_development: boolean;
    development_name: string | null;
    has_paved_access: boolean;
    has_water: boolean;
    has_power: boolean;
    has_ocean_view: boolean;
    has_mountain_view: boolean;
    has_water_body: boolean;
    is_flat: boolean;
    is_repriced: boolean;

    // ── Activity ──────────────────────────────────────────────────────
    days_listed: number | null;
    photos_count: number;
    photo_urls: string[];               // [0] is hero
    hero_photo_path: string | null;     // local /photos/<source>_<id>.jpg
    /** PR-7.6 — heuristic quality score (0..100) for hero_photo_path. null when not scored. */
    hero_photo_quality_score: number | null;
    first_seen_at: string | null;       // ISO8601 UTC

    // ── Broker ──────────────────────────────────────────────────────
    broker_name: string | null;
    broker_phone: string | null;
    broker_email: string | null;

    // ── Validation + AI enrichment ────────────────────────────────
    validation_status: ValidationStatus;
    validation_warnings: string[];
    /** PR-7.5 bilingual shape: {en, es}. Legacy entries (pre-PR-7.5) carry null. */
    title_canonical: { en: string; es: string } | null;
    short_description_canonical: { en: string; es: string } | null;
    /** PR-7.5: each USP carries both languages. */
    reasons_to_buy: { en: string; es: string }[];
    /** PR-7.5: language of the source listing's URL — gates the "View on source" CTA. */
    url_language: "en" | "es" | "mixed" | null;
    geocoding_source: GeocodingSource | null;
    geocoding_reference: string | null;
    enriched_at: string | null;
    enrichment_model: string | null;

    // ── Ranking output ───────────────────────────────────────────────
    rank: number | null;                // 1-based position rank
    rank_score: number | null;          // composite 0..100
    zone_percentile: number | null;     // 0..100, lower = cheaper
    value_score: number | null;         // 0..100
    location_score: number | null;      // 0..100
    momentum_score: number | null;      // 0..100
    rank_reasons: string[];

    // ── Derived signals (PRD §FR-7) ─────────────────────────────────
    data_quality_score: number | null;  // 0..1
    investment_signal: InvestmentSignal;
    readiness_score: number | null;     // 0..3
    source_label: string[];

    // ── PR-7 — UX-facing derives ────────────────────────────────────
    source_type: "off_market" | "on_market" | null;  // gates paywall + "View on source"
    previous_price: number | null;                   // strikethrough on cards/detail when is_repriced

    // ── Zone medians (PRD §FR-7.5) ──────────────────────────────────
    price_vs_zone_median: number | null;  // USD/m² median of bucket peers
    price_vs_zone_pct: number | null;     // signed % vs bucket median

    // ── Distance fields (PRD §FR-5.5) ───────────────────────────────
    dist_airport_km: number | null;
    dist_beach_km: number | null;
    dist_highway_km: number | null;
    dist_nearest_town_km: number | null;
}
