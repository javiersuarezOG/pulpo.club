# Agricultural exclusion — producer / consumer contract

## TL;DR

- **Producer:** `pulpo/nlp_extractor.py` stamps `is_agricultural: bool` on every listing using the keyword list at `nlp_keywords/is_agricultural.json` (moves to `pulpo/countries/sv.json#agricultural_keywords` in PR D2).
- **Canonical FE consumer:** `web/app/data/use-listings.tsx::excludeAgricultural`. Every reader of `useListings()` inherits the filter.
- **Defense-in-depth:** `web/app/home/HomeShelf.jsx::pickTopByMasterAndSub` repeats `!l.is_agricultural` so direct-data callers can't bypass the hook.
- **Pipeline DROP:** `automation/run.py` purges **agricultural-LAND only** (built structures on agricultural land are kept; see the 2026-05-25 narrowing comment in `run.py`).
- **IG queue gate:** `automation/ig_photo_gate.py::_check_agricultural` keeps agricultural rows out of the Instagram batch even when `IG_GATE_EXCLUDE_AGRICULTURAL` is left at its `true` default.
- **Enforcement:** `tests/test_agricultural_exclusion.py` locks the canonical helper + the HomeShelf defense-in-depth clause.

## What "agricultural" means here

Pulpo's scope is beach + lake recreational real estate. "Agricultural" is the rural-production pool — coffee farms, cattle ranches, sugarcane fields, raw fincas with no structure. These properties show up in El Salvador inventory regularly but don't serve Pulpo's buyer.

The NLP extractor at `pulpo/nlp_extractor.py` runs the keyword regex from `nlp_keywords/is_agricultural.json` against `title + description`. Keywords use `\b` word boundaries — this is load-bearing (per CLAUDE.md): without `\b`, "ranch" substring-matches "rancho" (a beach pavilion) and breaks ~40 legitimate listings.

## The pipeline split (post-2026-05-25)

The original PR #418 purge dropped EVERY `is_agricultural=true` listing. The 2026-05-25 audit found this dropped ~140 BUILT houses/condos along with raw farms — properties like "casa en cafetal" (beach house with a small coffee plot) which the buyer genuinely wants.

Current narrowed rule in `automation/run.py`:

```python
ranked = [
    li for li in ranked
    if not (
        getattr(li, "property_type", None) == "land"
        and getattr(li, "is_agricultural", False)
    )
]
```

→ Pure agricultural LAND drops. Built structures (house / condo) with `is_agricultural=true` are KEPT.

The FE filter at `excludeAgricultural` then handles the remaining built-structure agricultural listings (currently letting them through; documented as a known gap below).

## Known gaps (BACKLOG)

The contract test enforces the canonical helper + HomeShelf defense-in-depth. It does NOT enforce the filter at:

- `automation/newsletter/*.py` — newsletter renderers
- `pulpo/featured_listing.py` — featured picker
- `automation/repick_heroes.py` — hero repick

These consume the post-purge `ranked.json` (which has no agricultural-LAND), but they currently do NOT filter out the agri-HOUSE/agri-CONDO pool that the narrowed purge retains. Whether this is a bug depends on product judgment:

- If agri-HOUSE / agri-CONDO are valid Pulpo inventory (the narrowed-purge intent), the newsletters + featured surfaces correctly include them and nothing needs to change.
- If those should NOT reach newsletters/featured/hero, a follow-up PR applies the same `is_agricultural` filter at each renderer.

Tracked in `BACKLOG.md`.

## How to add a new FE renderer that consumes listings

1. Use `useListings()` from `web/app/data/use-listings.tsx`. The filter is inherited automatically.
2. If you must read `ranked.json` directly, apply the filter:
   ```ts
   const visible = listings.filter(
     (l) => (l as Listing & { is_agricultural?: boolean }).is_agricultural !== true
   );
   ```
3. If you're adding a curated-shelf-style picker, also apply the inline `!l.is_agricultural` clause (defense-in-depth pattern from `HomeShelf.jsx`).

## How to add a new Python renderer that consumes listings

1. Filter via `li.get("is_agricultural") is True` (dict form) or `getattr(li, "is_agricultural", False)` (dataclass form).
2. If the surface is a diagnostic / observability dump (shelf audit, dedup audit, KPI dashboard, source health), no filter is needed — those operate on raw inventory by design.
