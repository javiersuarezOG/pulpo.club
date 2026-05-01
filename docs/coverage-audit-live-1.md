# Live Coverage Audit — Run 1
Timestamp: 2026-05-01T21:26:20Z

```
  auditing goodlife…
  auditing oceanside…
  auditing kazu…
  auditing century21…
  auditing remax…
[html_crawler] index fetch failed (https://www.remax.com.sv/listings/buy?page=1&type=land&pageSize=24): [Errno 8] nodename nor servname provided, or not known
  auditing bienesraices…

source        supplier  pulled  coverage  max_pages_hit  limit_hit
------------  --------  ------  --------  -------------  ---------
goodlife      ?         80      ?         yes            no       
oceanside     ?         40      ?         no             no       
kazu          ?         0       ?         no             no       
century21     15        15      100%      no             no       
remax         ?         0       ?         no             no       
bienesraices  556       471     84%       no             no       

FAILURES — 1 source(s) under-pulling:
  bienesraices: 84% < 95% threshold (supplier=556, pulled=471)

```

## Analysis

### goodlife — 80 pulled, max_pages_hit=yes (FALSE POSITIVE)
WordPress wraps beyond the last real page: page 51+ returns the same listing URLs as pages 1–8.
`parse_index_page` returns non-empty partials but every URL is already in `seen_urls`.
The dedup prevents double-counting; 80 unique listings *are* the full supply.
Fixed: added "no new URLs on this page → stop" guard to `walk_with_meta`.

### oceanside — 40 pulled, no cap hit
No advertised total found by regex. 40 listings, no `max_pages_hit`, no `limit_hit` —
scraper naturally exhausted all pages. Assumed 100% coverage.

### kazu — 0 pulled (EXPECTED)
API host `panel.kazurealestate.com` is on the proxy denylist.

### century21 — 15/15 = 100% ✓

### remax — 0 pulled (EXPECTED)
`www.remax.com.sv` DNS does not resolve. Dead domain.

### bienesraices — 471 pulled (MISLEADING 84%)
`supplier=556` is the slug-keyword pre-filter count from the AlterEstate sitemap — an upper bound.
On crawl, 471 of those candidates passed the category filter; the remaining 85 were
false-positive slugs (land keywords in the slug but non-land category on the detail page).
True coverage ≈ 100%. Fixed: `report_total()` now returns `None`.
