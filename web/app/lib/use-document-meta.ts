// Per-route document title + meta tags + canonical + hreflang.
//
// React's standard pattern is `react-helmet`; we don't pull that in for
// one hook. Instead, this hook directly mutates the live <head> on every
// route change. The mutations are idempotent — same path → same tags —
// so the React strict-mode double-invoke is fine.
//
// Why this exists:
// 1. SEO — Google ranks unique <title> + <meta name="description"> per
//    URL. Without this hook, every section shares the index.html shell's
//    static <title>.
// 2. Sharing — WhatsApp / Slack / Twitter / iMessage render OG tags. JS
//    crawlers (Googlebot in 2026) execute this hook; non-JS social
//    crawlers do not. Static stubs for /listing/:id are tracked as a
//    follow-up — see the section-urls plan.
// 3. Hreflang — gives Google explicit language alternates so the
//    Spanish-localized URL (`?lang=es`) ranks for Spanish queries
//    instead of being treated as duplicate content.

import { useLayoutEffect } from "react";
import type { Route } from "./url-routing";
import type { Listing } from "../data/types";
import { ACTIVE_COUNTRY } from "../config/countries";
import { findDocument } from "../config/legal-content";
import { CATEGORY_KEYS, type CategoryKey } from "./categories";

const SITE_NAME = "Pulpo";
// PR-MC-4 — every "El Salvador" / "Salvadoran" string below is now a
// read from ACTIVE_COUNTRY (the country selected at build time by
// VITE_PULPO_ACTIVE_COUNTRY, default "SV"). The literal strings here
// resolve to the SV deployment's copy when the active country is SV;
// switching the deployment's env var to a new country produces the
// matching localized copy automatically.
const COUNTRY_EN = ACTIVE_COUNTRY.name_en;
const COUNTRY_ES = ACTIVE_COUNTRY.name_es;
const COUNTRY_ADJECTIVE_EN = ACTIVE_COUNTRY.name_adjective_en ?? ACTIVE_COUNTRY.name_en;
// OG locale tag is `<lang>_<COUNTRY-CC>` — Open Graph spec uses
// `es_SV` shape, not BCP-47's `es-SV` hyphen form.
const OG_LOCALE_ES = `es_${ACTIVE_COUNTRY.code}`;
const OG_LOCALE_EN = `en_${ACTIVE_COUNTRY.code === "SV" ? "US" : ACTIVE_COUNTRY.code}`;

// Rewrite Phase 8 — homepage description now aligns with the new hero
// copy ("Every beach and lake home in {country}, ranked by value")
// while remaining accurate for the legacy homepage during the rollout
// window. Both versions surface beach + lake properties + a value
// ranking; the copy works regardless of which UI a SERP click lands on.
const SITE_DESCRIPTION_EN = `Every beach and lake home in ${COUNTRY_EN}, ranked by value. Browse hundreds of vetted beach and lake properties — and get the 10 best delivered to your inbox every week.`;
const SITE_DESCRIPTION_ES = `Cada casa de playa y lago en ${COUNTRY_ES}, ordenada por valor. Explora cientos de propiedades verificadas de playa y lago — y recibe las 10 mejores en tu correo cada semana.`;

// One real property image for sections; listing detail uses the listing's
// first photo. This path is also referenced from index.html's static OG
// tag for the cold-load path, so keep both in sync.
const BRAND_OG_IMAGE = "/photos/goodlife_newly-built-condo-with-partial-ocean-view-at-zonset-el-zonte-340000.hero.jpg";

const ORIGIN = (() => {
  if (typeof window === "undefined") return "https://pulpo.club";
  return window.location.origin;
})();

type Meta = {
  title: string;
  description: string;
  image: string;
  // Canonical URL (without `?lang=`, `?sort=…`, etc.). For Browse with
  // a meaningful category, canonical points at the category-level page.
  canonicalPath: string;
  robots?: string;
  // og:type — defaults to "website" for sections, "product" for
  // /listing/:id (each listing is a discrete purchasable property).
  ogType?: "website" | "product";
  // og:image:alt — short alt text for the share-card image. Optional;
  // when absent, applyMeta removes any stale alt tag from the static
  // shell so previewers don't show the cold-load alt on a different image.
  imageAlt?: string;
};

// Squeeze a free-text listing description into a meta-tag-friendly form.
// SERPs render newlines + control chars literally; LLM-generated copy
// occasionally embeds `&amp;` / `&quot;` / `&#39;`. Single-line, decoded,
// capped at 200 chars with an ellipsis is the conservative shape.
function cleanDescription(raw: string): string {
  if (!raw) return "";
  let s = raw
    // Decode the handful of HTML entities our enrichment pipeline emits.
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&nbsp;/g, " ")
    // Strip control chars (including newlines, tabs) — collapse to one
    // space so word boundaries survive.
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    // Collapse runs of whitespace.
    .replace(/\s+/g, " ")
    .trim();
  if (s.length > 200) s = s.slice(0, 197) + "…";
  return s;
}

// Per-category title + description copy for /browse?cat={key}. Every key
// from CATEGORY_KEYS in lib/categories.ts MUST appear here — the
// use-document-meta tests assert full coverage so a new category can't
// land without SEO copy. The titles target long-tail SERP queries like
// "ocean view land for sale in El Salvador" — country name is
// interpolated from ACTIVE_COUNTRY so the table works for any future
// country deployment.
//
// Why every key has unique copy: the soft-404 / duplicate-content
// penalty kicks in if Google sees /browse?cat=ocean_view and
// /browse?cat=mountain_view sharing the same <title>+<description>.
// Each pair of strings has to read as a meaningfully different page.
const BROWSE_CATEGORY_COPY: Record<CategoryKey, { titleEn: string; titleEs: string; descEn: string; descEs: string }> = {
  new_this_week: {
    titleEn: `New listings this week in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Anuncios nuevos esta semana en ${COUNTRY_ES} — Pulpo`,
    descEn: `Beach and lake homes that hit the ${COUNTRY_ADJECTIVE_EN} market this week, ranked by value. Pulpo updates the list every night.`,
    descEs: `Casas de playa y lago publicadas esta semana en ${COUNTRY_ES}, ordenadas por valor. Pulpo actualiza la lista cada noche.`,
  },
  price_drops: {
    titleEn: `Recent price drops in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Bajadas de precio recientes en ${COUNTRY_ES} — Pulpo`,
    descEn: `Beach and lake listings whose asking price dropped in the last 30 days. Curated by Pulpo.`,
    descEs: `Anuncios de playa y lago con bajada de precio en los últimos 30 días. Curado por Pulpo.`,
  },
  off_market: {
    titleEn: `Off-market deals in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Ofertas off-market en ${COUNTRY_ES} — Pulpo`,
    descEn: `Access off-market deals not listed publicly elsewhere. Pulpo Pro.`,
    descEs: `Acceso a tratos off-market que no aparecen en otros portales. Pulpo Pro.`,
  },
  best_documented: {
    titleEn: `Best-documented listings in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Anuncios mejor documentados en ${COUNTRY_ES} — Pulpo`,
    descEn: `Listings with title verified, photos checked, and seller reputation scored. Curated by Pulpo.`,
    descEs: `Anuncios con título verificado, fotos revisadas y reputación del vendedor puntuada. Curado por Pulpo.`,
  },
  beachfront: {
    titleEn: `Beachfront land for sale in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Terrenos frente al mar en ${COUNTRY_ES} — Pulpo`,
    descEn: `Browse ${COUNTRY_ADJECTIVE_EN} beachfront land — titled and off-market — in one place.`,
    descEs: `Explora terrenos frente al mar en ${COUNTRY_ES}, titulados y off-market, en un solo lugar.`,
  },
  ocean_view: {
    titleEn: `Ocean-view land and homes in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Terrenos y casas con vista al mar en ${COUNTRY_ES} — Pulpo`,
    descEn: `Beach and hillside listings with an ocean view across ${COUNTRY_EN}, ranked by value. Curated by Pulpo.`,
    descEs: `Terrenos y casas con vista al mar en ${COUNTRY_ES}, ordenados por valor. Curado por Pulpo.`,
  },
  mountain_view: {
    titleEn: `Mountain-view homes in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Casas con vista a la montaña en ${COUNTRY_ES} — Pulpo`,
    descEn: `Hillside and lakeside homes with a mountain view in ${COUNTRY_EN}. Curated by Pulpo.`,
    descEs: `Casas en ladera y junto al lago con vista a la montaña en ${COUNTRY_ES}. Curado por Pulpo.`,
  },
  water_features: {
    titleEn: `Lakefront and water-feature properties in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Propiedades junto al agua y con lago en ${COUNTRY_ES} — Pulpo`,
    descEn: `Listings on or near a lake, river, or natural pool. Curated by Pulpo.`,
    descEs: `Anuncios junto a un lago, río o piscina natural. Curado por Pulpo.`,
  },
  flat_buildable: {
    titleEn: `Flat, buildable land in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Terrenos planos para construir en ${COUNTRY_ES} — Pulpo`,
    descEn: `Level parcels suited for direct construction. Curated by Pulpo.`,
    descEs: `Parcelas planas, aptas para construcción directa. Curado por Pulpo.`,
  },
  build_ready: {
    titleEn: `Build-ready land for sale in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Terrenos listos para construir en ${COUNTRY_ES} — Pulpo`,
    descEn: `Plots with utilities and road access — build-ready. Curated by Pulpo.`,
    descEs: `Terrenos con servicios y acceso vial, listos para construir. Curado por Pulpo.`,
  },
  commercial: {
    titleEn: `Commercial property for sale in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Propiedades comerciales en ${COUNTRY_ES} — Pulpo`,
    descEn: `Hotels, restaurants, retail, and mixed-use commercial listings across ${COUNTRY_EN}. Curated by Pulpo.`,
    descEs: `Hoteles, restaurantes, retail y propiedades comerciales mixtas en ${COUNTRY_ES}. Curado por Pulpo.`,
  },
  under_50k: {
    titleEn: `Land and homes under $50,000 in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Terrenos y casas por menos de $50,000 en ${COUNTRY_ES} — Pulpo`,
    descEn: `Affordable beach and lake listings under $50k, ranked by value. Curated by Pulpo.`,
    descEs: `Anuncios económicos de playa y lago por menos de $50,000, ordenados por valor. Curado por Pulpo.`,
  },
  under_100k: {
    titleEn: `Land and homes under $100,000 in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Terrenos y casas por menos de $100,000 en ${COUNTRY_ES} — Pulpo`,
    descEn: `Beach and lake listings under $100k, ranked by value. Curated by Pulpo.`,
    descEs: `Anuncios de playa y lago por menos de $100,000, ordenados por valor. Curado por Pulpo.`,
  },
  motivated_sellers: {
    titleEn: `Motivated-seller deals in ${COUNTRY_EN} — Pulpo`,
    titleEs: `Vendedores motivados en ${COUNTRY_ES} — Pulpo`,
    descEn: `Listings flagged as motivated sellers — likely to negotiate. Curated by Pulpo.`,
    descEs: `Anuncios marcados como vendedores motivados — abiertos a negociar. Curado por Pulpo.`,
  },
};

function metaForSection(route: Route, locale: "en" | "es", search: string): Meta {
  const isEs = locale === "es";

  if (route === "browse") {
    // Read just the category from the search string — other Browse params
    // shouldn't fragment the canonical (filter combinations are noindex).
    const params = new URLSearchParams(search);
    const cat = params.get("cat");
    if (cat && (CATEGORY_KEYS as readonly string[]).includes(cat)) {
      const copy = BROWSE_CATEGORY_COPY[cat as CategoryKey];
      return {
        title: isEs ? copy.titleEs : copy.titleEn,
        description: isEs ? copy.descEs : copy.descEn,
        image: BRAND_OG_IMAGE,
        canonicalPath: `/browse?cat=${cat}`,
      };
    }
    // Unknown / absent category → generic Browse meta. Canonical drops
    // the cat param so a stray `?cat=foo` doesn't get indexed as its
    // own URL.
    return {
      title: isEs
        ? `Explorar terrenos de playa, listos para construir y off-market en ${COUNTRY_ES} — Pulpo`
        : `Browse ${COUNTRY_ADJECTIVE_EN} beachfront, build-ready & off-market land — Pulpo`,
      description: isEs ? SITE_DESCRIPTION_ES : SITE_DESCRIPTION_EN,
      image: BRAND_OG_IMAGE,
      canonicalPath: "/browse",
    };
  }

  if (route === "saved") {
    return {
      title: isEs ? "Tus terrenos guardados — Pulpo" : "Your saved listings — Pulpo",
      description: isEs ? SITE_DESCRIPTION_ES : SITE_DESCRIPTION_EN,
      image: BRAND_OG_IMAGE,
      canonicalPath: "/saved",
      robots: "noindex,follow",
    };
  }

  if (route === "plans") {
    return {
      title: isEs ? "Planes y precios — Pulpo" : "Plans & pricing — Pulpo",
      description: isEs
        ? "Pulpo es gratis para explorar. Contrata Pro para detalles ilimitados, acceso off-market y alertas semanales."
        : "Pulpo is free to browse. Upgrade for unlimited details, off-market access, and weekly alerts.",
      image: BRAND_OG_IMAGE,
      canonicalPath: "/plans",
    };
  }

  if (route === "account") {
    return {
      title: isEs ? "Tu cuenta — Pulpo" : "Your account — Pulpo",
      description: isEs ? SITE_DESCRIPTION_ES : SITE_DESCRIPTION_EN,
      image: BRAND_OG_IMAGE,
      canonicalPath: "/account",
      robots: "noindex,follow",
    };
  }

  if (
    route === "terms" ||
    route === "privacy" ||
    route === "cookies" ||
    route === "subscription" ||
    route === "imprint"
  ) {
    const doc = findDocument(route);
    return {
      title: doc?.title[locale] ?? (isEs ? "Pulpo — Aviso legal" : "Pulpo — Legal"),
      description: doc?.description[locale] ?? (isEs ? SITE_DESCRIPTION_ES : SITE_DESCRIPTION_EN),
      image: BRAND_OG_IMAGE,
      canonicalPath: `/${route}`,
    };
  }

  if (route === "contact") {
    return {
      title: isEs ? "Contacto — Pulpo" : "Contact Pulpo — support, privacy & billing",
      description: isEs
        ? "Contacta con Pulpo para consultas generales, facturación, privacidad o solicitudes legales."
        : "Get in touch with Pulpo for general enquiries, billing, privacy requests, and legal notices.",
      image: BRAND_OG_IMAGE,
      canonicalPath: "/contact",
    };
  }

  if (route === "admin") {
    return {
      title: "Pulpo admin",
      description: "Internal Pulpo admin tools.",
      image: BRAND_OG_IMAGE,
      canonicalPath: "/admin",
      robots: "noindex,nofollow",
    };
  }

  // home
  return {
    title: isEs
      ? `Pulpo — Casas y terrenos de playa y lago en ${COUNTRY_ES}, ordenados por valor`
      : `Pulpo — Beach and lake homes in ${COUNTRY_EN}, ranked by value`,
    description: isEs ? SITE_DESCRIPTION_ES : SITE_DESCRIPTION_EN,
    image: BRAND_OG_IMAGE,
    canonicalPath: "/",
  };
}

function metaForListing(listing: Listing, locale: "en" | "es"): Meta {
  const isEs = locale === "es";
  const titleField = cleanDescription(listing.title?.[locale] ?? listing.title?.en ?? "");
  const descField = cleanDescription(listing.description?.[locale] ?? listing.description?.en ?? "");
  const zone = listing.zone_name || (listing.region ?? "");

  const countryName = isEs ? COUNTRY_ES : COUNTRY_EN;
  const title = titleField
    ? `${titleField} — ${zone ? zone + ", " : ""}${countryName} — Pulpo`
    : isEs
      ? `Anuncio en ${zone || COUNTRY_ES} — Pulpo`
      : `Listing in ${zone || COUNTRY_EN} — Pulpo`;

  const description = descField || (isEs ? SITE_DESCRIPTION_ES : SITE_DESCRIPTION_EN);

  // First photo if available. Photos are absolute URLs already
  // (e.g. /photos/idealista/12345/0.jpg) so no rewriting needed.
  const image = listing.photos?.[0] ?? BRAND_OG_IMAGE;

  return {
    title,
    description,
    image,
    canonicalPath: `/listing/${encodeURIComponent(listing.id)}`,
    // Real-estate listings render as "Product" in OG-aware scrapers
    // (LinkedIn, Pinterest) — matches the RealEstateListing JSON-LD
    // we already emit in pages.jsx.
    ogType: "product",
    imageAlt: titleField || (isEs ? `Anuncio en ${COUNTRY_ES}` : `Listing in ${COUNTRY_EN}`),
  };
}

// Set or update a <meta> tag identified by attribute key + value.
// Returns the element so the caller can keep adjusting attributes.
function setMeta(attr: "name" | "property", key: string, content: string) {
  if (typeof document === "undefined") return;
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

// Remove a <meta> tag if present. Used to strip dimension/alt tags that
// would lie about the current image (the static shell sets them for the
// brand OG photo; when the route swaps in a listing photo of unknown
// size, the stale tags must go rather than mislead the share-card
// previewer).
function removeMeta(attr: "name" | "property", key: string) {
  if (typeof document === "undefined") return;
  const el = document.head.querySelector(`meta[${attr}="${key}"]`);
  if (el) el.remove();
}

function setLink(rel: string, href: string, hreflang?: string) {
  if (typeof document === "undefined") return;
  // Need to handle multiple rel="alternate" entries (one per hreflang),
  // so key on rel + hreflang.
  const selector = hreflang
    ? `link[rel="${rel}"][hreflang="${hreflang}"]`
    : `link[rel="${rel}"]:not([hreflang])`;
  let el = document.head.querySelector<HTMLLinkElement>(selector);
  if (!el) {
    el = document.createElement("link");
    el.setAttribute("rel", rel);
    if (hreflang) el.setAttribute("hreflang", hreflang);
    document.head.appendChild(el);
  }
  el.setAttribute("href", href);
}

// Apply a Meta record to the live document. Idempotent — same input
// produces the same DOM, no churn.
function applyMeta(meta: Meta, locale: "en" | "es") {
  if (typeof document === "undefined") return;

  document.title = meta.title;

  setMeta("name", "description", meta.description);

  setMeta("property", "og:title", meta.title);
  setMeta("property", "og:description", meta.description);
  const resolvedImage = new URL(meta.image, ORIGIN).toString();
  const isBrandImage = meta.image === BRAND_OG_IMAGE;
  setMeta("property", "og:image", resolvedImage);
  setMeta("property", "og:type", meta.ogType ?? "website");
  setMeta("property", "og:site_name", SITE_NAME);
  setMeta("property", "og:url", new URL(meta.canonicalPath, ORIGIN).toString());
  setMeta("property", "og:locale", locale === "es" ? OG_LOCALE_ES : OG_LOCALE_EN);
  setMeta("property", "og:locale:alternate", locale === "es" ? OG_LOCALE_EN : OG_LOCALE_ES);

  // Image dimensions + alt — only meaningful for the brand fallback we
  // control. For per-listing photos we don't know dimensions upfront,
  // so strip the static-shell tags rather than ship lies to crawlers.
  if (isBrandImage) {
    setMeta("property", "og:image:type", "image/jpeg");
    setMeta("property", "og:image:width", "1200");
    setMeta("property", "og:image:height", "630");
  } else {
    removeMeta("property", "og:image:type");
    removeMeta("property", "og:image:width");
    removeMeta("property", "og:image:height");
  }
  if (meta.imageAlt) {
    setMeta("property", "og:image:alt", meta.imageAlt);
    setMeta("name", "twitter:image:alt", meta.imageAlt);
  } else if (!isBrandImage) {
    removeMeta("property", "og:image:alt");
    removeMeta("name", "twitter:image:alt");
  }

  setMeta("name", "twitter:card", "summary_large_image");
  setMeta("name", "twitter:title", meta.title);
  setMeta("name", "twitter:description", meta.description);
  setMeta("name", "twitter:image", resolvedImage);
  setMeta("name", "robots", meta.robots ?? "index,follow");

  // Canonical: never carry `?lang=` (locale variants get hreflang
  // alternates instead) or `?sort=` / weight params.
  const canonicalUrl = new URL(meta.canonicalPath, ORIGIN).toString();
  setLink("canonical", canonicalUrl);

  // Hreflang alternates — point each language's variant at the same
  // canonical path with the appropriate `?lang=` (or no param for
  // English, the default).
  const enHref = new URL(meta.canonicalPath, ORIGIN).toString();
  const esUrl = new URL(meta.canonicalPath, ORIGIN);
  esUrl.searchParams.set("lang", "es");
  setLink("alternate", enHref, "en");
  setLink("alternate", esUrl.toString(), "es");
  setLink("alternate", enHref, "x-default");
}

export function useDocumentMeta(args: {
  route: Route;
  locale: "en" | "es";
  listing?: Listing | null;
  search?: string;
}) {
  const { route, locale, listing, search = "" } = args;

  // Reactivity key: route + locale + listing.id + search-without-noise.
  // We strip transient params (sort, weights, slider drags) so the meta
  // doesn't churn on every chip toggle. Filter chips that change the
  // canonical (cat) DO trigger an update — that's what we want.
  // useLayoutEffect (synchronous, runs before paint AND before any
  // useEffect) so the title and head tags are route-correct on first
  // paint.
  useLayoutEffect(() => {
    const meta = listing
      ? metaForListing(listing, locale)
      : metaForSection(route, locale, search);
    applyMeta(meta, locale);
  }, [route, locale, listing?.id, listing?.photos?.[0], search]);
}

// Exposed for tests + the SEO follow-up that prerenders static stubs.
export const __test__ = { metaForSection, metaForListing, applyMeta };
