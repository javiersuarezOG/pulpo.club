# Pulpo — Navigation Spec

This is the navigation contract for the Pulpo prototype. The implementation is
in `app.jsx` (route state + `go` / `goBrowse`) and `pages.jsx` (TopNav,
BottomNav, PillRail, page components). When migrating to a real router, this
doc is the source of truth for URL shapes and the mental model for each route.

---

## 1. Top-level routes

| Route key | URL (proposed) | Mental model | Page component |
|---|---|---|---|
| `home` | `/` | **Discover** — editorial, "what's new and noteworthy" | `HomePage` |
| `browse` | `/browse` | **Browse** — search/filter, "find listings matching X" | `BrowsePage` |
| `saved` | `/saved` | **Saved** — personal collection | `SavedPage` |
| `plans` | `/plans` | Pricing | `PlansPage` |

Listing detail is **not** a top-level route in the prototype — it opens as an
overlay panel on top of whichever route the user is on (`openListingId` in
`app.jsx`). For production, give it its own URL: `/listings/:id`.

---

## 2. Two distinct browsing modes

This is the most important decision in the IA, and the one most prone to drift:

### Discover (`/`) — editorial, **not** filterable

- Hero featured listing
- Curated horizontal shelves (Beachfront, Build-Ready, Off-Market, etc.)
- **No pill rail, no filter sidebar.** Discover is a magazine, not a search UI.
- Entry points to Browse: the Hero CTA "Browse listings", and each shelf's
  "See all →" link (which opens Browse pre-filtered to that shelf's category).

### Browse (`/browse`) — search-driven, fully filterable

- Pill rail of category shortcuts (saved searches)
- Filter sidebar (zones, land types, price, size, features, infra, status)
- Sort + view toggle (cards / table)
- Active filter chip row
- Results

**Rule of thumb:** if a UI affordance applies a filter, it lives on Browse.
If it presents curated content, it lives on Discover. Do not blur this line —
having the pill rail on both pages (the original prototype's mistake) makes
Discover feel like a half-broken Browse.

---

## 3. URL parameters

`BrowsePage` accepts these route params (today held in `routeParams`, in
production in the URL query string):

| Param | Type | Effect |
|---|---|---|
| `category` | string | One of the keys in `PILLS` or `SHELVES`. Calls `buildFiltersForCategory(category)` to seed the filter state. `null` = "All". |
| `zones` | string[] | Pre-applies a zone filter (e.g. `?zones=Surf+City`). Used by "Browse similar listings in {zone}" from sold listings. |

**Resync rule:** whenever `routeParams.category` or `routeParams.zones`
changes, `BrowsePage` must rebuild filter state from those params. This is
what makes the "All" pill (and the category-clear ✕) actually clear prior
filter state. Don't initialize filters from params *only* on mount — it leaves
stale chips on subsequent navigations.

For production, also persist the full filter state to URL query params
(`?zones=...&price_min=...&features=...`) so the browser back button, refresh,
and shared links all work. The prototype intentionally doesn't do this.

---

## 4. Entry points to Browse (audit)

There are intentionally multiple ways to land on Browse. All must produce
identical results when given identical params:

| Source | Action |
|---|---|
| Top nav "Browse" | `go("browse")` — no params, full unfiltered list |
| Bottom nav "Browse" | same |
| Hero CTA on Discover | same |
| Shelf "See all →" | `goBrowse({ category: shelf.key })` |
| Pill rail on Browse | `goBrowse({ category: pill.key })` or `{ category: null }` |
| Footer category links | `goBrowse({ category })` |
| Sold-listing "Browse similar in {zone}" | `goBrowse({ category: null, zones: [zone] })` |
| "Saved" empty-state CTA | `go("browse")` |

If any of these diverge in behavior, that's a bug.

---

## 5. Active states

- **Top nav** highlights the current route. It does **not** breadcrumb the
  active category (e.g. "Browse / Beachfront"). Once the URL pattern is real,
  consider adding a breadcrumb under the top nav for `/browse/:category`.
- **Bottom nav** mirrors top nav; the "Saved" tab shows a count badge.
- **Pill rail** (Browse only) highlights `routeParams.category` or "All".
- **Results header** on Browse shows the active category as a removable chip
  with a ✕ that returns to "All".

---

## 6. Open product questions

These are intentionally unresolved — flag for product before shipping:

1. **"All" pill behavior on Browse.** Today, clicking "All" (or the category ✕)
   resets *every* filter, not just the category. Rationale: matches the user's
   mental model of "All = clean slate." Alternative: preserve manual sidebar
   edits and only clear the category. Pick one and document.
2. **Sign-in gating on save.** A guest who tries to save a listing gets the
   signup modal. If they dismiss it, the heart silently does nothing. Consider
   a fallback ("get a digest by email" or similar).
3. **Listing detail as overlay vs. route.** Prototype uses an overlay so the
   underlying list state is preserved. For SEO and shareable links, production
   should give it `/listings/:id`. Decide whether the back button restores the
   overlay or navigates to a fresh `/browse`.

---

## 7. Labels

The bottom nav says **Discover** (not "Home") to match the top nav. "Discover"
is the editorial brand promise; "Home" is generic. Don't drift.
