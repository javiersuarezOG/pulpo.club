# Geocoding Extraction Probe

Sampled **50** of 811 catalog listings  
Goal: measure free-tier (HTML-only) geocoding hit rate per PRD §FR-5.2 priority chain.  

## Headline

- HTTP fetch success: **50 / 50** (100%)
- Coordinates extracted (any method): **22 / 50** (44% of fetched)
- Plausible SV coords (within bbox): **22 / 50** (44% of fetched)

## Per-source hit rate

| Source | n | Fetched | Extracted | SV-plausible |
|---|---:|---:|---:|---:|
| `bienesraices` | 23 | 23 | 0 | 0 |
| `century21` | 1 | 1 | 0 | 0 |
| `goodlife` | 3 | 3 | 0 | 0 |
| `oceanside` | 1 | 1 | 0 | 0 |
| `remax` | 22 | 22 | 22 | 22 |

## Extraction method (priority order)

| Method | Hits |
|---|---:|
| `gmaps_q_param` | 22 |
| `gmaps_3d4d_embed` | 0 |
| `data_lat_lng_attrs` | 0 |
| `og_meta` | 0 |
| `jsonld_geo` | 0 |
| `jsonld_root` | 0 |

## Cost implications

- HTML free-tier hit rate: **44%**
- At full catalog (811), Mapbox API calls per refresh: ~**454**
- Mapbox free tier (100k/mo): **within budget**
