var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// shared/api-core.ts
var api_core_exports = {};
__export(api_core_exports, {
  API_VERSION: () => API_VERSION,
  FILTER_URL_KEYS: () => FILTER_URL_KEYS,
  ID_SEPARATOR: () => ID_SEPARATOR,
  PRICE_HISTO_MAX: () => PRICE_HISTO_MAX,
  WEIGHT_DEFAULTS: () => WEIGHT_DEFAULTS,
  ZONE_NAMES: () => ZONE_NAMES,
  adaptListing: () => adaptListing,
  applyFilters: () => applyFilters,
  applyRankCap: () => applyRankCap,
  buildListingId: () => buildListingId,
  buildSuggestions: () => buildSuggestions,
  buildTopRankMap: () => buildTopRankMap,
  decodeHtmlEntities: () => decodeHtmlEntities,
  detectListingLang: () => detectListingLang,
  hasFilterParamsInURL: () => hasFilterParamsInURL,
  isListingId: () => isListingId,
  makeDefaultFilters: () => makeDefaultFilters,
  matchesQuery: () => matchesQuery,
  matchesQueryString: () => matchesQueryString,
  parseListingId: () => parseListingId,
  pretty: () => pretty,
  readFilterFromURL: () => readFilterFromURL,
  readSortFromURL: () => readSortFromURL,
  readViewFromURL: () => readViewFromURL,
  recomputeComposite: () => recomputeComposite,
  scoreListing: () => scoreListing,
  tokenize: () => tokenize,
  zoneName: () => zoneName
});
module.exports = __toCommonJS(api_core_exports);

// shared/version.ts
var API_VERSION = "v1";

// shared/listing-id.ts
var ID_SEPARATOR = "__";
var SAFE_ID_RE = /^[A-Za-z0-9._%-]+$/;
function buildListingId(source, sourceId) {
  if (typeof source !== "string" || typeof sourceId !== "string") return null;
  const s = source.trim();
  const sid = sourceId.trim();
  if (!s || !sid) return null;
  if (!SAFE_ID_RE.test(s) || !SAFE_ID_RE.test(sid)) return null;
  return `${s}${ID_SEPARATOR}${sid}`;
}
function parseListingId(id) {
  if (typeof id !== "string") return null;
  const trimmed = id.trim();
  if (!trimmed || trimmed.length > 200) return null;
  const at = trimmed.indexOf(ID_SEPARATOR);
  if (at <= 0) return null;
  const source = trimmed.slice(0, at);
  const sourceId = trimmed.slice(at + ID_SEPARATOR.length);
  if (!source || !sourceId) return null;
  if (!SAFE_ID_RE.test(source) || !SAFE_ID_RE.test(sourceId)) return null;
  return { source, sourceId };
}
function isListingId(id) {
  return parseListingId(id) !== null;
}

// shared/zones.ts
var ZONE_NAMES = {
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
  "la-union": "La Uni\xF3n",
  "lago-coatepeque": "Lago de Coatepeque",
  "lago-ilopango": "Lago de Ilopango",
  "costa-del-sol": "Costa del Sol"
};
function pretty(slug, lookup) {
  if (!slug) return "\u2014";
  if (lookup[slug]) return lookup[slug];
  return slug.replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
function zoneName(slug) {
  return pretty(slug, ZONE_NAMES);
}

// shared/decode-html.ts
var ENTITIES = {
  amp: "&",
  lt: "<",
  gt: ">",
  quot: '"',
  apos: "'",
  nbsp: " ",
  aacute: "\xE1",
  Aacute: "\xC1",
  eacute: "\xE9",
  Eacute: "\xC9",
  iacute: "\xED",
  Iacute: "\xCD",
  oacute: "\xF3",
  Oacute: "\xD3",
  uacute: "\xFA",
  Uacute: "\xDA",
  ntilde: "\xF1",
  Ntilde: "\xD1",
  uuml: "\xFC",
  Uuml: "\xDC",
  iexcl: "\xA1",
  iquest: "\xBF",
  ordm: "\xBA",
  ordf: "\xAA",
  middot: "\xB7",
  hellip: "\u2026",
  ndash: "\u2013",
  mdash: "\u2014",
  lsquo: "'",
  rsquo: "'",
  ldquo: "\u201C",
  rdquo: "\u201D"
};
var TAG_RE = /<\/?[a-z][^>]*>/gi;
var ENTITY_RE = /&([a-zA-Z]+|#\d+);/g;
function decodeHtmlEntities(input) {
  if (!input) return "";
  let s = input.replace(ENTITY_RE, (match, body) => {
    if (body.startsWith("#")) {
      const code = parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return ENTITIES[body] ?? match;
  });
  s = s.replace(ENTITY_RE, (match, body) => {
    if (body.startsWith("#")) {
      const code = parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    return ENTITIES[body] ?? match;
  });
  s = s.replace(TAG_RE, " ");
  return s.replace(/\s+/g, " ").trim();
}

// shared/adapt/listing.ts
var VALID_MASTER_CATEGORIES = /* @__PURE__ */ new Set(["beach", "lake"]);
var VALID_SUBCATEGORIES = /* @__PURE__ */ new Set(["homes", "condos", "land"]);
var VALID_DISCOVERY_TAGS = /* @__PURE__ */ new Set([
  "top_rated",
  "under_250k",
  "gated",
  "waterfront"
]);
function adaptDiscoveryTags(raw) {
  if (!Array.isArray(raw)) return [];
  const out = [];
  for (const t of raw) {
    if (typeof t === "string" && VALID_DISCOVERY_TAGS.has(t)) {
      out.push(t);
    }
  }
  return out;
}
var OFF_MARKET_SOURCES = /* @__PURE__ */ new Set(["whatsapp", "facebook", "private"]);
var SOURCE_LABELS = {
  goodlife: "Goodlife",
  oceanside: "Oceanside",
  century21: "Century 21",
  bienesraices: "Bienes Ra\xEDces",
  remax: "RE/MAX",
  nexo: "Nexo",
  realtyelsalvador: "Realty El Salvador"
};
function deriveSourceType(source) {
  return OFF_MARKET_SOURCES.has(source) ? "off_market" : "on_market";
}
var _ES_DIACRITICS = /[áéíóúñ¿¡ü]/i;
var _ES_STOP = /* @__PURE__ */ new Set([
  "de",
  "en",
  "con",
  "para",
  "por",
  "del",
  "una",
  "un",
  "y",
  "se",
  "su",
  "al",
  "casa",
  "terreno",
  "playa",
  "mar",
  "vista",
  "venta",
  "frente",
  "cerca",
  "lote",
  "lujo",
  "apartamento",
  "sobre"
]);
var _EN_STOP = /* @__PURE__ */ new Set([
  "the",
  "for",
  "with",
  "and",
  "sale",
  "lot",
  "house",
  "home",
  "beach",
  "beachfront",
  "ocean",
  "oceanfront",
  "view",
  "near",
  "front",
  "land",
  "of",
  "in",
  "on",
  "to",
  "luxury",
  "apartment",
  "condo"
]);
function detectListingLang(text) {
  if (!text || !text.trim()) return "es";
  if (_ES_DIACRITICS.test(text)) return "es";
  const words = text.toLowerCase().match(/[a-záéíóúñü]+/gi) || [];
  if (words.length === 0) return "es";
  let es = 0;
  let en = 0;
  for (const w of words) {
    if (_ES_STOP.has(w)) es++;
    if (_EN_STOP.has(w)) en++;
  }
  return en > es ? "en" : "es";
}
function daysSince(iso) {
  if (!iso) return null;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return null;
  const ms = Date.now() - t;
  return Math.max(0, Math.floor(ms / 864e5));
}
function deriveLandType(raw, propertyType) {
  const v = raw?.land_type;
  if (v === "commercial" || v === "tourist" || v === "residential") {
    return v;
  }
  if (propertyType === "land" || propertyType === "house" || propertyType === "condo" || propertyType === "apartment") {
    return "residential";
  }
  return null;
}
function deriveBeachfrontTier(isBeachfront, tier) {
  if (tier === "on_beach" || tier === "walk_to_beach" || tier === "near_beach") {
    return tier;
  }
  if (tier === "oceanfront") return "on_beach";
  return isBeachfront ? "near_beach" : null;
}
function deriveRoadAccess(hasPaved, type) {
  if (type === "paved" || type === "gravel" || type === "dirt") return type;
  if (hasPaved) return "paved";
  return "unknown";
}
function buildPhotos(raw) {
  const urls = Array.isArray(raw.photo_urls) ? raw.photo_urls : [];
  const rejected = Array.isArray(raw.photo_urls_rejected) ? new Set(raw.photo_urls_rejected.filter((u) => typeof u === "string")) : null;
  const out = [];
  for (const u of urls) {
    if (typeof u !== "string") continue;
    if (rejected && rejected.has(u)) continue;
    if (out.length === 0 || u !== out[out.length - 1]) out.push(u);
  }
  const selected = typeof raw.selected_photo_url === "string" && raw.selected_photo_url.length > 0 ? raw.selected_photo_url : null;
  if (selected) {
    const idx = out.indexOf(selected);
    if (idx > 0) {
      out.splice(idx, 1);
      out.unshift(selected);
    } else if (idx < 0 && urls.includes(selected)) {
      out.unshift(selected);
    }
  }
  return out;
}
function adaptListing(raw, country) {
  const sourceKey = String(raw.source ?? "unknown");
  const sourceId = String(raw.source_id ?? "");
  const id = sourceKey && sourceId ? `${sourceKey}__${sourceId}` : `pulpo__${Math.random().toString(36).slice(2)}`;
  const sourceType = raw.source_type === "off_market" || raw.source_type === "on_market" ? raw.source_type : deriveSourceType(sourceKey);
  const sourceLabel = sourceType === "off_market" ? "" : SOURCE_LABELS[sourceKey] ?? sourceKey.replace(/^\w/, (c) => c.toUpperCase());
  const urlLanguage = raw.url_language === "en" || raw.url_language === "es" || raw.url_language === "mixed" ? raw.url_language : null;
  const contentLang = urlLanguage === "es" ? "es" : urlLanguage === "en" || urlLanguage === "mixed" ? "en" : detectListingLang(typeof raw.title === "string" ? raw.title : "");
  const localizedFromAny = (canonical, legacy) => {
    if (canonical && typeof canonical === "object") {
      const en = typeof canonical.en === "string" ? canonical.en : "";
      const es = typeof canonical.es === "string" ? canonical.es : "";
      if (en || es) {
        const out = { en };
        if (es) out.es = es;
        return out;
      }
    }
    const single = typeof canonical === "string" && canonical.length > 0 ? canonical : typeof legacy === "string" && legacy.length > 0 ? legacy : "";
    if (!single) return { en: "" };
    return contentLang === "es" ? { en: "", es: single } : { en: single };
  };
  const titleLocalized = localizedFromAny(raw.title_canonical, raw.title);
  if (!titleLocalized.en && !titleLocalized.es) {
    titleLocalized.en = "Untitled";
    titleLocalized.es = "Sin t\xEDtulo";
  }
  const descLegacy = typeof raw.description === "string" ? decodeHtmlEntities(raw.description).replace(/\s+/g, " ").trim() : void 0;
  const descLocalized = localizedFromAny(raw.short_description_canonical, descLegacy);
  const usps = Array.isArray(raw.reasons_to_buy) ? raw.reasons_to_buy.map((s) => {
    if (s && typeof s === "object") {
      const en = typeof s.en === "string" ? s.en : "";
      const es = typeof s.es === "string" ? s.es : "";
      if (en || es) {
        const out = { en };
        if (es) out.es = es;
        return out;
      }
      return null;
    }
    if (typeof s === "string" && s.length > 0) {
      return contentLang === "es" ? { en: "", es: s } : { en: s };
    }
    return null;
  }).filter((u) => u !== null && ((u.en?.trim().length ?? 0) > 0 || (u.es?.trim().length ?? 0) > 0)) : [];
  const isBeachfront = Boolean(raw.is_beachfront);
  const photos = buildPhotos(raw);
  const department = typeof raw.department === "string" ? raw.department : null;
  return {
    id,
    title: titleLocalized,
    description: descLocalized,
    usps,
    url_language: urlLanguage,
    zone_name: pretty(raw.zone, ZONE_NAMES),
    region: department,
    country: typeof raw.country === "string" ? raw.country : country.code,
    province_state: department ? `${department}, ${country.name_en}` : country.name_en,
    land_type: deriveLandType(raw, typeof raw.property_type === "string" ? raw.property_type : null),
    size_m2: typeof raw.area_m2 === "number" ? raw.area_m2 : null,
    price: typeof raw.price_usd === "number" ? raw.price_usd : null,
    previous_price: typeof raw.previous_price === "number" ? raw.previous_price : null,
    price_per_m2: typeof raw.price_per_m2 === "number" ? raw.price_per_m2 : null,
    // Zone-relative price context — drives the detail-page PriceContextBlock.
    // All seven fields are nullable; the block degrades gracefully when any
    // are missing (sparse zones, fresh scrapes, incomplete listings).
    zone: typeof raw.zone === "string" ? raw.zone : null,
    zone_percentile: typeof raw.zone_percentile === "number" ? raw.zone_percentile : null,
    price_vs_zone_median: typeof raw.price_vs_zone_median === "number" ? raw.price_vs_zone_median : null,
    price_vs_zone_pct: typeof raw.price_vs_zone_pct === "number" ? raw.price_vs_zone_pct : null,
    zone_price_per_m2_min: typeof raw.zone_price_per_m2_min === "number" ? raw.zone_price_per_m2_min : null,
    zone_price_per_m2_max: typeof raw.zone_price_per_m2_max === "number" ? raw.zone_price_per_m2_max : null,
    zone_comp_count: typeof raw.zone_comp_count === "number" ? raw.zone_comp_count : null,
    zone_comparison_scope: raw.zone_comparison_scope === "zone" || raw.zone_comparison_scope === "macro" || raw.zone_comparison_scope === "country" ? raw.zone_comparison_scope : null,
    photos,
    thumbnail_url: typeof raw.hero_photo_path === "string" && raw.hero_photo_path.length > 0 ? raw.hero_photo_path : null,
    photos_count: typeof raw.photos_count === "number" ? raw.photos_count : photos.length,
    hero_photo_quality_score: typeof raw.hero_photo_quality_score === "number" ? raw.hero_photo_quality_score : null,
    has_text_overlay: typeof raw.has_text_overlay === "boolean" ? raw.has_text_overlay : null,
    // Image-enrichment flags. Defensive defaults (false) keep older
    // ranked.json records valid during the rollout window before the
    // first nightly populates the sidecars.
    hero_eligible: raw.hero_eligible === true,
    card_eligible: raw.card_eligible === true,
    first_seen_date: daysSince(raw.first_seen_at),
    // Source-of-truth listing age: comes from the scraper's parse of
    // the original posting's mod_dt. `null` means we couldn't extract
    // it from the source — DON'T conflate with 0 ("posted today"),
    // because 0 would falsely fire the "Nuevo" badge for stale
    // listings whose source date was unparseable.
    days_listed: typeof raw.days_listed === "number" ? raw.days_listed : null,
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
    dist_nearest_town_km: typeof raw.dist_nearest_town_km === "number" ? raw.dist_nearest_town_km : null,
    has_lat_lng: Number.isFinite(raw.lat) && Number.isFinite(raw.lng),
    // PR-5/WS4 — pass the raw coordinates through for the map view.
    // Clamp non-numbers to null so map read-sites can guard with hasCoords().
    lat: Number.isFinite(raw.lat) ? raw.lat : null,
    lng: Number.isFinite(raw.lng) ? raw.lng : null,
    geocoding_confidence: raw.geocoding_confidence === "high" || raw.geocoding_confidence === "medium" || raw.geocoding_confidence === "low" ? raw.geocoding_confidence : null,
    geocoding_source: raw.geocoding_source === "extracted" || raw.geocoding_source === "estimated" || raw.geocoding_source === "nominatim" ? raw.geocoding_source : null,
    geocoding_reference: typeof raw.geocoding_reference === "string" && raw.geocoding_reference.trim().length > 0 ? raw.geocoding_reference : null,
    existence_status: raw.existence_status === "confirmed_current" || raw.existence_status === "missing_recently" || raw.existence_status === "stale" ? raw.existence_status : null,
    is_sold: Boolean(raw.is_sold),
    original_url: sourceType === "on_market" && typeof raw.url === "string" ? raw.url : null,
    rank: typeof raw.rank === "number" ? raw.rank : null,
    rank_score: typeof raw.rank_score === "number" ? raw.rank_score : null,
    value_score: typeof raw.value_score === "number" ? raw.value_score : null,
    location_score: typeof raw.location_score === "number" ? raw.location_score : null,
    momentum_score: typeof raw.momentum_score === "number" ? raw.momentum_score : null,
    property_type: typeof raw.property_type === "string" ? raw.property_type : null,
    bedrooms: typeof raw.bedrooms === "number" ? raw.bedrooms : null,
    // Built-property facts (plan 010) — same graceful-null guard style
    // as bedrooms above. ranked.json carries these sparsely today;
    // plan 009/011 raise coverage and the tiles light up as data lands.
    bathrooms: typeof raw.bathrooms === "number" ? raw.bathrooms : null,
    built_area_m2: typeof raw.built_area_m2 === "number" ? raw.built_area_m2 : null,
    year_built: typeof raw.year_built === "number" ? raw.year_built : null,
    year_renovated: typeof raw.year_renovated === "number" ? raw.year_renovated : null,
    parking_spaces: typeof raw.parking_spaces === "number" ? raw.parking_spaces : null,
    floor: typeof raw.floor === "number" ? raw.floor : null,
    hoa_fee_usd_monthly: typeof raw.hoa_fee_usd_monthly === "number" ? raw.hoa_fee_usd_monthly : null,
    furnished: typeof raw.furnished === "boolean" ? raw.furnished : null,
    has_pool: typeof raw.has_pool === "boolean" ? raw.has_pool : null,
    // IA-axis fields. During the rollout window, ranked.json may not
    // yet carry them — graceful nulls keep the legacy homepage code
    // working unchanged while the backend catches up.
    master_category: typeof raw.master_category === "string" && VALID_MASTER_CATEGORIES.has(raw.master_category) ? raw.master_category : null,
    subcategory: typeof raw.subcategory === "string" && VALID_SUBCATEGORIES.has(raw.subcategory) ? raw.subcategory : null,
    discovery_tags: adaptDiscoveryTags(raw.discovery_tags),
    star_rating: typeof raw.star_rating === "number" ? raw.star_rating : 0,
    // Backend writes `is_incomplete` directly. Fallback derives from
    // the same rule client-side so the FE stays correct during the
    // rollout window before the first nightly emits the flag.
    is_incomplete: typeof raw.is_incomplete === "boolean" ? raw.is_incomplete : raw.price_usd == null || raw.area_m2 == null
  };
}

// shared/engine/search.ts
function tokenize(query) {
  if (!query) return [];
  return foldAscii(query).split(/\s+/).map((tok) => tok.trim()).filter(Boolean);
}
function matchesQuery(listing, tokens) {
  if (!tokens || tokens.length === 0) return true;
  if (!listing) return false;
  const haystack = buildHaystack(listing);
  for (const tok of tokens) {
    if (!haystack.includes(tok)) return false;
  }
  return true;
}
function matchesQueryString(listing, query) {
  return matchesQuery(listing, tokenize(query));
}
var FIELD_WEIGHTS = { title: 3, zone: 2, source: 1 };
function haystackFields(listing) {
  return [
    { weight: FIELD_WEIGHTS.title, text: listing.title?.en },
    { weight: FIELD_WEIGHTS.title, text: listing.title?.es },
    { weight: FIELD_WEIGHTS.zone, text: listing.zone_name },
    { weight: FIELD_WEIGHTS.zone, text: listing.province_state },
    { weight: FIELD_WEIGHTS.source, text: listing.id },
    { weight: FIELD_WEIGHTS.source, text: listing.source_id },
    { weight: FIELD_WEIGHTS.source, text: listing.source_label },
    { weight: FIELD_WEIGHTS.source, text: listing.original_url },
    // PR-4 — prose recall, weighted lowest so it never outranks a title
    // or zone hit. usps is an array of Localized; flatten both locales.
    { weight: FIELD_WEIGHTS.source, text: listing.description?.en },
    { weight: FIELD_WEIGHTS.source, text: listing.description?.es },
    ...(Array.isArray(listing.usps) ? listing.usps : []).flatMap((u) => [
      { weight: FIELD_WEIGHTS.source, text: u?.en },
      { weight: FIELD_WEIGHTS.source, text: u?.es }
    ])
  ];
}
function buildHaystack(listing) {
  return foldAscii(
    haystackFields(listing).map((f) => f.text).filter(Boolean).join(" ")
  );
}
function scoreListing(listing, tokens) {
  if (!tokens || tokens.length === 0) return 0;
  if (!listing) return 0;
  const fields = haystackFields(listing).map((f) => ({ weight: f.weight, text: f.text ? foldAscii(f.text) : "" })).filter((f) => f.text);
  let score = 0;
  for (const tok of tokens) {
    const boundary = new RegExp(`\\b${escapeRegExp(tok)}`);
    for (const f of fields) {
      if (f.text.includes(tok)) {
        score += f.weight;
        if (boundary.test(f.text)) score += 1;
      }
    }
  }
  return score;
}
function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}
function buildSuggestions(query, listings, opts) {
  const max = opts?.max ?? 8;
  const locale = opts?.locale ?? "en";
  const folded = query ? foldAscii(query.trim()) : "";
  if (folded.length < 2) return [];
  if (!Array.isArray(listings) || listings.length === 0) return [];
  const tokens = tokenize(query);
  const zoneCounts = /* @__PURE__ */ new Map();
  const ltCounts = /* @__PURE__ */ new Map();
  for (const l of listings) {
    if (!l) continue;
    const zn = l.zone_name;
    if (zn && foldAscii(zn).includes(folded)) {
      zoneCounts.set(zn, (zoneCounts.get(zn) ?? 0) + 1);
    }
    const lt = l.land_type;
    if (lt) {
      const label = opts?.landTypeLabel ? opts.landTypeLabel(lt) : lt;
      if (foldAscii(label).includes(folded) || foldAscii(lt).includes(folded)) {
        ltCounts.set(lt, (ltCounts.get(lt) ?? 0) + 1);
      }
    }
  }
  const zoneSugs = [...zoneCounts.entries()].sort((a, b) => b[1] - a[1]).map(([value, count]) => ({ kind: "zone", value, count }));
  const ltSugs = [...ltCounts.entries()].sort((a, b) => b[1] - a[1]).map(([value, count]) => ({
    kind: "land_type",
    value,
    label: opts?.landTypeLabel ? opts.landTypeLabel(value) : value,
    count
  }));
  const titleSugs = [];
  if (tokens.length > 0) {
    const scored = listings.map((l) => ({ l, s: scoreListing(l, tokens) })).filter((x) => x.s > 0).sort((a, b) => b.s - a.s);
    const seen = /* @__PURE__ */ new Set();
    for (const { l } of scored) {
      if (titleSugs.length >= 5) break;
      const title = (l.title?.[locale] || l.title?.en || l.title?.es || "").trim();
      if (!title) continue;
      const key = foldAscii(title);
      if (seen.has(key)) continue;
      seen.add(key);
      titleSugs.push({
        kind: "title",
        value: title,
        listingId: l.id,
        listing: l
      });
    }
  }
  return [...zoneSugs, ...ltSugs, ...titleSugs].slice(0, max);
}
var COMBINING_DIACRITICS_RE = /[̀-ͯ]/g;
function foldAscii(s) {
  return s.normalize("NFD").replace(COMBINING_DIACRITICS_RE, "").toLowerCase();
}

// shared/engine/filters.ts
var WEIGHT_DEFAULTS = { value: 40, location: 35, momentum: 25 };
function makeDefaultFilters() {
  return {
    zones: /* @__PURE__ */ new Set(),
    land_types: /* @__PURE__ */ new Set(),
    features: /* @__PURE__ */ new Set(),
    infra: /* @__PURE__ */ new Set(),
    status: /* @__PURE__ */ new Set(),
    price_min: 0,
    // null = no upper cap. The previous default of 1,000,000 silently
    // hid every listing above $1M (~20% of the catalog) — Browse
    // counted ~700 while LiveStats correctly reported 873. Bug fix.
    price_max: null,
    size_min: 0,
    // null = no upper cap, mirroring price_max. Number inputs accept any
    // value; the 20k m² visual scale is only a legibility choice.
    size_max: null,
    readiness: 0,
    // PR-4b — feature parity with legacy:
    score_min: 0,
    // 0–100 score floor
    weights: { ...WEIGHT_DEFAULTS },
    // V/L/M weights, sum = 100
    photos: "all",
    // "all" | "with" | "none"
    // Rewrite Phase 5B — new IA filter axes (Beach/Lake × Homes/
    // Condos/Land + 4 discovery tags). The homepage CategoryGrid /
    // DiscoveryPills navigate here with these pre-set via
    // buildFiltersForCategory.
    master_category: null,
    // "beach" | "lake" | null
    subcategory: null,
    // "homes" | "condos" | "land" | null
    discovery_tags: /* @__PURE__ */ new Set(),
    // subset of {top_rated, under_250k, gated, waterfront}
    rank_max: null,
    // position-rank cap; e.g. 10 for "Top 10" chip
    // Inverse-semantic toggle. Defaults to false → listings where the
    // broker hasn't shared price or size are hidden. Toggling on
    // surfaces them at the bottom of the result set (ranker already
    // hard-floored them, so the order is correct without extra work).
    include_incomplete: false,
    // Free-text exact-lookup search (web/app/lib/search-match.ts). The
    // user types a Pulpo id, broker URL, zone, or title fragment;
    // every whitespace-separated token must hit somewhere in the
    // listing's haystack. Empty = match-all (no-op).
    query: ""
  };
}
function recomputeComposite(l, w) {
  if (!w) return l.rank_score ?? 0;
  if (w.value === WEIGHT_DEFAULTS.value && w.location === WEIGHT_DEFAULTS.location && w.momentum === WEIGHT_DEFAULTS.momentum) {
    return l.rank_score ?? 0;
  }
  const v = l.value_score ?? 0;
  const ll = l.location_score ?? 0;
  const m = l.momentum_score ?? 0;
  const total = w.value + w.location + w.momentum;
  if (total <= 0) return 0;
  return (v * w.value + ll * w.location + m * w.momentum) / total;
}
function buildTopRankMap(listings, n = 10) {
  const out = /* @__PURE__ */ new Map();
  const ranked = [...listings].filter((l) => !l.is_sold && l.rank_score != null).sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0)).slice(0, n);
  ranked.forEach((l, i) => out.set(l.id, i + 1));
  return out;
}
function applyFilters(listings, f, opts) {
  const skip = opts && opts.skip;
  const queryTokens = tokenize(f && f.query);
  return listings.filter((l) => {
    if (l.is_sold) return false;
    if (l.is_incomplete && !f.include_incomplete) return false;
    if (f.zones.size && !f.zones.has(l.zone_name)) return false;
    if (f.land_types.size && !f.land_types.has(l.land_type)) return false;
    if (skip !== "price") {
      if (l.price < f.price_min) return false;
      if (f.price_max != null && l.price > f.price_max) return false;
    }
    if (skip !== "size") {
      if (l.size_m2 < f.size_min) return false;
      if (f.size_max != null && l.size_m2 > f.size_max) return false;
    }
    if (f.features.has("beachfront") && !l.beachfront_tier) return false;
    if (f.features.has("ocean_view") && !l.has_ocean_view) return false;
    if (f.features.has("mountain_view") && !l.has_mountain_view) return false;
    if (f.features.has("flat") && !l.is_flat) return false;
    if (f.features.has("water_body") && !l.has_water_body) return false;
    if (f.infra.has("water") && !l.has_water) return false;
    if (f.infra.has("power") && !l.has_power) return false;
    if (f.infra.has("paved") && l.road_access_type !== "paved") return false;
    if (f.infra.has("sewage") && !l.has_sewage) return false;
    if (f.status.has("new") && !(typeof l.first_seen_date === "number" && l.first_seen_date <= 7)) return false;
    if (f.status.has("price_drop") && !l.is_repriced) return false;
    if (f.status.has("off_market") && l.source_type !== "off_market") return false;
    if (f.status.has("motivated") && (typeof l.days_listed !== "number" || l.days_listed < 90)) return false;
    if (l.readiness_score < f.readiness) return false;
    if ((f.score_min ?? 0) > 0 && (l.rank_score ?? 0) < f.score_min) return false;
    if (f.photos === "with" && (l.photos_count ?? 0) === 0) return false;
    if (f.photos === "none" && (l.photos_count ?? 0) > 0) return false;
    if (f.master_category && l.master_category !== f.master_category) return false;
    if (f.subcategory && l.subcategory !== f.subcategory) return false;
    if (f.discovery_tags && f.discovery_tags.size > 0) {
      const tags = Array.isArray(l.discovery_tags) ? l.discovery_tags : [];
      for (const required of f.discovery_tags) {
        if (!tags.includes(required)) return false;
      }
    }
    if (queryTokens.length > 0 && !matchesQuery(l, queryTokens)) return false;
    return true;
  });
}
function applyRankCap(listings, rank_max) {
  if (rank_max == null || rank_max <= 0) return listings;
  return [...listings].filter((l) => l.rank_score != null).sort((a, b) => (b.rank_score ?? 0) - (a.rank_score ?? 0)).slice(0, rank_max);
}

// shared/engine/params.ts
var VALID_MASTER = /* @__PURE__ */ new Set(["beach", "lake"]);
var VALID_SUB = /* @__PURE__ */ new Set(["homes", "condos", "land"]);
var VALID_TAGS = /* @__PURE__ */ new Set([
  "top_rated",
  "under_250k",
  "gated",
  "waterfront"
]);
var PRICE_HISTO_MAX = 1e6;
function parseSet(value) {
  if (!value) return /* @__PURE__ */ new Set();
  return new Set(value.split(",").map((s) => s.trim()).filter(Boolean));
}
function parseInt0(value, fallback) {
  if (value == null) return fallback;
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? n : fallback;
}
function parseCapOrNull(value) {
  if (value == null) return null;
  const n = parseInt(value, 10);
  return Number.isFinite(n) ? n : null;
}
function parseMaster(value) {
  if (!value) return null;
  return VALID_MASTER.has(value) ? value : null;
}
function parseSub(value) {
  if (!value) return null;
  return VALID_SUB.has(value) ? value : null;
}
function parseTags(value) {
  const raw = parseSet(value);
  const out = /* @__PURE__ */ new Set();
  raw.forEach((t) => {
    if (VALID_TAGS.has(t)) out.add(t);
  });
  return out;
}
var FILTER_URL_KEYS = [
  "zones",
  "types",
  "features",
  "infra",
  "status",
  "pmin",
  "pmax",
  "smin",
  "smax",
  "ready",
  "master",
  "sub",
  "tag",
  "rmax"
];
function hasFilterParamsInURL(search) {
  const p = new URLSearchParams(search);
  return FILTER_URL_KEYS.some((k) => p.has(k));
}
function readFilterFromURL(search, baseDefaults) {
  const p = new URLSearchParams(search);
  const masterFromUrl = parseMaster(p.get("master"));
  const subFromUrl = parseSub(p.get("sub"));
  const tagsFromUrl = parseTags(p.get("tag"));
  const out = {
    ...baseDefaults,
    zones: parseSet(p.get("zones")),
    land_types: parseSet(p.get("types")),
    features: parseSet(p.get("features")),
    infra: parseSet(p.get("infra")),
    status: parseSet(p.get("status")),
    price_min: parseInt0(p.get("pmin"), 0),
    price_max: parseCapOrNull(p.get("pmax")),
    size_min: parseInt0(p.get("smin"), 0),
    size_max: parseCapOrNull(p.get("smax")),
    readiness: parseInt0(p.get("ready"), 0),
    master_category: masterFromUrl ?? baseDefaults.master_category,
    subcategory: subFromUrl ?? baseDefaults.subcategory,
    discovery_tags: tagsFromUrl.size > 0 ? tagsFromUrl : baseDefaults.discovery_tags,
    rank_max: p.get("rmax") != null ? parseInt0(p.get("rmax"), 0) : baseDefaults.rank_max,
    include_incomplete: p.get("inc") === "1" ? true : baseDefaults.include_incomplete,
    query: (p.get("q") ?? baseDefaults.query ?? "").slice(0, 200)
  };
  const sm = p.get("score_min");
  if (sm != null) out.score_min = parseInt0(sm, 0);
  const wv = p.get("wv");
  const wl = p.get("wl");
  const wm = p.get("wm");
  if (wv && wl && wm) {
    out.weights = {
      value: parseInt0(wv, 40),
      location: parseInt0(wl, 35),
      momentum: parseInt0(wm, 25)
    };
  }
  return out;
}
function readSortFromURL(search, fallback) {
  const p = new URLSearchParams(search);
  return p.get("sort") || fallback;
}
var VALID_VIEWS = /* @__PURE__ */ new Set(["cards", "table", "map"]);
function readViewFromURL(search, fallback) {
  const p = new URLSearchParams(search);
  const v = p.get("view");
  return v && VALID_VIEWS.has(v) ? v : fallback;
}
// Annotate the CommonJS export names for ESM import in node:
0 && (module.exports = {
  API_VERSION,
  FILTER_URL_KEYS,
  ID_SEPARATOR,
  PRICE_HISTO_MAX,
  WEIGHT_DEFAULTS,
  ZONE_NAMES,
  adaptListing,
  applyFilters,
  applyRankCap,
  buildListingId,
  buildSuggestions,
  buildTopRankMap,
  decodeHtmlEntities,
  detectListingLang,
  hasFilterParamsInURL,
  isListingId,
  makeDefaultFilters,
  matchesQuery,
  matchesQueryString,
  parseListingId,
  pretty,
  readFilterFromURL,
  readSortFromURL,
  readViewFromURL,
  recomputeComposite,
  scoreListing,
  tokenize,
  zoneName
});
