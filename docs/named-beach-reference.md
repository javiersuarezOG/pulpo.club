# Named-beach reference table

**Where it lives:** `automation/distance_fields.py` → `NAMED_BEACHES`.

This single tuple of `(name, lat, lng)` is the source of truth for two
otherwise unrelated systems:

1. **`dist_beach_km` haversine grid.** The `compute_dist_beach_km`
   function takes a listing's lat/lng and returns the distance in km to
   the closest entry in `NAMED_BEACHES`. Used for the editorial chip
   "Beach access · Xkm" and as a feature in the location-leg ranker.
2. **LLM prompt anchor table.** `automation/llm_enrichment_prompts.py`
   imports `NAMED_BEACHES` at module load and renders it into the
   `latlong` rule block of the system prompt as `AUTHORITATIVE BEACH
   COORDINATES`. When DeepSeek sees a coastal cue ("frente al mar",
   "two-minute walk to the beach", "beachfront") combined with a named
   beach, it is instructed to use the exact coordinates from this table
   rather than guess from memory.

## Why coupling them matters

Before this coupling existed, three failure modes co-existed:

| Failure | Symptom | Example |
|---|---|---|
| LLM placed a beachfront listing at an inland zone centroid | `dist_beach_km` reads 14 km on a real beachfront listing | Zonset listings in El Zonte showed 14.88 km |
| LLM hallucinated coordinates with `confidence=high` | Real Playa La Perla mapped at 13.336, -89.329 (in the ocean) | A/B test run, May 2026 |
| `NAMED_BEACHES` missing a stretch of coast | LLM placed coords correctly, but haversine to nearest reference still read 30+ km | Barra de Santiago (far west) |

A single source of truth fixes all three: the LLM gets the right
coordinates from the prompt; haversine gets the same coordinates as
reference points; adding a beach in one place propagates to both.

## How to add a new beach (or a new country / region)

1. **Add the entry to `NAMED_BEACHES`** in
   `automation/distance_fields.py`. Keep entries grouped by region
   with a short header comment so the file stays scannable.

   ```python
   NAMED_BEACHES = (
       # ── West (Sonsonate / Ahuachapán) ────────────────────
       ("Barra de Santiago",         13.7060, -89.9740),
       # …
   )
   ```

   Entries are ordered loosely west-to-east. Coordinates should be
   the *coastline* point of the named beach, not a town centroid —
   the table feeds haversine to coast and the prompt's "place at the
   coastline" instruction.

2. **Verify the prompt renders cleanly** by running:

   ```bash
   python3 -c "from automation.llm_enrichment_prompts import SYSTEM_PROMPT; print(SYSTEM_PROMPT)" | grep -A1 "<your beach name>"
   ```

   The new entry should appear in the `AUTHORITATIVE BEACH
   COORDINATES` block as `  - <name>: lat=13.XXXX, lng=-89.XXXX`.

3. **Sanity-check the haversine** by running the offline audit:

   ```bash
   python3 scripts/audit_beach_distance_consistency.py
   ```

   Listings near the new beach should now flag with smaller distances
   (or stop flagging entirely after the next nightly run re-enriches
   them with the new prompt).

4. **Re-enrich the affected listings.** Production listings carry
   stale lat/lng from before the addition. The next nightly run will
   re-enrich any listing whose sidecar entry predates the prompt
   change. To force-retrofit a known set, run:

   ```bash
   python3 scripts/retrofit_geocoding.py --limit 30      # smoke test
   python3 scripts/retrofit_geocoding.py                 # all suspects
   ```

   The script updates ranked.json AND
   `web/data/llm_enrichment.json` (the per-listing sidecar) so the
   next nightly run does not clobber the retrofit.

## Detecting when the table is missing a beach

`automation/unmapped_beach_detector.py` runs at the end of every
nightly pipeline. It flags listings whose copy claims walking-distance
or beachfront but whose lat/lng is > 5 km from any entry in
`NAMED_BEACHES`, then clusters those listings by 0.1° grid cell.

A cluster of ≥ 5 listings at the same grid cell with high median
distance is a strong signal that a beach is missing from the table.
The pipeline prints:

```
[unmapped_beaches] suspects=12 clusters=2
  cluster (13.7, -89.97) count=8 median_dist_beach_km=37.1
  cluster (13.18, -88.18) count=4 median_dist_beach_km=22.4
```

History of these counts streams to
`web/data/unmapped_beaches_history.jsonl` (append-only, same pattern
as `distance_fields_history.jsonl` and `source_health_history.jsonl`).
A monotonically rising `cluster_count` between runs means new
listings are landing in unmapped territory and the table needs an
entry.

The matching ad-hoc tool for development is
`scripts/audit_beach_distance_consistency.py` — same heuristic, but
run against ranked.json on demand and prints per-listing detail
rather than aggregated clusters.

## When to expand to a new country

The current table covers El Salvador. When pulpo.club adds another
country:

1. Add a region header comment + the country's named beaches to
   `NAMED_BEACHES` in the same shape — the prompt template renders
   them all together.
2. Update the validator bbox in `automation/llm_enrichment_schema.py`
   (`_SV_BBOX_LAT`, `_SV_BBOX_LNG`) to either widen or split per
   country. Without this, valid coords for the new country will fail
   the latlong validator and the entire enrichment of those listings
   will be rejected.
3. Re-run `python3 scripts/audit_beach_distance_consistency.py` after
   the next nightly run — the unmapped-beach detector's cluster
   output is the fastest way to find which beaches in the new country
   you missed.

## Don't add to `NAMED_BEACHES`

* Inland landmarks. The table is coastal-only; entries off the coast
  would skew haversine to coast for inland listings.
* Vague names ("La Playa", "Beach Resort") — the LLM can't
  disambiguate, so the prompt anchor doesn't help and the haversine
  reference is misplaced.
* Beaches you can't pin to within ~500 m. If you don't have a
  reliable coordinate, leave it out — the model's fallback (zone
  centroid) is less wrong than a bad reference point.
