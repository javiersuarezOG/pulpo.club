// Pulpo — bilingual mock data.
//
// SHAPE CHANGE (vs. v1):
//   Previously: title: "Titled oceanfront acreage..."        (string)
//   Now:        title: { en: "...", es: "..." }              (translatable field)
//
// Translatable fields:  title, description, usps[]
// Non-translatable:     id, price, size_m2, photos, dates, flags, source_label
//
// In a real app this shape is what a headless CMS (Sanity / Contentful /
// Payload / Storyblok) returns natively for a "localized" field. The frontend
// reads it through `tr(value, locale)` — see i18n.jsx.
//
// FIVE listings (#1, #2, #11, #21, #31) get FULL Spanish translations so you
// can see real bilingual content side-by-side. The rest fall back to English
// gracefully via `tr()`'s default-locale handling — exactly what would happen
// in a CMS where translators haven't filled in `es` yet.

// All current inventory is in El Salvador. The schema keeps `country` as
// ISO 3166 alpha-2 so adding a second country later is a data change, not a
// refactor.
const ZONES = [
  { name: "Surf City",        region: "La Libertad",   country: "SV" },
  { name: "El Tunco",         region: "La Libertad",   country: "SV" },
  { name: "El Zonte",         region: "La Libertad",   country: "SV" },
  { name: "Playa El Cuco",    region: "San Miguel",    country: "SV" },
  { name: "Punta Mango",      region: "Usulután",      country: "SV" },
  { name: "Conchagua",        region: "La Unión",      country: "SV" },
  { name: "Suchitoto",        region: "Cuscatlán",     country: "SV" },
  { name: "Ataco",            region: "Ahuachapán",    country: "SV" },
  { name: "Lago de Coatepeque", region: "Santa Ana",   country: "SV" },
  { name: "Juayúa",           region: "Sonsonate",     country: "SV" },
];

const COUNTRY_NAMES = {
  SV: { en: "El Salvador", es: "El Salvador" },
};

// Curated Unsplash photos (land/ocean/jungle/farm) — direct CDN URLs
const PHOTO_POOLS = {
  beachfront: [
    "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1400&q=80",
    "https://images.unsplash.com/photo-1519046904884-53103b34b206?w=1400&q=80",
    "https://images.unsplash.com/photo-1439066615861-d1af74d74000?w=1400&q=80",
    "https://images.unsplash.com/photo-1473116763249-2faaef81ccda?w=1400&q=80",
  ],
  oceanview: [
    "https://images.unsplash.com/photo-1505142468610-359e7d316be0?w=1400&q=80",
    "https://images.unsplash.com/photo-1507525428034-b723cf961d3e?w=1400&q=80",
    "https://images.unsplash.com/photo-1518837695005-2083093ee35b?w=1400&q=80",
    "https://images.unsplash.com/photo-1502082553048-f009c37129b9?w=1400&q=80",
  ],
  jungle: [
    "https://images.unsplash.com/photo-1448375240586-882707db888b?w=1400&q=80",
    "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?w=1400&q=80",
    "https://images.unsplash.com/photo-1426604966848-d7adac402bff?w=1400&q=80",
    "https://images.unsplash.com/photo-1518495973542-4542c06a5843?w=1400&q=80",
  ],
  mountain: [
    "https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=1400&q=80",
    "https://images.unsplash.com/photo-1506905925346-21bda4d32df4?w=1400&q=80",
    "https://images.unsplash.com/photo-1469474968028-56623f02e42e?w=1400&q=80",
  ],
  farm: [
    "https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=1400&q=80",
    "https://images.unsplash.com/photo-1444858345857-ffaf64d3d6e1?w=1400&q=80",
    "https://images.unsplash.com/photo-1464226184884-fa280b87c399?w=1400&q=80",
  ],
  flat: [
    "https://images.unsplash.com/photo-1500382017468-9049fed747ef?w=1400&q=80",
    "https://images.unsplash.com/photo-1473773508845-188df298d2d1?w=1400&q=80",
  ],
};

const SOURCES = [
  { id: "encuentra24", label: "Encuentra24" },
  { id: "facebook",    label: "Facebook" },
  { id: "whatsapp",    label: "WhatsApp" },
  { id: "remax",       label: "RE/MAX" },
  { id: "private",     label: "Private" },
];

// Translatable titles. en + es where translated, en-only otherwise.
const TITLES = [
  { en: "Titled oceanfront acreage with mature teak forest",
    es: "Hectáreas tituladas frente al mar con bosque de teca maduro" },
  { en: "Build-ready hilltop with 270° Pacific Ocean view",
    es: "Cima lista para construir con vista 270° al Océano Pacífico" },
  { en: "Flat agricultural parcel on year-round river" },
  { en: "Beach-access lot in gated tourism community" },
  { en: "Off-grid mountain retreat with natural spring" },
  { en: "Subdividable farm with paved road frontage" },
  { en: "Walking-distance-to-beach infill lot" },
  { en: "Coffee farm with renovated farmhouse" },
  { en: "Commercial corner lot on highway" },
  { en: "Jungle parcel with creek and waterfall" },
  { en: "White-sand beachfront with coral reef break",
    es: "Playa de arena blanca con rompiente sobre arrecife de coral" },
  { en: "Titled tourism-zoned lot near surf break" },
  { en: "Highland coffee land with sweeping views" },
  { en: "Rolling pasture with three water sources" },
  { en: "Eco-community lot with shared solar grid" },
  { en: "Small finca with fruit orchard and well" },
  { en: "Headland acreage above protected cove" },
  { en: "Riverfront homestead with established garden" },
  { en: "Buildable mesa lot with utilities at boundary" },
  { en: "Working cattle ranch with two seasonal creeks" },
  { en: "Premium beachfront with development permits",
    es: "Frente de playa premium con permisos de desarrollo" },
  { en: "Hidden valley parcel between two waterfalls" },
  { en: "Tourism-titled lot in established surf town" },
  { en: "Productive teak plantation with road access" },
];

// Translatable USPs.
const USPS = [
  { en: "Titled and surveyed — clean property records",
    es: "Titulado y mensurado — registros limpios" },
  { en: "Paved road right to the property boundary",
    es: "Carretera asfaltada hasta el lindero" },
  { en: "Year-round water from natural spring on site",
    es: "Agua todo el año de manantial natural en el sitio" },
  { en: "Power and fiber internet at the road",
    es: "Electricidad e internet por fibra en la calle" },
  { en: "Owner financing available with 30% down",
    es: "Financiamiento del dueño con 30% de enganche" },
  { en: "Walk to beach in under 10 minutes",
    es: "A menos de 10 minutos caminando de la playa" },
  { en: "Adjacent parcels available for assembly" },
  { en: "Permits pre-approved for residential build",
    es: "Permisos pre-aprobados para construcción residencial" },
  { en: "Zoned for short-term rental and tourism use",
    es: "Zonificado para alquiler vacacional y uso turístico" },
  { en: "Mature shade trees and existing fruit orchard",
    es: "Árboles de sombra maduros y huerto de frutales" },
  { en: "Subdividable into 4 buildable lots" },
  { en: "Within 30 minutes of international airport",
    es: "A menos de 30 minutos del aeropuerto internacional" },
  { en: "Tax-friendly investor jurisdiction" },
  { en: "No flooding history per zone records" },
  { en: "Below recent comparable sales in zone",
    es: "Por debajo de ventas comparables recientes en la zona" },
  { en: "Quiet end-of-road location, no through traffic" },
  { en: "View deck site already cleared and graded" },
  { en: "Cell service and 4G coverage confirmed" },
  { en: "Surveyed boundaries marked with concrete",
    es: "Linderos mensurados marcados con concreto" },
  { en: "Mature secondary forest — eco credits eligible" },
];

const LAND_TYPES = ["residential", "agricultural", "commercial", "tourist", "mixed", "raw"];

function pick(arr, i) { return arr[i % arr.length]; }
function pickN(arr, seed, n) {
  const out = [];
  for (let i = 0; i < n; i++) out.push(arr[(seed * 7 + i * 13) % arr.length]);
  return out;
}
function rand(seed) {
  let x = Math.sin(seed) * 10000;
  return x - Math.floor(x);
}

// Build a translatable description from a title + 2 USPs.
function buildDescription(titleObj, zone, usps) {
  const country = COUNTRY_NAMES[zone.country].en;
  const en = `${titleObj.en} located in ${zone.name}, ${zone.region}, ${country}. ${usps[0].en} ${usps[1].en}`;
  const es = (titleObj.es && usps[0].es && usps[1].es)
    ? `${titleObj.es} ubicado en ${zone.name}, ${zone.region}, ${country}. ${usps[0].es} ${usps[1].es}`
    : undefined;
  return es ? { en, es } : { en };
}

const LISTINGS = Array.from({ length: 48 }, (_, i) => {
  const seed = i + 1;
  const zone = pick(ZONES, i * 3);
  const titleObj = TITLES[i % TITLES.length];
  const photoPools = Object.keys(PHOTO_POOLS);
  const pool = photoPools[i % photoPools.length];
  const photoCount = Math.floor(rand(seed) * 14) + (i % 5 === 0 ? 0 : 2);
  const photos = Array.from({ length: photoCount }, (_, j) => PHOTO_POOLS[pool][(i + j) % PHOTO_POOLS[pool].length]);
  const isBeachfront = pool === "beachfront";
  const hasOceanView = pool === "oceanview" || isBeachfront;
  const hasMountainView = pool === "mountain";
  const isFlat = pool === "flat" || pool === "farm" || rand(seed * 2) > 0.6;
  const hasWaterBody = pool === "jungle" || rand(seed * 3) > 0.7;
  const landType = isBeachfront ? "tourist"
    : pool === "farm" ? "agricultural"
    : i % 11 === 0 ? "commercial"
    : pick(LAND_TYPES, i);

  const sizeM2 = Math.round((1000 + rand(seed * 5) * 80000) / 100) * 100;
  const pricePerM2 = isBeachfront ? 80 + rand(seed * 7) * 250
    : hasOceanView ? 30 + rand(seed * 7) * 80
    : 5 + rand(seed * 7) * 35;
  const price = Math.round(sizeM2 * pricePerM2 / 1000) * 1000;

  const daysListed = Math.floor(rand(seed * 11) * 180);
  const isRepriced = rand(seed * 13) > 0.78;
  const sourceType = i % 9 === 0 ? "off_market" : "on_market";
  const source = sourceType === "off_market" ? SOURCES[2] : pick(SOURCES, i);
  const readinessScore = Math.min(4, Math.floor(rand(seed * 17) * 5));
  const hasWater = readinessScore >= 1 || rand(seed * 19) > 0.5;
  const hasPower = readinessScore >= 2 || rand(seed * 23) > 0.5;
  const roadAccessType = readinessScore >= 3 ? "paved" : rand(seed * 29) > 0.5 ? "gravel" : "dirt";

  const usps = pickN(USPS, seed, 3);                 // each entry is { en, es? }
  const previousPrice = isRepriced ? Math.round(price * (1 + 0.08 + rand(seed * 31) * 0.15) / 1000) * 1000 : null;
  const description = buildDescription(titleObj, zone, usps);

  return {
    id: `pulpo-${String(i + 1).padStart(4, "0")}`,
    // ↓↓↓ TRANSLATABLE FIELDS — { en, es? }
    title: titleObj,
    description,
    usps,                                            // array of { en, es? }
    // ↓↓↓ NON-TRANSLATABLE (universal across locales)
    zone_name: zone.name,
    region: zone.region,
    country: zone.country,                           // ISO 3166 alpha-2 — "SV" for now
    province_state: `${zone.region}, ${COUNTRY_NAMES[zone.country].en}`,
    land_type: landType,                             // string key — translated via t("type." + land_type)
    size_m2: sizeM2,
    price,
    previous_price: previousPrice,
    price_per_m2: Math.round(price / sizeM2 * 10) / 10,
    photos,
    photos_count: photos.length,
    first_seen_date: daysListed,
    days_listed: daysListed,
    is_repriced: isRepriced,
    source_type: sourceType,
    source_label: source.label,
    source_id: source.id,
    beachfront_tier: isBeachfront ? (i % 2 === 0 ? "oceanfront" : "beach_access") : null,
    has_ocean_view: hasOceanView,
    has_mountain_view: hasMountainView,
    has_water_body: hasWaterBody,
    is_flat: isFlat,
    has_water: hasWater,
    has_power: hasPower,
    has_sewage: rand(seed * 37) > 0.6,
    road_access_type: roadAccessType,
    readiness_score: readinessScore,
    zoning_use: landType === "commercial" ? "commercial" : landType === "agricultural" ? "agricultural" : "residential",
    dist_beach_km: isBeachfront ? 0 : Math.round(rand(seed * 41) * 30 * 10) / 10,
    dist_airport_km: Math.round(rand(seed * 43) * 80),
    dist_nearest_town_km: Math.round(rand(seed * 47) * 15 * 10) / 10,
    has_lat_lng: rand(seed * 53) > 0.4,
    is_sold: i === 30,
    original_url: sourceType === "on_market" ? `https://${source.id}.example.com/listing/${i}` : null,
  };
});

// Shelves and pills — labels are translatable too.
// All shelves use the same monochrome <Icon> set as the pill rail.
// `icon` is a key into the Icon component (see components.jsx).
// SHELVES — display copy layer.
// `key` and `filter` are the data contract (matches parent PRD §4.2 shelf keys).
// `label` and `subline` are UI strings only — edit freely without touching filters.
// Per addendum A.1: human-language headlines (3–7 words), optional sub-lines that earn their place.
const SHELVES = [
  { key: "new_this_week",    label: { en: "Fresh Off the Radar",          es: "Recién aparecidos" },           subline: { en: "This week's best additions, first.",                    es: "Lo mejor que entró esta semana, primero." },              icon: "cat_new",          filter: (l) => l.first_seen_date <= 7 },
  { key: "price_drops",      label: { en: "Just Got More Affordable",     es: "Acaban de bajar de precio" },   subline: { en: "Sellers are moving — here's your moment.",              es: "Los dueños se están moviendo — este es tu momento." },    icon: "cat_price_drop",   filter: (l) => l.is_repriced },
  { key: "off_market",       label: { en: "Before It Hits the Market",    es: "Antes de salir al mercado" },   subline: { en: "Quiet finds, for those paying attention.",              es: "Hallazgos discretos, para quien está atento." },          icon: "cat_off_market",   filter: (l) => l.source_type === "off_market" },
  { key: "best_documented",  label: { en: "Know Before You Buy",          es: "Conoce antes de comprar" },     subline: { en: "Full details, no surprises.",                           es: "Toda la información, sin sorpresas." },                   icon: "camera",           filter: (l) => l.photos_count >= 8 },
  { key: "beachfront",       label: { en: "Dreaming of a Beachfront Pad?",es: "¿Sueñas con frente al mar?" },  subline: { en: "Sand, ocean, and a proper terrace.",                    es: "Arena, mar y una buena terraza." },                       icon: "cat_beachfront",   filter: (l) => l.beachfront_tier !== null },
  { key: "ocean_view",       label: { en: "Wake Up to This",              es: "Despierta con esto" },          subline: { en: "The view that makes the decision for you.",             es: "La vista que decide por ti." },                           icon: "cat_ocean_view",   filter: (l) => l.has_ocean_view && !l.beachfront_tier },
  { key: "mountain_view",    label: { en: "Up in the Hills",              es: "Allá en las montañas" },        subline: { en: "Elevation, silence, and serious upside.",               es: "Altura, silencio y verdadero potencial." },               icon: "cat_mountain",     filter: (l) => l.has_mountain_view },
  { key: "water_features",   label: { en: "Something on the Water",       es: "Algo junto al agua" },          subline: { en: "River, creek, or lake — take your pick.",               es: "Río, quebrada o lago — tú eliges." },                     icon: "cat_water",        filter: (l) => l.has_water_body },
  { key: "flat_buildable",   label: { en: "Ready When You Are",           es: "Listo cuando tú lo estés" },    subline: { en: "Flat, clear, and waiting for your plans.",              es: "Plano, limpio y esperando tus planes." },                 icon: "cat_flat_land",    filter: (l) => l.is_flat },
  { key: "build_ready",      label: { en: "Plug In and Build",            es: "Conecta y construye" },         subline: { en: "Water, power, road — the hard part is done.",           es: "Agua, luz y carretera — lo difícil ya está." },           icon: "cat_build_ready",  filter: (l) => l.readiness_score >= 3 },
  { key: "commercial",       label: { en: "Think Bigger",                 es: "Piensa en grande" },            subline: { en: "Land zoned for what you have in mind.",                 es: "Propiedades zonificadas para lo que tienes en mente." },       icon: "cat_commercial",   filter: (l) => l.land_type === "commercial" },
  { key: "agricultural",     label: { en: "Back to the Land",             es: "Vuelta a la tierra" },          subline: { en: "Productive soil. Real long-term value.",                es: "Suelo productivo. Valor real a largo plazo." },           icon: "cat_agricultural", filter: (l) => l.land_type === "agricultural" },
  { key: "under_50k",        label: { en: "Under $50K — Seriously",       es: "Menos de $50K — en serio" },    subline: { en: "Entry-point land that doesn't feel like a compromise.", es: "Propiedades de entrada que no se sienten como sacrificio." },  icon: "cat_under_100k",   filter: (l) => l.price <= 50000 },
  { key: "under_100k",       label: { en: "Big Opportunity, Mid Budget",  es: "Gran oportunidad, presupuesto medio" }, subline: { en: "The $50K–$100K range is where the deals live.", es: "Entre $50K y $100K es donde viven las ofertas." },        icon: "cat_under_100k",   filter: (l) => l.price <= 100000 && l.price > 50000 },
  { key: "motivated_sellers",label: { en: "The Owner Is Ready to Talk",   es: "El dueño está listo para conversar" }, subline: { en: "Listed over 90 days — room to negotiate.",      es: "Más de 90 días publicado — espacio para negociar." },     icon: "cat_motivated",    filter: (l) => l.days_listed >= 90 },
];

// All pills use the same monochrome <Icon> set. Icons inherit currentColor
// from .pill-icon (CSS), which ties them to --accent — so changing the
// accent recolors every category icon site-wide automatically.
const PILLS = [
  { key: "new_this_week",  label: { en: "New",            es: "Nuevos" },               icon: "cat_new" },
  { key: "price_drops",    label: { en: "Price Drops",    es: "Bajó de precio" },       icon: "cat_price_drop" },
  { key: "beachfront",     label: { en: "Beachfront",     es: "Frente al mar" },        icon: "cat_beachfront" },
  { key: "ocean_view",     label: { en: "Ocean View",     es: "Vista al mar" },         icon: "cat_ocean_view" },
  { key: "build_ready",    label: { en: "Build-Ready",    es: "Listo para construir" }, icon: "cat_build_ready" },
  { key: "off_market",     label: { en: "Off-Market",     es: "Off-market" },           icon: "cat_off_market" },
  { key: "flat_buildable", label: { en: "Flat Land",      es: "Terreno plano" },        icon: "cat_flat_land" },
  { key: "water_features", label: { en: "Water Features", es: "Cuerpos de agua" },      icon: "cat_water" },
  { key: "mountain_view",  label: { en: "Mountain View",  es: "Vista a la montaña" },   icon: "cat_mountain" },
  { key: "under_100k",     label: { en: "Under $100K",    es: "Menos de $100K" },       icon: "cat_under_100k" },
  { key: "agricultural",   label: { en: "Agricultural",   es: "Agrícola" },             icon: "cat_agricultural" },
  { key: "commercial",     label: { en: "Commercial",     es: "Comercial" },            icon: "cat_commercial" },
];

export { LISTINGS, SHELVES, PILLS, ZONES, COUNTRY_NAMES };
