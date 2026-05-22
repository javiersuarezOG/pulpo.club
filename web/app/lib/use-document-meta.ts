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

const SITE_NAME = "Pulpo";
// Rewrite Phase 8 — homepage description now aligns with the new hero
// copy ("Every beach and lake home in El Salvador, ranked by value")
// while remaining accurate for the legacy homepage during the rollout
// window. Both versions surface beach + lake properties + a value
// ranking; the copy works regardless of which UI a SERP click lands on.
const SITE_DESCRIPTION_EN = "Every beach and lake home in El Salvador, ranked by value. Browse hundreds of vetted beach and lake properties — and get the 10 best delivered to your inbox every week.";
const SITE_DESCRIPTION_ES = "Cada casa de playa y lago en El Salvador, ordenada por valor. Explora cientos de propiedades verificadas de playa y lago — y recibe las 10 mejores en tu correo cada semana.";

// One brand image for sections; listing detail uses the listing's first
// photo. The brand image lives next to the legacy assets and is also
// referenced from index.html's static OG tag for the cold-load path.
const BRAND_OG_IMAGE = "/assets/og-default.jpg";

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
};

function metaForSection(route: Route, locale: "en" | "es", search: string): Meta {
  const isEs = locale === "es";

  if (route === "browse") {
    // Read just the category from the search string — other Browse params
    // shouldn't fragment the canonical (filter combinations are noindex).
    const params = new URLSearchParams(search);
    const cat = params.get("cat");
    if (cat === "beachfront") {
      return {
        title: isEs
          ? "Terrenos frente al mar en El Salvador — Pulpo"
          : "Beachfront land for sale in El Salvador — Pulpo",
        description: isEs
          ? "Explora terrenos frente al mar en El Salvador, titulados y off-market, en un solo lugar."
          : "Browse Salvadoran beachfront land — titled and off-market — in one place.",
        image: BRAND_OG_IMAGE,
        canonicalPath: "/browse?cat=beachfront",
      };
    }
    if (cat === "build_ready") {
      return {
        title: isEs
          ? "Terrenos listos para construir en El Salvador — Pulpo"
          : "Build-ready land for sale in El Salvador — Pulpo",
        description: isEs
          ? "Terrenos con servicios y acceso vial, listos para construir. Curado por Pulpo."
          : "Plots with utilities and road access — build-ready. Curated by Pulpo.",
        image: BRAND_OG_IMAGE,
        canonicalPath: "/browse?cat=build_ready",
      };
    }
    if (cat === "off_market") {
      return {
        title: isEs
          ? "Ofertas off-market en El Salvador — Pulpo"
          : "Off-market deals in El Salvador — Pulpo",
        description: isEs
          ? "Acceso a tratos off-market que no aparecen en otros portales. Pulpo Pro."
          : "Access off-market deals not listed publicly elsewhere. Pulpo Pro.",
        image: BRAND_OG_IMAGE,
        canonicalPath: "/browse?cat=off_market",
      };
    }
    return {
      title: isEs
        ? "Explorar terrenos frente al mar y off-market — Pulpo"
        : "Browse Salvadoran beachfront, build-ready & off-market land — Pulpo",
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
    };
  }

  // home
  return {
    title: isEs
      ? "Pulpo — Casas y terrenos de playa y lago en El Salvador, ordenados por valor"
      : "Pulpo — Beach and lake homes in El Salvador, ranked by value",
    description: isEs ? SITE_DESCRIPTION_ES : SITE_DESCRIPTION_EN,
    image: BRAND_OG_IMAGE,
    canonicalPath: "/",
  };
}

function metaForListing(listing: Listing, locale: "en" | "es"): Meta {
  const isEs = locale === "es";
  const titleField = listing.title?.[locale] ?? listing.title?.en ?? "";
  const descField = listing.description?.[locale] ?? listing.description?.en ?? "";
  const zone = listing.zone_name || (listing.region ?? "");

  const title = titleField
    ? `${titleField} — ${zone ? zone + ", " : ""}El Salvador — Pulpo`
    : isEs
      ? `Anuncio en ${zone || "El Salvador"} — Pulpo`
      : `Listing in ${zone || "El Salvador"} — Pulpo`;

  const description = descField
    ? descField.length > 200 ? descField.slice(0, 197) + "…" : descField
    : isEs ? SITE_DESCRIPTION_ES : SITE_DESCRIPTION_EN;

  // First photo if available. Photos are absolute URLs already
  // (e.g. /photos/idealista/12345/0.jpg) so no rewriting needed.
  const image = listing.photos?.[0] ?? BRAND_OG_IMAGE;

  return {
    title,
    description,
    image,
    canonicalPath: `/listing/${encodeURIComponent(listing.id)}`,
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
  setMeta("property", "og:image", new URL(meta.image, ORIGIN).toString());
  setMeta("property", "og:type", "website");
  setMeta("property", "og:site_name", SITE_NAME);
  setMeta("property", "og:locale", locale === "es" ? "es_SV" : "en_US");

  setMeta("name", "twitter:card", "summary_large_image");
  setMeta("name", "twitter:title", meta.title);
  setMeta("name", "twitter:description", meta.description);
  setMeta("name", "twitter:image", new URL(meta.image, ORIGIN).toString());

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
  // useEffect) so the title is up-to-date by the time the marquee
  // effect snapshots it. Without this, the marquee captures the
  // static index.html title and animates the wrong text on home.
  useLayoutEffect(() => {
    const meta = listing
      ? metaForListing(listing, locale)
      : metaForSection(route, locale, search);
    applyMeta(meta, locale);
  }, [route, locale, listing?.id, listing?.photos?.[0], search]);
}

// Exposed for tests + the SEO follow-up that prerenders static stubs.
export const __test__ = { metaForSection, metaForListing, applyMeta };
