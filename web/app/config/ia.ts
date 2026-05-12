// Pulpo Information Architecture — TypeScript mirror of pulpo/ia_config.py.
//
// Both files MUST stay in lockstep: tile copy, discovery pill labels,
// star bins, thresholds, master-category labels. The Python side is
// the runtime source of truth for the backend pipeline; this TS file
// is the runtime source for the React components. Changes flow:
//
//   1. Edit pulpo/ia_config.py
//   2. Mirror the change here in the matching constant
//   3. Both Python + TS tests assert their own constants — drift fails CI
//
// When the surface grows beyond ~3 constants, consider auto-generating
// this file from the Python source at build time. For v1 the manual-sync
// cost is < a code review.
//
// Bilingual copy (Q1 of the rewrite plan): every user-facing string is
// {en, es} at write-time. The React components read via i18n.jsx's
// tr() helper, identical to every other localized string in the app.

import type { DiscoveryTag, MasterCategory, Subcategory } from "../data/types";

// ── Enums (re-exported from types.ts; here as runtime tuples for iteration)

export const MASTER_CATEGORIES = ["beach", "lake"] as const satisfies readonly MasterCategory[];
export const SUBCATEGORIES     = ["homes", "condos", "land"] as const satisfies readonly Subcategory[];
export const DISCOVERY_TAGS    = [
  "top_rated", "under_250k", "gated", "waterfront",
] as const satisfies readonly DiscoveryTag[];

// ── Thresholds (mirrored from pulpo/ia_config.py)

export const TOP_RATED_MIN_RANK_SCORE = 70.0;
export const UNDER_250K_USD = 250_000;
export const BEACH_PROXIMITY_KM = 5.0;

// ── Star rating bins (mirror of STAR_BINS in pulpo/ia_config.py)
// Descending lookup: first threshold met wins.

export const STAR_BINS: readonly (readonly [number, number])[] = [
  [85, 5.0],
  [78, 4.5],
  [70, 4.0],
  [60, 3.5],
  [50, 3.0],
  [38, 2.5],
  [25, 2.0],
  [13, 1.5],
  [1,  1.0],
] as const;

// ── Bilingual tile copy (homepage category grid).
// Key shape: `${MasterCategory}.${Subcategory}` — keeps the lookup type-safe
// without needing tuple-key Map gymnastics on the FE.

type TileKey = `${MasterCategory}.${Subcategory}`;
type LocalizedString = { en: string; es: string };

export const TILE_COPY: Record<TileKey, LocalizedString> = {
  "beach.homes": {
    en: "Move-in-ready houses on the Pacific coast.",
    es: "Casas listas para habitar en la costa del Pacífico.",
  },
  "beach.condos": {
    en: "Apartments within walking distance of surf.",
    es: "Apartamentos a pasos del surf.",
  },
  "beach.land": {
    en: "Buildable plots near the ocean.",
    es: "Terrenos para construir cerca del mar.",
  },
  "lake.homes": {
    en: "Houses on Coatepeque, Ilopango, Suchitlán.",
    es: "Casas en Coatepeque, Ilopango, Suchitlán.",
  },
  "lake.condos": {
    en: "Waterfront apartments and shared developments.",
    es: "Apartamentos junto al lago y desarrollos compartidos.",
  },
  "lake.land": {
    en: "Plots with direct access or lake views.",
    es: "Terrenos con acceso directo o vista al lago.",
  },
};

export const DISCOVERY_PILL_LABELS: Record<DiscoveryTag, LocalizedString> = {
  top_rated:  { en: "Top rated",   es: "Mejor valorados" },
  under_250k: { en: "Under $250K", es: "Menos de $250K" },
  gated:      { en: "Gated",       es: "Privado / cerrado" },
  waterfront: { en: "Waterfront",  es: "Frente al agua" },
};

export const MASTER_CATEGORY_LABELS: Record<MasterCategory, LocalizedString> = {
  beach: { en: "Beach properties", es: "Propiedades de playa" },
  lake:  { en: "Lake properties",  es: "Propiedades de lago" },
};

export const SUBCATEGORY_LABELS: Record<Subcategory, LocalizedString> = {
  homes:  { en: "Homes",  es: "Casas" },
  condos: { en: "Condos", es: "Condominios" },
  land:   { en: "Land",   es: "Terrenos" },
};

// Helper: typed lookup for the category grid component.
export function tileCopy(master: MasterCategory, sub: Subcategory): LocalizedString {
  return TILE_COPY[`${master}.${sub}`];
}
