// Live-data adapter — fetches /data/ranked.json and reshapes each
// record into the Listing schema the rest of the app expects.
//
// This is the single seam between the backend's ranked.json and the
// React components. If WS2 ever moves to a real /api/listings endpoint,
// swap this file's implementation; nothing else changes.
//
// Field mapping table lives in the plan
// (~/.claude/plans/use-the-ux-fluffy-cocke.md). Highlights:
//   - title/description/usps wrap as { en } until PR-7.5 adds ES.
//   - description has its HTML entities decoded (raw scrape preserves them).
//   - source_type derives from `source` per the off-market rule
//     (whatsapp/facebook/private → off_market). Until PR-7 there are no
//     such sources in the data.
//   - beachfront_tier falls back to is_beachfront ? "near_beach" : null
//     (PR-8 ships the full enum).
//   - land_type is a placeholder until PR-8's classifier.

import type { Listing } from "./types";
import { decodeHtmlEntities } from "./decode-html";

// Off-market sources per the user's rule. The literal labels never
// reach the UI for these — we emit "Off-market" instead.
const OFF_MARKET_SOURCES = new Set(["whatsapp", "facebook", "private"]);

// Pretty source names. Anything missing falls back to a Title-Cased
// version of the source key.
const SOURCE_LABELS: Record<string, string> = {
  goodlife: "Goodlife",
  oceanside: "Oceanside",
  century21: "Century 21",
  bienesraices: "Bienes Raíces",
  remax: "RE/MAX",
  nexo: "Nexo",
  realtyelsalvador: "Realty El Salvador",
};

// Pretty zone names. Slugs come from `pulpo/normalize.py:ZONE_PATTERNS`.
// Missing slugs fall back to Title-Cased pretty name.
const ZONE_NAMES: Record<string, string> = {
  "el-cuco": "Playa El Cuco",
  "las-flores": "Las Flores",
  "punta-mango": "Punta Mango",
  "el-espino": "El Espino",
  "el-tunco": "El Tunco",
  "el-sunzal": "El Sunzal",
  "el-zonte": "El Zonte",
  "san-diego": "San Diego (K59)",
  "mizata": "Mizata",
  "conchagua": "Conchagua",
  "jiquilisco": "Jiquilisco",
  "puerto-la-libertad": "Puerto La Libertad",
  "la-libertad": "La Libertad",
  "la-union": "La Unión",
};

function pretty(slug: string | null | undefined, lookup: Record<string, string>): string {
  if (!slug) return "—";
  if (lookup[slug]) return lookup[slug];
  return slug
    .replace(/-/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function deriveSourceType(source: string): "on_market" | "off_market" {
  return OFF_MARKET_SOURCES.has(source) ? "off_market" : "on_market";
}

function daysSince(iso: string | null | undefined): number {
  if (!iso) return 0;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 0;
  const ms = Date.now() - t;
  return Math.max(0, Math.floor(ms / 86_400_000));
}

function deriveLandType(propertyType: string | null): Listing["land_type"] {
  // Placeholder — PR-8 ships the real text classifier.
  if (propertyType === "land") return "raw";
  if (propertyType === "condo" || propertyType === "house" || propertyType === "apartment") {
    return "residential";
  }
  return "residential";
}

function deriveBeachfrontTier(
  isBeachfront: boolean,
  tier: string | null | undefined
): Listing["beachfront_tier"] {
  // Backend may already emit a tier (post-PR-8). Until then, fall back
  // to the boolean.
  if (tier === "oceanfront" || tier === "walk_to_beach" || tier === "near_beach") {
    return tier;
  }
  return isBeachfront ? "near_beach" : null;
}

function deriveRoadAccess(
  hasPaved: boolean,
  type: string | null | undefined
): Listing["road_access_type"] {
  if (type === "paved" || type === "gravel" || type === "dirt") return type;
  if (hasPaved) return "paved";
  return "unknown";
}

function buildPhotos(raw: any): string[] {
  // Prefer hero_photo_path (locally cached, served by Vercel) for slot
  // 0; supplement with photo_urls for the gallery. hero_photo_path is
  // a path like "/photos/<source>_<id>.jpg".
  const out: string[] = [];
  const hero = raw.hero_photo_path;
  if (typeof hero === "string" && hero.length > 0) out.push(hero);
  const urls = Array.isArray(raw.photo_urls) ? raw.photo_urls : [];
  for (const u of urls) {
    if (typeof u !== "string") continue;
    if (out.length === 0 || u !== out[0]) out.push(u);
  }
  return out;
}

export function adaptListing(raw: any): Listing {
  const sourceKey = String(raw.source ?? "unknown");
  const sourceId = String(raw.source_id ?? "");
  const id = `${sourceKey}-${sourceId}` || `pulpo-${Math.random().toString(36).slice(2)}`;
  // PR-7 — prefer the backend-derived source_type when present (the
  // pipeline now sets it via pulpo/derived_rules.derive_source_type).
  // Fallback to the FE-side derivation keeps things rendering during
  // the deploy window before the new ranked.json lands.
  const sourceType: "on_market" | "off_market" =
    raw.source_type === "off_market" || raw.source_type === "on_market"
      ? raw.source_type
      : deriveSourceType(sourceKey);

  // Off-market listings hide the source name entirely (the user's rule
  // — never reveal that a listing came from WhatsApp/Facebook/private).
  // We pass an empty label and let the FE substitute the i18n
  // "Off-market" string.
  const sourceLabel =
    sourceType === "off_market"
      ? ""
      : SOURCE_LABELS[sourceKey] ??
        sourceKey.replace(/^\w/, (c) => c.toUpperCase());

  const titleStr =
    typeof raw.title_canonical === "string" && raw.title_canonical.length > 0
      ? raw.title_canonical
      : typeof raw.title === "string"
      ? raw.title
      : "Untitled";

  const descStr =
    typeof raw.short_description_canonical === "string" && raw.short_description_canonical.length > 0
      ? raw.short_description_canonical
      : typeof raw.description === "string"
      ? decodeHtmlEntities(raw.description).replace(/\s+/g, " ").trim()
      : "";

  const usps: Listing["usps"] = Array.isArray(raw.reasons_to_buy)
    ? raw.reasons_to_buy
        .filter((s: any) => typeof s === "string" && s.length > 0)
        .map((s: string) => ({ en: s }))
    : [];

  const isBeachfront = Boolean(raw.is_beachfront);
  const photos = buildPhotos(raw);
  const department = typeof raw.department === "string" ? raw.department : null;

  return {
    id,
    title: { en: titleStr },
    description: { en: descStr },
    usps,
    zone_name: pretty(raw.zone, ZONE_NAMES),
    region: department,
    country: typeof raw.country === "string" ? raw.country : "SV",
    province_state: department ? `${department}, El Salvador` : "El Salvador",
    land_type: deriveLandType(typeof raw.property_type === "string" ? raw.property_type : null),
    size_m2: typeof raw.area_m2 === "number" ? raw.area_m2 : null,
    price: typeof raw.price_usd === "number" ? raw.price_usd : null,
    previous_price: typeof raw.previous_price === "number" ? raw.previous_price : null,
    price_per_m2: typeof raw.price_per_m2 === "number" ? raw.price_per_m2 : null,
    photos,
    photos_count: typeof raw.photos_count === "number" ? raw.photos_count : photos.length,
    hero_photo_quality_score:
      typeof raw.hero_photo_quality_score === "number" ? raw.hero_photo_quality_score : null,
    first_seen_date: daysSince(raw.first_seen_at),
    days_listed: typeof raw.days_listed === "number" ? raw.days_listed : 0,
    is_repriced: Boolean(raw.is_repriced),
    source_type: sourceType,
    source_label: sourceLabel,
    source_id: sourceKey,
    beachfront_tier: deriveBeachfrontTier(isBeachfront, raw.beachfront_tier),
    has_ocean_view: Boolean(raw.has_ocean_view),
    has_mountain_view: Boolean(raw.has_mountain_view),
    has_water_body: Boolean(raw.has_water_body),
    is_flat: Boolean(raw.is_flat),
    has_water: Boolean(raw.has_water),
    has_power: Boolean(raw.has_power),
    has_sewage: typeof raw.has_sewage === "boolean" ? raw.has_sewage : null,
    road_access_type: deriveRoadAccess(Boolean(raw.has_paved_access), raw.road_access_type),
    readiness_score: typeof raw.readiness_score === "number" ? raw.readiness_score : 0,
    zoning_use: typeof raw.zoning_use === "string" ? raw.zoning_use : null,
    dist_beach_km: typeof raw.dist_beach_km === "number" ? raw.dist_beach_km : null,
    dist_airport_km: typeof raw.dist_airport_km === "number" ? raw.dist_airport_km : null,
    dist_nearest_town_km:
      typeof raw.dist_nearest_town_km === "number" ? raw.dist_nearest_town_km : null,
    has_lat_lng: typeof raw.lat === "number" && typeof raw.lng === "number",
    is_sold: Boolean(raw.is_sold),
    original_url: sourceType === "on_market" && typeof raw.url === "string" ? raw.url : null,
    rank_score: typeof raw.rank_score === "number" ? raw.rank_score : null,
    value_score: typeof raw.value_score === "number" ? raw.value_score : null,
    location_score: typeof raw.location_score === "number" ? raw.location_score : null,
    momentum_score: typeof raw.momentum_score === "number" ? raw.momentum_score : null,
    property_type: typeof raw.property_type === "string" ? raw.property_type : null,
    bedrooms: typeof raw.bedrooms === "number" ? raw.bedrooms : null,
  };
}

let cache: { ts: number; listings: Listing[] } | null = null;

export async function loadListings(): Promise<Listing[]> {
  // 60s in-memory cache — same listings JSON serves every page load
  // within a session.
  if (cache && Date.now() - cache.ts < 60_000) return cache.listings;

  const res = await fetch("/data/ranked.json", { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`ranked.json HTTP ${res.status}`);
  }
  const raw = await res.json();
  if (!Array.isArray(raw)) {
    throw new Error("ranked.json is not an array");
  }
  const listings = raw.map(adaptListing);
  cache = { ts: Date.now(), listings };
  return listings;
}

export function clearListingsCache() {
  cache = null;
}
