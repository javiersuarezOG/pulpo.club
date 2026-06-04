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
    }

The `target_discovered` field starts None — the coverage_logger updates
it after the first nightly run.
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
    },
    "nexo": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards",
        "strengths": ["SV native", "broad listings"],
        "failure_modes": ["placeholder photo URL pattern (filtered at validation)"],
        "owner_module": "pulpo.scrapers.nexo",
        "target_prd": None,
        "target_discovered": None,
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
    },
    # ── Phase C scrapers — entries added when each scraper PR lands ──
    "xitios": {
        "layer": "extraction",
        "fetch_kind": "static_http",
        "discovery_kind": "html_pagination",
        "extraction_kind": "html_cards + jsonld_residence (DRAFT)",
        "strengths": ["SV-native portal", "possible Coatepeque inventory"],
        "failure_modes": [
            "DRAFT skeleton — selectors are placeholders pending real HTML capture",
        ],
        "owner_module": "pulpo.scrapers.xitios",
        "target_prd": None,
        "target_discovered": None,
    },
    # Remaining Phase C placeholders below get filled in when each
    # scraper PR lands.
}


REQUIRED_KEYS: frozenset[str] = frozenset({
    "layer", "fetch_kind", "discovery_kind", "extraction_kind",
    "strengths", "failure_modes", "owner_module",
    "target_prd", "target_discovered",
})
