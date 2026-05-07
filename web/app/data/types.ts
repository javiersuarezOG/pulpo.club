// The Listing type is the contract between the adapter and the rest of
// the app. It mirrors the prototype's mock-LISTINGS shape so components
// don't change when we swap in real data.

export type Localized = { en: string; es?: string };

export type Listing = {
  id: string;
  title: Localized;
  description: Localized;
  usps: Localized[];
  zone_name: string;
  region: string | null;
  country: string;
  province_state: string;
  land_type: "residential" | "agricultural" | "commercial" | "tourist" | "mixed" | "raw";
  size_m2: number | null;
  price: number | null;
  previous_price: number | null;
  price_per_m2: number | null;
  photos: string[];
  photos_count: number;
  // PR-7.6 — heuristic quality score (0..100) for the hero photo.
  // null = pipeline didn't score this run (offline / no OpenCV).
  hero_photo_quality_score: number | null;
  first_seen_date: number;     // days ago (computed at adapter time)
  days_listed: number;
  is_repriced: boolean;
  source_type: "on_market" | "off_market";
  source_label: string;
  source_id: string;
  beachfront_tier: "oceanfront" | "walk_to_beach" | "near_beach" | null;
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
  is_sold: boolean;
  original_url: string | null;
  // PR-7.5 — language of the source listing's URL. FE uses this to
  // decide whether to show the "View on source" CTA on the detail
  // panel: only renders when url_language matches user_locale OR is
  // "mixed". Legacy listings (pre-bilingual-enrichment) carry null.
  url_language: "en" | "es" | "mixed" | null;
  // Carried for the legacy Browse "Advanced ranking" group + sort:
  rank_score: number | null;
  value_score: number | null;
  location_score: number | null;
  momentum_score: number | null;
  property_type: string | null;
  bedrooms: number | null;
};
