"""Per-scraper metadata — ToolSpec-shaped seam (PRD B1).

The medium-grade groundwork from the plan. Each entry mirrors a future
``ToolSpec`` (the events-discovery `tool_bench` pattern) so a later
retrofit can lift this dict into a registry + recommender without
rewriting any scraper. Today nobody reads it; tomorrow's ToolSpec
retrofit references it directly.

Adding a new scraper in Phase C? Append an entry here. The contract
test in ``tests/test_source_integration.py`` (extended in this PR)
asserts every registered scraper has a matching ``SCRAPER_METADATA``
entry with the required keys.

Schema:

    SCRAPER_METADATA["<slug>"] = {
        "layer":              "extraction",   # always; the layer abstraction is
                                              # for the future ToolSpec retrofit
        "fetch_kind":         "playwright" | "static_http" | "wp_rest" | "curl_cffi",
        "discovery_kind":     "html_pagination" | "sitemap" | "json_index" | "manual_curate",
        "extraction_kind":    free-form string (mapper name + auxiliary signals),
        "strengths":          list[str],      # what this scraper is good at
        "failure_modes":      list[str],      # known + recurring failure modes
        "owner_module":       "pulpo.scrapers.<slug>",
        "target_prd":         int | None,     # PRD-stated inventory hint
        "target_discovered":  int | None,     # populated each nightly by
                                              # lib.coverage_logger; runtime
                                              # field, NOT a static value
        "health_probe_url":   str | None,     # canonical landing/listing URL
                                              # the URL drift sentinel HEAD-
                                              # probes daily; None = source
                                              # has no single landing surface
                                              # (e.g., sitemap-XML-only)
    }

The `target_discovered` field starts None — the coverage_logger updates
it after the first nightly run.

The `health_probe_url` field is consumed by
``automation/url_drift_sentinel.py`` (PR-D1). Drift states `unreachable`
or persistent `redirect_drift` page Slack via the watchdog — catches a
source going down one layer earlier than waiting for the next nightly
to return zero listings.
"""
from __future__ import annotations


SCRAPER_METADATA: dict[str, dict] = {
    # ── Existing scrapers (11) — populated by reading code, not behavior change ──
    "bienesraices": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards (house + condo only)",
        "strengths": ["dedicated SV real-estate portal", "structured property data"],
        "failure_modes": ["limited inventory for non-residential"],
        "owner_module": "pulpo.scrapers.bienesraices",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://secure.alterestate.com/api/v1/properties/sitemap/",
    },
    "century21": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards (franchise template)",
        "strengths": ["franchise-standard schema", "agent attribution"],
        "failure_modes": ["pagination edge cases", "WAF challenges occasionally"],
        "owner_module": "pulpo.scrapers.century21",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://www.century21elsalvador.com",
    },
    "citymax": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards + force_vacation_gate",
        "strengths": ["broad franchise inventory", "category-rich"],
        "failure_modes": ["inland-dominant — vacation gate strict"],
        "owner_module": "pulpo.scrapers.citymax",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://www.citymax-sv.com",
    },
    "elagente": {
        "layer": "extraction",
        "fetch_kind": "curl_cffi",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards via GCP scrape-shim",
        "strengths": ["agent-curated", "SV native"],
        "failure_modes": ["WAF blocks Azure IPs — requires GCP shim"],
        "owner_module": "pulpo.scrapers.elagente",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://www.elagenteinmobiliario.com",
    },
    "encuentra24": {
        "layer": "extraction",
        "fetch_kind": "playwright",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards + jsonld_residence",
        "strengths": ["largest SV inventory", "broad coverage"],
        "failure_modes": ["rate-limit at >50 pages", "cloudflare challenges"],
        "owner_module": "pulpo.scrapers.encuentra24",
        "target_prd": 2947,
        "target_discovered": None,
        "health_probe_url": "https://www.encuentra24.com/el-salvador-es/bienes-raices",
    },
    "essurf": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards (coastal specialist)",
        "strengths": ["beach corridor specialist", "La Libertad inventory"],
        "failure_modes": ["thin volume", "niche site"],
        "owner_module": "pulpo.scrapers.essurf",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://elsalvadorsurfrealestate.com",
    },
    "goodlife": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards + multi-signal type classifier",
        "strengths": ["high-quality SV inventory", "vacation-focused"],
        "failure_modes": ["type ambiguity on mixed-use lots"],
        "owner_module": "pulpo.scrapers.goodlife",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://goodlifeelsalvador.com/",
    },
    "nexo": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards",
        "strengths": ["SV native", "broad listings"],
        "failure_modes": [
            "placeholder photo URL pattern (filtered at validation)",
            # 2026-06-05 (PR-S2): the parser intentionally narrows to
            # listing_type.category=='terrenos' + sale_rent=='venta'
            # (see pulpo/scrapers/nexo.py:247). Per the docstring,
            # ~1% of nexo's catalogue meets that filter — so single-
            # digit yields are EXPECTED, not a bleed. PR-S1's
            # degradation detection should treat the historic floor
            # (currently ~5) as the median; further "degraded"
            # alerts would mean the filter dropped to 0, which IS
            # actionable.
            "intentional-narrow-filter (terrenos-venta only)",
        ],
        "owner_module": "pulpo.scrapers.nexo",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://nexo.com.sv",
    },
    "oceanside": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards (beach-lot specialist)",
        "strengths": ["beach-lot focus", "La Libertad + Atami"],
        "failure_modes": ["very thin inventory"],
        "owner_module": "pulpo.scrapers.oceanside",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://oceansideelsalvador.com/",
    },
    "realtyelsalvador": {
        "layer": "extraction",
        "fetch_kind": "curl_cffi",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards via GCP scrape-shim",
        "strengths": ["agent-curated", "documented properties"],
        "failure_modes": ["WAF blocks Azure IPs", "cached via 25h freshness window"],
        "owner_module": "pulpo.scrapers.realtyelsalvador",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://realtyelsalvador.com",
    },
    "remax": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards (franchise template) + jsonld_residence",
        "strengths": ["franchise-standard schema", "agent attribution"],
        "failure_modes": ["pagination edge cases"],
        "owner_module": "pulpo.scrapers.remax",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://www.remax-elsalvador.com",
    },
    # ── Phase C scrapers — DRAFT skeletons (PRs C2-C8) ──
    # All seven entries land in the same PR as their scraper files.
    # Each remains DRAFT in failure_modes until the per-source
    # calibration pass replaces placeholder selectors with real ones.
    "agentiz": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "jsonld_residence (DRAFT) — check for JSON API first",
        "strengths": ["agency-sourced", "possible JSON API"],
        "failure_modes": ["DRAFT skeleton — calibration pass required"],
        "owner_module": "pulpo.scrapers.agentiz",
        "target_prd": None,
        "target_discovered": None,
        "health_probe_url": "https://sv.agentiz.com/en",
    },
    "santizo": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "jsonld_listing (case-insensitive @type) + ?page=N catalog walk → per-detail JSON-LD",
        "strengths": ["#1 SV agency per their own marketing", "high data completeness"],
        "failure_modes": [
            "carries cross-country inventory (DR) — filtered by URL slug + addressCountry",
            "expect overlap with encuentra24",
        ],
        "owner_module": "pulpo.scrapers.santizo",
        "target_prd": 150,
        "target_discovered": None,
        "health_probe_url": "https://santizorealestate.com/s/ventas",
    },
    "citymax_sc": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "catalog ItemList JSON-LD → per-detail RealEstateListing JSON-LD",
        "strengths": ["coastal/Surf City focus", "catalog JSON-LD ItemList = clean URL discovery"],
        "failure_modes": [
            "?in=terrenos,fincas filter is non-functional — page returns all types regardless; rely on downstream type classifier",
            "may share inventory with citymax (verify via dedup_audit overlap matrix after first nightly)",
        ],
        "owner_module": "pulpo.scrapers.citymax_sc",
        "target_prd": 300,
        "target_discovered": None,
        "health_probe_url": "https://www.citymax-sc.com/inmuebles/venta/el-salvador",
    },
    "vivolatam": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "sitemap",
        "extraction_kind": "sitemap-driven (catalog is client-rendered) → per-detail RealEstateListing JSON-LD",
        "strengths": ["regional portal", "verified seller ecosystem", "sitemap-driven discovery (no SSR-dependence)"],
        "failure_modes": [
            "multi-country site — sitemap_url_filter forces /<active-country>/ + for-sale tokens (rents excluded)",
            "sitemap-only discovery means catalog UI is not the URL source — if vivolatam restructures the sitemap path, we re-discover the new feed",
        ],
        "owner_module": "pulpo.scrapers.vivolatam",
        "target_prd": 400,
        "target_discovered": None,
        "health_probe_url": "https://www.vivolatam.com/sitemap/property_listings.xml",
    },
    "csbr": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "WordPress /page/N/ walk → JSON-LD RealEstateListing (@graph) + Houzez li.item-price for price",
        "strengths": [
            "official industry guild (institutional source — +1 quality_score nudge)",
            "type-filtered catalog (fincas+playa+terrenos) — pre-narrowed inventory",
        ],
        "failure_modes": [
            "JSON-LD RealEstateListing lacks `offers` — price scraped from Houzez <li class='item-price'> instead",
            "URL-encoded type[]=fincas+playa+terrenos filter MUST be preserved across pagination",
        ],
        "owner_module": "pulpo.scrapers.csbr",
        "target_prd": 293,
        "target_discovered": None,
        "health_probe_url": "https://www.camarabienesraices.com.sv/resultado-busqueda/?keyword=&type%5B0%5D=fincas&type%5B1%5D=playa&type%5B2%5D=terrenos",
    },
    "realtor_intl_sv": {
        "layer": "extraction",
        "fetch_kind": "curl_cffi",
        "discovery_kind": "html_pagination",
        "extraction_kind": "jsonld_residence (DRAFT) — US-based portal, anti-bot expected",
        "strengths": ["international aggregator", "broad gap-fill coverage"],
        "failure_modes": [
            "DRAFT skeleton — calibration pass required",
            "ToS clearance required before live runs (US-based franchise)",
            "anti-bot — likely needs residential proxy or curl_cffi",
        ],
        "owner_module": "pulpo.scrapers.realtor_intl_sv",
        "target_prd": 633,
        "target_discovered": None,
        "health_probe_url": "https://www.realestate.com.au/international/sv",
    },
    "jamesedition": {
        "layer": "extraction",
        "fetch_kind": "curl_cffi",
        "discovery_kind": "html_pagination",
        "extraction_kind": "jsonld_listing (case-insensitive @type) — Coatepeque luxury",
        "strengths": ["luxury inventory", "Coatepeque-specific gap-fill"],
        "failure_modes": [
            "DRAFT — Cloudflare JS challenge blocks both httpx and curl_cffi (chrome131, chrome124, safari17_0, safari18_0, edge101 all return HTTP 403 + 'Just a moment...' on 2026-06-05). Selectors + policy are calibrated for the moment the challenge relaxes OR a follow-up adds Playwright transport to the skeleton helper (encuentra24's pattern).",
            "low volume but high-value; some listings exceed PRICE_FLAG_MAX ($20M) and will be FLAGGED (kept + warned)",
        ],
        "owner_module": "pulpo.scrapers.jamesedition",
        "target_prd": 50,
        "target_discovered": None,
        "health_probe_url": "https://www.jamesedition.com/es/real_estate/house-lago-de-coatepeque-el-salvador",
    },
}


REQUIRED_KEYS: frozenset[str] = frozenset({
    "layer", "fetch_kind", "discovery_kind", "extraction_kind",
    "strengths", "failure_modes", "owner_module",
    "target_prd", "target_discovered",
    "health_probe_url",
})
