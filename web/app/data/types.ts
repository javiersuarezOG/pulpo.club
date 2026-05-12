// The Listing type is the contract between the adapter and the rest of
// the app. It mirrors the prototype's mock-LISTINGS shape so components
// don't change when we swap in real data.

export type Localized = { en: string; es?: string };

// IA-axis literals. Single source of truth lives in pulpo/ia_config.py;
// web/app/config/ia.ts re-exports identical literals so this file +
// the runtime config stay in lockstep.
export type MasterCategory = "beach" | "lake";
export type Subcategory    = "homes" | "condos" | "land";
export type DiscoveryTag   = "top_rated" | "under_250k" | "gated" | "waterfront";

export type Listing = {
  id: string;
  title: Localized;
  description: Localized;
  usps: Localized[];
  /** Schema v3 — detected dominant language of the listing's source URL.
   *  Used to gate the "View on source" link. null when DeepSeek didn't run. */
  url_language: "en" | "es" | "mixed" | null;
  zone_name: string;
  region: string | null;
  country: string;
  province_state: string;
  // PR-8 — backend-derived enum (pulpo/derived_rules.derive_land_type).
  // null when no signal (rare — backend defaults to "residential" for
  // any land/house/condo property_type).
  land_type:
    | "residential"
    | "agricultural"
    | "commercial"
    | "tourist"
    | null;
  size_m2: number | null;
  price: number | null;
  previous_price: number | null;
  price_per_m2: number | null;
  photos: string[];
  photos_count: number;
  // PR-7.6 — heuristic quality score (0..100) for the hero photo.
  // null = pipeline didn't score this run (offline / no OpenCV).
  hero_photo_quality_score: number | null;
  // OCR-flag for brochure-style hero photos (price stamps / banners /
  // agency overlays). True excludes the listing from the elite featured
  // pool. null = no OCR signal (Tesseract absent or undecodable image).
  has_text_overlay: boolean | null;
  // Image-enrichment protocol flags (hero rewrite Phase 2). Source of
  // truth is pulpo/models.py Listing; pipeline writes the derivative
  // files + sidecars and sets these flags.
  hero_eligible: boolean;  // <file>.hero.jpg ≥ 1600×1200 + aspect 1.4–1.85 + ≤ 5MB
  card_eligible: boolean;  // <file>.jpg ≥ 800×600
  first_seen_date: number;     // days ago Pulpo first scraped this listing
  // Days since the source published the listing (from the scraper's
  // parse of mod_dt). `null` when the source date was unparseable —
  // distinct from 0 ("posted today"). Consumers must null-guard.
  days_listed: number | null;
  is_repriced: boolean;
  source_type: "on_market" | "off_market";
  source_label: string;
  source_id: string;
  // PR-8 — backend-derived (pulpo/derived_rules.derive_beachfront_tier).
  // "on_beach" replaces the prototype's "oceanfront" placeholder.
  beachfront_tier: "on_beach" | "walk_to_beach" | "near_beach" | null;
  has_ocean_view: boolean;
  has_mountain_view: boolean;
  has_water_body: boolean;
  is_flat: boolean;
  has_water: boolean;
  has_power: boolean;
  has_sewage: boolean | null;
  road_access_type: "paved" | "gravel" | "dirt" | "unknown";
  readiness_score: number;
  zoning_use: string | null;
  dist_beach_km: number | null;
  dist_airport_km: number | null;
  dist_nearest_town_km: number | null;
  has_lat_lng: boolean;
  /** DeepSeek's self-reported confidence on the lat/lng. 'high' = within
   *  ~2km, 'medium' = within municipality, 'low' = department-level guess.
   *  null when DeepSeek didn't run OR the listing has no lat/lng (in which
   *  case any populated dist_*_km comes from a zone-table fallback and is
   *  itself approximate). The FE uses this to soften distance displays. */
  geocoding_confidence: "high" | "medium" | "low" | null;
  is_sold: boolean;
  original_url: string | null;
  // Carried for the legacy Browse "Advanced ranking" group + sort:
  rank_score: number | null;
  value_score: number | null;
  location_score: number | null;
  momentum_score: number | null;
  property_type: string | null;
  bedrooms: number | null;
  // IA-axis derives (populated by pulpo.derived_rules.apply_ia_derives).
  // master_category/subcategory are null for interior land, raw, or
  // property_type that doesn't map to the homes/condos/land trichotomy.
  // discovery_tags is always an array (possibly empty). star_rating is
  // always a number (0.0 when rank_score is missing). See
  // pulpo/ia_config.py for the threshold definitions.
  master_category: MasterCategory | null;
  subcategory: Subcategory | null;
  discovery_tags: DiscoveryTag[];
  star_rating: number;
};
