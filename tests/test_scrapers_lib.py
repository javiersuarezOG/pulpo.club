"""Unit tests for the pulpo.scrapers.lib primitives (PR B1).

Each primitive ships with a focused test set. The Phase C scrapers
(Xitios, Agentiz, Santizo, CityMax Surf City, Vivo Latam, CSBR,
Realtor.com Intl, JamesEdition) will consume these helpers; tests here
lock the contracts so Phase C can rely on them without re-validating.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from pulpo.scrapers.lib import (
    discover_target,
    find_jsonld,
    listing_fingerprint,
    log_coverage,
    paginate,
)
from pulpo.scrapers.lib.coverage_logger import WARN_RATIO
from pulpo.scrapers.lib.dedup_hasher import (
    identity_fingerprint,
    property_fingerprint,
)


# ── paginator ──────────────────────────────────────────────────────────


@dataclass
class _FakeResp:
    text: str


def test_paginate_query_string_shape():
    seen_urls: list[str] = []

    def fetch(url: str) -> _FakeResp:
        seen_urls.append(url)
        return _FakeResp(text=f"<html>card-{url[-1]}</html>")

    pages = list(paginate(
        fetch,
        base_url="https://example.test/listings",
        page_param="page",
        max_pages=3,
    ))
    assert len(pages) == 3
    assert seen_urls == [
        "https://example.test/listings?page=1",
        "https://example.test/listings?page=2",
        "https://example.test/listings?page=3",
    ]


def test_paginate_url_pattern_shape():
    seen_urls: list[str] = []

    def fetch(url: str) -> _FakeResp:
        seen_urls.append(url)
        return _FakeResp(text="ok")

    list(paginate(
        fetch,
        base_url="https://example.test/listings",
        url_pattern="https://example.test/listings/page/{page}/",
        max_pages=2,
    ))
    assert seen_urls == [
        "https://example.test/listings/page/1/",
        "https://example.test/listings/page/2/",
    ]


def test_paginate_appends_query_string_correctly_when_base_has_query():
    seen: list[str] = []

    def fetch(url: str) -> _FakeResp:
        seen.append(url)
        return _FakeResp(text="ok")

    list(paginate(
        fetch,
        base_url="https://example.test/listings?country=sv",
        page_param="page",
        max_pages=1,
    ))
    assert seen == ["https://example.test/listings?country=sv&page=1"]


def test_paginate_stops_on_empty_signal_miss():
    fetched: list[int] = []

    def fetch(url: str) -> _FakeResp:
        page = int(url.split("=")[-1])
        fetched.append(page)
        # Pages 1+2 have cards; page 3 does not.
        if page <= 2:
            return _FakeResp(text="<div class=\"card\">x</div>")
        return _FakeResp(text="<p>No results</p>")

    pages = list(paginate(
        fetch,
        base_url="https://example.test/?q=lago",
        page_param="page",
        max_pages=10,
        stop_signal="<div class=\"card\">",
    ))
    assert [p for p, _ in pages] == [1, 2]
    assert fetched == [1, 2, 3]  # 3rd fetch happened but didn't yield


def test_paginate_stops_on_fetch_returning_none():
    def fetch(url: str) -> Optional[_FakeResp]:
        return None  # fetch failed first try

    pages = list(paginate(
        fetch,
        base_url="https://example.test/",
        page_param="page",
        max_pages=5,
    ))
    assert pages == []


def test_paginate_requires_exactly_one_of_page_param_or_url_pattern():
    try:
        list(paginate(lambda u: None, "https://x.test/", max_pages=1))
    except ValueError as e:
        assert "exactly one" in str(e)
    else:
        raise AssertionError("expected ValueError when neither supplied")


# ── jsonld ─────────────────────────────────────────────────────────────


def test_find_jsonld_extracts_single_block():
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@type": "Residence", "name": "Casa El Zonte"}
      </script>
    </head></html>
    """
    blocks = find_jsonld(html)
    assert len(blocks) == 1
    assert blocks[0]["name"] == "Casa El Zonte"


def test_find_jsonld_filters_by_schema_type():
    html = """
    <script type="application/ld+json">{"@type": "Residence", "name": "A"}</script>
    <script type="application/ld+json">{"@type": "Organization", "name": "B"}</script>
    """
    residences = find_jsonld(html, schema_type="Residence")
    assert len(residences) == 1
    assert residences[0]["name"] == "A"


def test_find_jsonld_handles_arrays_and_graphs():
    html = """
    <script type="application/ld+json">
      {"@graph": [
        {"@type": "Residence", "name": "A"},
        {"@type": "Residence", "name": "B"}
      ]}
    </script>
    """
    blocks = find_jsonld(html, schema_type="Residence")
    assert {b["name"] for b in blocks} == {"A", "B"}


def test_find_jsonld_tolerates_invalid_json():
    """A malformed block on the page must not prevent extraction of
    the valid blocks. Partial data > zero data."""
    html = """
    <script type="application/ld+json">{not valid json</script>
    <script type="application/ld+json">{"@type": "Residence", "name": "Survivor"}</script>
    """
    blocks = find_jsonld(html, schema_type="Residence")
    assert len(blocks) == 1
    assert blocks[0]["name"] == "Survivor"


def test_find_jsonld_returns_empty_for_no_blocks():
    assert find_jsonld("<html>no scripts here</html>") == []
    assert find_jsonld("") == []


# ── dedup_hasher ───────────────────────────────────────────────────────


def test_listing_fingerprint_is_stable():
    li = {
        "url": "https://example.test/listing/123",
        "title": "Casa de Playa",
        "price_usd": 325_000,
        "area_m2": 600,
        "zone": "el-zonte",
    }
    assert listing_fingerprint(li) == listing_fingerprint(li)


def test_listing_fingerprint_collapses_url_query_params():
    a = {"url": "https://x.test/lot/1", "title": "Lot", "price_usd": 100_000, "area_m2": 500, "zone": "z"}
    b = {"url": "https://x.test/lot/1?utm_source=fb", "title": "Lot", "price_usd": 100_000, "area_m2": 500, "zone": "z"}
    assert listing_fingerprint(a) == listing_fingerprint(b)


def test_listing_fingerprint_rounds_price_within_1k():
    a = {"url": "https://x.test/l", "title": "T", "price_usd": 325_000, "area_m2": 600, "zone": "z"}
    b = {"url": "https://x.test/l", "title": "T", "price_usd": 324_900, "area_m2": 600, "zone": "z"}
    assert listing_fingerprint(a) == listing_fingerprint(b)


def test_listing_fingerprint_rounds_area_within_50m2():
    a = {"url": "https://x.test/l", "title": "T", "price_usd": 100_000, "area_m2": 600, "zone": "z"}
    b = {"url": "https://x.test/l", "title": "T", "price_usd": 100_000, "area_m2": 612, "zone": "z"}
    assert listing_fingerprint(a) == listing_fingerprint(b)


def test_listing_fingerprint_differs_for_different_listings():
    a = {"url": "https://x.test/a", "title": "A", "price_usd": 100_000, "area_m2": 500, "zone": "z"}
    b = {"url": "https://x.test/b", "title": "B", "price_usd": 200_000, "area_m2": 1000, "zone": "y"}
    assert listing_fingerprint(a) != listing_fingerprint(b)


def test_listing_fingerprint_ignores_capitalization_and_punctuation_in_title():
    a = {"url": "https://x.test/l", "title": "Casa de Playa!", "price_usd": 100_000, "area_m2": 500, "zone": "z"}
    b = {"url": "https://x.test/l", "title": "casa  de   playa", "price_usd": 100_000, "area_m2": 500, "zone": "z"}
    assert listing_fingerprint(a) == listing_fingerprint(b)


# ── dedup_hasher: cross-domain dedup (the 2026-06 bug fix) ─────────────


def test_property_fingerprint_collides_across_domains():
    """Same physical property listed on two broker sites must collide.

    Regression test for the 2026-06 audit finding: when the fingerprint
    included URL, Santizo cross-posts to Encuentra24 looked unique on
    each side and the cross-source overlap matrix systematically
    under-counted. This test pins the fix: only title/price/area/zone
    matter for the property fingerprint, not URL.
    """
    a = {
        "url": "https://santizorealestate.com/casa/villa-coatepeque-123",
        "title": "Villa moderna con vista al lago",
        "price_usd": 425_000,
        "area_m2": 650,
        "zone": "lago-coatepeque",
    }
    b = {
        # Same physical property, different broker domain. Title
        # capitalization + a punctuation diff + a sub-$1k price gap +
        # sub-50 m² area drift are all tolerated by the property
        # fingerprint's normalization.
        "url": "https://www.encuentra24.com/el-salvador-es/villa-456",
        "title": "Villa Moderna Con Vista al Lago!",
        "price_usd": 425_200,
        "area_m2": 660,
        "zone": "lago-coatepeque",
    }
    assert property_fingerprint(a) == property_fingerprint(b)
    # listing_fingerprint is the back-compat alias for property_fingerprint.
    assert listing_fingerprint(a) == property_fingerprint(a)


def test_property_fingerprint_url_independent():
    """Two URLs, identical content → same property fingerprint. Generalized
    form of the cross-domain test; pins URL exclusion regardless of domain
    structure (CDN aliases, trailing slashes, mirror sites)."""
    a = {"url": "https://a.test/x", "title": "T", "price_usd": 100_000, "area_m2": 500, "zone": "z"}
    b = {"url": "https://b.test/y", "title": "T", "price_usd": 100_000, "area_m2": 500, "zone": "z"}
    assert property_fingerprint(a) == property_fingerprint(b)


# ── dedup_hasher: identity_fingerprint (within-source) ─────────────────


def test_identity_fingerprint_collides_for_same_source_and_source_id():
    """Within-source identity: same (source, source_id) → same hash.

    Used by the existence ledger to recognize a re-fetched listing across
    consecutive nightlies. Even if the price drops or title gets edited
    on the broker site, the identity stays stable as long as the scraper
    keeps emitting the same source_id."""
    a = {"source": "encuentra24", "source_id": "abc-123", "title": "Original", "price_usd": 100_000}
    b = {"source": "encuentra24", "source_id": "abc-123", "title": "Price reduced!", "price_usd": 90_000}
    assert identity_fingerprint(a) == identity_fingerprint(b)


def test_identity_fingerprint_distinguishes_sources():
    """Same source_id at two different sources → distinct identity.

    Source IDs are namespaced per source — e.g. realtyelsalvador's
    postid `4242` is unrelated to encuent24's listing id `4242`."""
    a = {"source": "encuentra24", "source_id": "4242"}
    b = {"source": "realtyelsalvador", "source_id": "4242"}
    assert identity_fingerprint(a) != identity_fingerprint(b)


def test_identity_fingerprint_falls_back_to_url_when_source_id_missing():
    """Defensive fallback when a scraper forgets to emit source_id.
    Better than collapsing every missing-id row into one identity hash."""
    a = {"source": "remax", "source_id": None, "url": "https://remax.test/listing/A"}
    b = {"source": "remax", "source_id": None, "url": "https://remax.test/listing/B"}
    # Distinct URLs → distinct identities even without source_id.
    assert identity_fingerprint(a) != identity_fingerprint(b)


def test_identity_fingerprint_orthogonal_to_property_fingerprint():
    """Identity and property are deliberately independent axes. Same
    property (cross-domain duplicate) has different identities; same
    identity (re-fetched listing) can have different property
    fingerprints if e.g. the price was reduced."""
    cross_domain_a = {
        "source": "santizo", "source_id": "s-1",
        "title": "Same Property", "price_usd": 425_000, "area_m2": 600, "zone": "z",
    }
    cross_domain_b = {
        "source": "encuentra24", "source_id": "e-9",
        "title": "Same Property", "price_usd": 425_000, "area_m2": 600, "zone": "z",
    }
    # Same property, different sources/IDs.
    assert property_fingerprint(cross_domain_a) == property_fingerprint(cross_domain_b)
    assert identity_fingerprint(cross_domain_a) != identity_fingerprint(cross_domain_b)


# ── coverage_logger ────────────────────────────────────────────────────


def test_log_coverage_writes_jsonl_row(tmp_path):
    out = tmp_path / "scraper_coverage_history.jsonl"
    row = log_coverage(
        "encuentra24",
        raw_count=300,
        kept_count=240,
        target_prd=2947,
        target_discovered=942,
        overlap_count=12,
        path=out,
    )
    assert out.exists()
    assert row["coverage_ratio_vs_discovered"] == round(240 / 942, 4)
    assert row["coverage_ratio_vs_prd"] == round(240 / 2947, 4)
    assert row["overlap_ratio"] == round(12 / 240, 4)

    # Append a second row; expect 2 lines total.
    log_coverage("xitios", raw_count=100, kept_count=80, target_discovered=100, path=out)
    lines = out.read_text().splitlines()
    assert len(lines) == 2
    second = json.loads(lines[1])
    assert second["source"] == "xitios"
    assert second["coverage_ratio_vs_discovered"] == 0.8


def test_log_coverage_status_warns_when_under_threshold(tmp_path):
    out = tmp_path / "cov.jsonl"
    # 80/300 vs discovered=300 → 0.267 → below WARN_RATIO → warn
    row = log_coverage("xitios", raw_count=300, kept_count=80, target_discovered=300, path=out)
    assert row["coverage_ratio_vs_discovered"] < WARN_RATIO
    assert row["status"] == "warn"


def test_log_coverage_status_ok_when_no_target_known(tmp_path):
    out = tmp_path / "cov.jsonl"
    row = log_coverage("nexo", raw_count=50, kept_count=40, path=out)
    assert row["coverage_ratio_vs_discovered"] is None
    assert row["coverage_ratio_vs_prd"] is None
    assert row["status"] == "ok"


# ── target_discoverer ──────────────────────────────────────────────────


def test_discover_target_parses_encuentra24_pattern():
    html = "En Encuentra24.com tenemos 942 Lotes y terrenos en venta"
    pattern = r"(\d[\d,.]*)\s+Lotes\s+y\s+terrenos"
    assert discover_target(html, pattern) == 942


def test_discover_target_handles_thousands_separator():
    html = "Showing 1,247 listings available"
    pattern = r"(\d[\d,.]*)\s+listings"
    assert discover_target(html, pattern) == 1247


def test_discover_target_returns_none_on_miss():
    html = "<html>no count here</html>"
    assert discover_target(html, r"(\d+)\s+lotes") is None


def test_discover_target_tries_multiple_patterns():
    html = "Inmuebles disponibles: 350"
    patterns = [
        r"Showing (\d+) listings",  # miss
        r"(\d+)\s+propiedades",     # miss
        r"Inmuebles[^:]*:\s*(\d+)", # hit
    ]
    assert discover_target(html, patterns) == 350


def test_discover_target_accepts_compiled_pattern():
    html = "Total: 50 listings found"
    pat = re.compile(r"Total:\s+(\d+)")
    assert discover_target(html, pat) == 50


def test_discover_target_returns_none_on_empty_html():
    assert discover_target("", r"(\d+)") is None
