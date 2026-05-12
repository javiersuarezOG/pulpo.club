# Categories — vocabulary & lifecycle

Categories like `beachfront`, `under_50k`, `price_drops` are app-wide
concepts. They power **multiple surfaces**:

- Discover shelves (`SHELVES` in [`../data.jsx`](../data.jsx))
- Browse pill rail (`PILLS` in [`../data.jsx`](../data.jsx))
- Account preference chip selector (`/account/notifications`)
- Future weekly newsletter generator
- Future personalization (Discover re-rank, alerts, etc.)

The source of truth for the **key vocabulary** is
[`categories.ts`](./categories.ts). Display copy lives where the
surface lives — different surfaces want different label lengths and
tones, so we don't try to share copy.

---

## Adding a category

The change-cost depends on *where* the category needs to show up.

### To make a category user-selectable in `/account/notifications`

1. Confirm the key is in `CATEGORY_KEYS` in `categories.ts`. If not,
   add it (see "Adding to the whole-app vocabulary" below).
2. Append the key to `PREFERENCE_CATEGORY_KEYS` in `categories.ts`.
   Order in the array = chip rendering order.
3. Add a row to `PREFERENCE_CATEGORY_LABEL_KEY` in `categories.ts`:
   `<key>: "account.notif.pref_cat.<key>"`.
4. Add an i18n row in [`../i18n.jsx`](../i18n.jsx) under the
   `account.notif.pref_cat.*` block — both EN and ES.
5. If the EN label is a word/phrase that would silently look fine in
   Spanish (e.g. "Price Drops"), add it as an English canary in
   [`../../../tests/e2e/preview-smoke.spec.ts`](../../../tests/e2e/preview-smoke.spec.ts)
   under the locale-leak test's `SHARED_TOKENS` allowlist scan.

That's it for the preferences surface. TypeScript narrows
`PREFERENCE_CATEGORY_KEYS` against `CATEGORY_KEYS` via
`satisfies readonly CategoryKey[]`, so step 1 isn't optional — adding
a preference key that doesn't exist in the universe is a compile error.

### To make a category appear in the Browse pill rail or Discover shelves

Today these still live in [`../data.jsx`](../data.jsx) (`PILLS` and
`SHELVES`). Each has its own label object (`{ en, es }`) and, for
shelves, a `filter` predicate and `subline`.

1. Add the key to `CATEGORY_KEYS` in `categories.ts` if it's not
   already there.
2. Append a row to `PILLS` or `SHELVES` (or both) in `data.jsx` with
   the appropriate label + icon + filter.

> **Future consolidation:** the per-surface labels and filter
> predicates *could* live in `categories.ts` too, so adding a category
> is a single edit that propagates to pills + shelves + preferences
> simultaneously. We didn't do it in this PR because reconciling
> SHELVES (long magazine-style copy) and PILLS (short labels) into one
> structure is a meaningful refactor with its own risk surface. The
> current 3-place change-cost is documented honestly here; consolidate
> when the friction outweighs the refactor.

### To make a category app-wide (vocabulary)

1. Add the key to `CATEGORY_KEYS` in `categories.ts`.
2. Then follow the surface-specific instructions above for wherever
   you want it to render.

---

## Removing a category

1. Remove the key from `PREFERENCE_CATEGORY_KEYS` +
   `PREFERENCE_CATEGORY_LABEL_KEY` in `categories.ts` (or from
   `PILLS` / `SHELVES` in `data.jsx`, depending on where it lives).
2. Remove the EN + ES i18n rows.
3. Remove any English canary line from `preview-smoke.spec.ts`.

**No migration is needed for stored user data.** Both `sanitizePreferredCategories`
(`categories.ts`) and the newsletter generator (forward-looking) drop
unknown keys defensively. A user who had `beachfront` selected when
you remove it will simply stop seeing it; their other selections are
unaffected.

---

## Reordering chips

Reorder the entries in `PREFERENCE_CATEGORY_KEYS` in `categories.ts`.
That array's order is the chip rendering order in the preferences UI.

---

## Changing the max-selection cap

Edit `PREFERENCE_CATEGORIES_MAX` in `categories.ts`. The limit-hint
copy in `account.notif.pref_cat.limit_hint` is parameterized with
`{max}` — no string changes needed, but update the EN + ES copy if
the wording needs to change with the number.

---

## Why the preference subset is smaller than the full vocabulary

`CATEGORY_KEYS` has 15 entries today (the full Discover shelf
vocabulary). `PREFERENCE_CATEGORY_KEYS` has 6 — a curated subset
chosen to match how buyers describe what they're looking for:

- *What's new* filters: `new_this_week`, `price_drops`
- *Landscape* preferences: `beachfront`, `water_features`
- *Budget bands*: `under_50k`, `under_100k`

We deliberately leave out things like `off_market` (a Pulpo-Pro
content type, not a buyer preference), `best_documented` (an internal
quality signal, not a search criterion), and `motivated_sellers`
(also a Pulpo Pro positioning thing). If a key feels like editorial
or product framing rather than "what kind of land do I want," it
probably shouldn't be in the preference list.

---

## Newsletter generator contract (forward-looking)

When the newsletter generator lands, it will read
`user.profile.preferred_categories` (an array of `PreferenceCategoryKey`).
Contract:

- Empty array or missing field → send the unfiltered top-10 digest.
- Non-empty array → filter the candidate pool to listings matching
  ANY of the selected categories, then re-rank.
- The generator should defensively clamp >4 selections and drop
  unknown keys — newer clients may write keys older generators don't
  recognise.
