# Browse Categories — Reference Spec

> **Status:** Reference, not contract.
> Pulpo's browse categories are **saved searches**, not a fixed taxonomy.
> The platform may have additional filters not listed here, and some filters
> below may be hard or impossible to populate from current data sources —
> ship what's reliable, defer the rest. The point of this doc is to align on
> *intent* and *expected UX*, then let the implementation be pragmatic.

---

## 1. Mental model

A **category** = a saved search.
Clicking a category pill (or "See all" on a homepage shelf) navigates the user to the Browse page with one or more underlying filters pre-applied and a default sort. The user can then refine further via the filter sidebar.

Categories are *additive sugar* on top of the filter system — every category should be expressible as a combination of filters that the user could have applied manually. If a category can't be reduced to filters, it doesn't belong as a category.

---

## 2. Expected UX (acceptance criteria)

When a user clicks a category pill or shelf "See all":

1. **Navigate** to `/sv/{locale}/browse?cat={key}` (URL is shareable + back-button safe).
2. **Pre-apply** the relevant filters in the sidebar — checkboxes/sliders reflect the active state, so the user understands *why* they're seeing this subset.
3. **Confirm context** in the results header:
   > **{Category Name}**
   > {N} listings in El Salvador · ✕
   The ✕ clears the category and returns to the unfiltered Browse page.
4. **Active state** — the pill in the rail stays highlighted; the sidebar chips are checked.
5. **Default sort** — each category has a sensible default sort (see table below). User can override.
6. **Refresh / share** — refreshing the URL reproduces the same view.
7. **Back button** — returns to the previous category or page, doesn't blow away state.
8. **Empty state** — if 0 listings match, show a cross-suggest:
   > "No beachfront listings in El Salvador right now. Try **Ocean View** instead?"
   …with a button. Don't show a generic "No results" empty state.

---

## 3. Category → filter mapping (reference)

This is **the source of truth for category intent**, not for implementation. If a flag below is hard to extract reliably, replace it with the closest reliable proxy or drop the category until the data is there.

| Category key | Underlying filter (intent) | Default sort |
|---|---|---|
| `new_this_week`   | `first_seen_date` ≤ 7 days ago | `first_seen_date desc` |
| `price_drops`     | `is_repriced = true`           | `price_drop_pct desc` |
| `beachfront`      | `beachfront_tier ≠ null` (e.g. `on_beach`, `walk_to_beach`) | `recency` |
| `ocean_view`      | `has_ocean_view = true` AND NOT `beachfront_tier` (avoid double-listing) | `recency` |
| `mountain_view`   | `has_mountain_view = true` | `recency` |
| `water_features`  | `has_water_body = true` (river / pond / spring on parcel) | `recency` |
| `flat_buildable`  | `is_flat = true` (slope ≤ ~10%) | `recency` |
| `build_ready`     | `readiness_score ≥ 3` (composite — see below) | `recency` |
| `off_market`      | `source_type = "off_market"` | `recency` |
| `under_50k`       | `price ≤ 50_000` | `price asc` |
| `under_100k`      | `price` between `50_001` and `100_000` (avoid overlap with under_50k) | `price asc` |
| `agricultural`    | `land_type = "agricultural"` | `recency` |
| `commercial`      | `land_type = "commercial"` | `recency` |
| `motivated_sellers` | `days_listed ≥ 90` AND (`is_repriced = true` OR seller flagged) | `days_listed desc` |

**Notes**
- `readiness_score` is a 0–4 composite — recommended definition: `+1 has_road_access + 1 has_power + 1 has_water + 1 has_title_clean`. Threshold `≥ 3` for "build-ready".
- `under_100k` deliberately excludes the under-$50K band so the two pills don't show identical results.

---

## 4. Extracting flags from listing text and photos

Most flags will not arrive pre-tagged from a scraper or off-market source — they need to be derived from free-text descriptions and/or photos. Here are extraction strategies per flag, ordered roughly from cheap-and-reliable to expensive.

### Text-based extraction

For each flag, prefer **keyword + regex** first, then **LLM classification with strict JSON output** for ambiguous cases. Always store `confidence` alongside the flag so the UI can hide low-confidence flags.

| Flag | Text signals (EN / ES) | Strategy |
|---|---|---|
| `beachfront_tier` | "beachfront", "on the beach", "frente al mar", "en la playa", "primera línea", "playa privada" | Regex pass for distance hints ("50m to beach", "5 min walk to beach") → bucket into `on_beach` / `walk_to_beach` / `near_beach`. LLM fallback for ambiguous descriptions. |
| `has_ocean_view` | "ocean view", "sea view", "vista al mar", "vista oceánica", "panoramic view of the Pacific" | Keyword + LLM to filter false positives ("ocean view from the rooftop *of a future build*" ≠ already has view). |
| `has_mountain_view` | "mountain view", "vista a la montaña", "vista a los volcanes", "Cerro Verde view" | Keyword. Country-specific cues — in El Salvador, references to volcanoes (Conchagua, Santa Ana, San Vicente) are strong signals. |
| `has_water_body` | "river", "creek", "spring", "pond", "lake frontage", "río", "quebrada", "manantial", "ojo de agua" | Keyword. Watch for negation: "near the river" ≠ "river on parcel". LLM disambiguates. |
| `is_flat` | "flat", "level", "plano", "plana", "topografía plana", "0–5% slope", "buildable" | Keyword. Numeric slope cues ("10% slope") → parse and bucket. Default to false if absent (flat is a noteworthy feature; sellers would mention it). |
| `has_road_access` | "paved road", "calle pavimentada", "vehicle access", "acceso vehicular", "off the highway", "from CA-2" | Keyword. Distinguish `paved` / `dirt` / `none` — affects `road_access_type`. |
| `has_power` | "power on site", "luz", "electricidad", "transformer at boundary", "poste a 50m" | Keyword. "At boundary" vs "on site" matters → bucket. |
| `has_water` | "water on site", "agua potable", "well", "pozo", "ANDA", "municipal water" | Keyword. In El Salvador, "ANDA" (national water utility) is a strong positive signal. |
| `has_title_clean` | "titled", "escriturado", "título de propiedad", "Registro Inmobiliario", "free of liens", "libre de gravamen" | Keyword. Inverse signals: "in process", "en trámite", "remedición pendiente" → flag as `title_pending`. |
| `land_type` | "agricultural", "agrícola", "finca", "cafetal", "commercial", "comercial", "residential", "tourism zone", "zona turística" | Keyword. Default to `residential` if ambiguous. Cross-check with zoning municipal data when available. |
| `is_repriced` | Compare current price vs scrape history. If no history, look for "reduced", "rebajado", "price reduced from $X to $Y", "negociable" | Diff-based. Keyword as fallback for first-scrape signals. |
| `motivated` | "must sell", "urgent", "se vende urgente", "remate", "bajada de precio", "owner relocating", "estate sale" | Keyword. Combined with `days_listed ≥ 90` for higher precision. |
| `usps[]` | The 2–3 most distinctive features per listing | LLM summarizer with prompt: *"Given this listing description, return up to 3 short bullets that would make this parcel stand out. Output JSON: `{ usps: [{ en, es }] }`."* |

### Photo-based extraction

When text is sparse or low-confidence, photos can fill gaps. Use a vision model (or specialized classifiers) to extract:

| Flag | Photo signals | Strategy |
|---|---|---|
| `beachfront_tier` | Visible sand, surf, water on the parcel | Vision model classifier: `[on_beach / near_beach / no_beach]`. Combine with text hints. |
| `has_ocean_view` | Horizon line + ocean visible from parcel POV | Vision model. Look at *foreground vs background* — drone shots overstate views. |
| `has_mountain_view` | Volcano / mountain silhouette in distance | Vision + EXIF GPS → cross-check known viewpoints. |
| `is_flat` | Land surface gradient | Vision model regressor. Drone overhead shots most reliable. |
| `has_road_access` | Visible road touching or adjacent to parcel | Vision: detect road, classify surface (`paved` / `dirt` / `path`). Combine with satellite imagery. |
| `has_power` | Power poles / lines visible at boundary | Vision: object detection for utility poles. Counts as `at_boundary`, not `on_site`. |
| `has_water_body` | River / pond / lake visible on parcel | Vision: water-body segmentation. Cross-check with topographic data. |
| `photo_quality_score` | Sharpness, resolution, lighting, composition | Off-the-shelf aesthetic scorer. Drives the `best_documented` shelf. |
| `is_drone_shot` | Bird's-eye perspective | Useful metadata: drone shots are higher-trust for parcel boundaries and topography. |

### Geographic / external sources

Some flags are cheaper to derive from external data than from listing content:

| Flag | Source |
|---|---|
| `dist_beach_km` | Lat/lon → coastline polygon (OSM `natural=coastline`). |
| `dist_airport_km` | Lat/lon → SAL (San Salvador Intl) and other registered airports. |
| `dist_nearest_town_km` | Lat/lon → OSM `place=town/city`. |
| `is_flat` | DEM (digital elevation model — SRTM or local lidar) → slope at parcel centroid. **More reliable than text or photos.** |
| `zoning_use` | Municipal zoning maps (where digitized). El Salvador's MARN and OPAMSS have partial coverage. |
| `road_access_type` | OSM road network → nearest road class. |

### Confidence & display rules

- Every extracted flag should have `confidence ∈ [0, 1]` stored alongside it.
- UI rule of thumb: **show the flag** if confidence ≥ 0.7, **hide it** below that.
- For category eligibility (whether a listing appears in a saved-search shelf), use a higher bar: ≥ 0.85. False positives in shelves erode trust faster than false negatives.
- Always store `extraction_source` (`text` / `photo` / `geodata` / `seller_provided`) so debugging is possible.

---

## 5. What's *not* in scope of this doc

- The full filter sidebar taxonomy (price slider, size slider, zone multi-select, etc.) — that lives in the filter spec.
- Search-bar free-text matching.
- Map-view filtering.
- Personalization / recommendations.

---

## 6. Open questions for product

- Do we want `under_25k` as a separate band, or is `under_50k` the floor? (Sub-$25K parcels in El Salvador exist and skew toward unverifiable titles — may not be worth surfacing.)
- Should `new_this_week` reset every Monday (calendar week) or be a rolling 7-day window? Calendar week is more "magazine-like" and pairs with the weekly digest; rolling is more "live."
- Is there a `verified` category (titled + photographed + walked by us)? If so, that becomes the highest-trust shelf and probably the most-clicked.
- Should `motivated_sellers` be public, or gated behind a paid plan? It has a "deal-finder" connotation that may belong in Pro.
