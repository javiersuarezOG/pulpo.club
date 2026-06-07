"""Tests for automation.dedup_audit — per-source dedup audit (PR D1).

Content-fingerprint dedup using ``pulpo.scrapers.lib.dedup_hasher``.
Complementary to ``automation/duplicate_detection.py``'s phone+coord
pair matching — catches same-listing-across-sources cross-broker cases.
"""
from __future__ import annotations

import json

from automation.dedup_audit import compute_audit, write_audit


def _li(**fields):
    """Build a dict listing with the fields the fingerprint reads."""
    base = {
        "source": "encuentra24",
        "url": "https://example.test/listing/1",
        "title": "Casa en El Zonte",
        "price_usd": 350_000,
        "area_m2": 600,
        "zone": "el-zonte",
    }
    base.update(fields)
    return base


def test_empty_dataset():
    audit = compute_audit([])
    assert audit["total_in_dataset"] == 0
    assert audit["total_unique_fingerprints"] == 0
    assert audit["per_source"] == {}
    assert audit["overlap_matrix"] == {}
    assert audit["duplicate_clusters"] == []


def test_single_source_no_overlap():
    listings = [
        _li(source="encuentra24", url="https://x.test/a", title="A"),
        _li(source="encuentra24", url="https://x.test/b", title="B"),
        _li(source="encuentra24", url="https://x.test/c", title="C"),
    ]
    audit = compute_audit(listings)
    assert audit["total_in_dataset"] == 3
    assert audit["total_unique_fingerprints"] == 3
    assert audit["per_source"]["encuentra24"] == {
        "raw": 3,
        "unique_in_source": 3,
        "kept_as_unique": 3,
        "shared_with_others": 0,
    }
    # No cross-source overlap because we only have one source.
    assert audit["overlap_matrix"] == {}


def test_overlap_matrix_is_symmetric():
    """Same listing posted by two brokers — fingerprint matches, both
    sources record the overlap, matrix is symmetric."""
    shared = dict(url="https://shared.test/same", title="Same Casa",
                  price_usd=300_000, area_m2=500, zone="el-tunco")
    listings = [
        _li(source="encuentra24", **shared),
        _li(source="remax", **shared),
    ]
    audit = compute_audit(listings)
    matrix = audit["overlap_matrix"]
    assert matrix["encuentra24"]["remax"] == 1
    assert matrix["remax"]["encuentra24"] == 1
    # Self-pairs never appear.
    assert "encuentra24" not in matrix.get("encuentra24", {})
    assert "remax" not in matrix.get("remax", {})


def test_duplicate_clusters_intra_source_grouping():
    """Two listings with identical fingerprint cluster together. The
    duplicate_clusters entry carries sources, count, cross_source flag,
    and projection samples for operator inspection.

    Cross-domain (different-URL) dupe detection lands when PR #753
    (fingerprint URL exclusion) merges — a follow-up commit on this
    branch will add the cross-domain assertion back at that point.
    """
    listings = [
        _li(
            source="remax",
            url="https://remax.test/abc",
            title="Casa Frente al Mar",
            price_usd=300_000,
            area_m2=500,
            zone="el-zonte",
        ),
        _li(
            source="remax",
            url="https://remax.test/abc",
            title="Casa Frente al Mar",
            price_usd=300_000,
            area_m2=500,
            zone="el-zonte",
        ),
    ]
    audit = compute_audit(listings)
    assert audit["total_unique_fingerprints"] == 1
    clusters = audit["duplicate_clusters"]
    assert len(clusters) == 1
    assert clusters[0]["count"] == 2
    assert clusters[0]["sources"] == ["remax"]
    assert clusters[0]["cross_source"] is False
    # Sample projection: source + content fields exposed for operator
    # inspection. The cap is 5 entries — only the first listing of the
    # cluster surfaces here since the test passes two identical rows.
    assert clusters[0]["samples"][0]["source"] == "remax"
    assert clusters[0]["samples"][0]["title"] == "Casa Frente al Mar"


def test_per_source_counts_shared_vs_unique():
    """Three sources: A has 2 unique + 1 shared with B; B has 1 shared with A
    + 1 unique; C has 1 totally unique. Verify counts."""
    unique_a1 = dict(url="https://x.test/a1", title="A1", price_usd=100_000, area_m2=500, zone="z")
    unique_a2 = dict(url="https://x.test/a2", title="A2", price_usd=200_000, area_m2=600, zone="z")
    shared_ab = dict(url="https://x.test/shared", title="Shared", price_usd=300_000, area_m2=700, zone="z")
    unique_b1 = dict(url="https://x.test/b1", title="B1", price_usd=400_000, area_m2=800, zone="z")
    unique_c1 = dict(url="https://x.test/c1", title="C1", price_usd=500_000, area_m2=900, zone="z")

    listings = [
        _li(source="srcA", **unique_a1),
        _li(source="srcA", **unique_a2),
        _li(source="srcA", **shared_ab),
        _li(source="srcB", **shared_ab),
        _li(source="srcB", **unique_b1),
        _li(source="srcC", **unique_c1),
    ]
    audit = compute_audit(listings)

    assert audit["per_source"]["srcA"]["kept_as_unique"] == 2  # a1, a2
    assert audit["per_source"]["srcA"]["shared_with_others"] == 1  # shared_ab
    assert audit["per_source"]["srcB"]["kept_as_unique"] == 1  # b1
    assert audit["per_source"]["srcB"]["shared_with_others"] == 1  # shared_ab
    assert audit["per_source"]["srcC"]["kept_as_unique"] == 1  # c1
    assert audit["per_source"]["srcC"]["shared_with_others"] == 0


def test_three_way_overlap_increments_each_pair():
    """When N sources share the same fingerprint, every pair (a,b)
    in the unordered set gets +1 in the matrix."""
    shared = dict(url="https://x.test/share", title="3way",
                  price_usd=100_000, area_m2=500, zone="z")
    listings = [
        _li(source="A", **shared),
        _li(source="B", **shared),
        _li(source="C", **shared),
    ]
    audit = compute_audit(listings)
    # 3 pairs: (A,B), (A,C), (B,C) — each gets +1 in both directions.
    assert audit["overlap_matrix"]["A"]["B"] == 1
    assert audit["overlap_matrix"]["A"]["C"] == 1
    assert audit["overlap_matrix"]["B"]["C"] == 1
    assert audit["overlap_matrix"]["B"]["A"] == 1
    assert audit["overlap_matrix"]["C"]["A"] == 1
    assert audit["overlap_matrix"]["C"]["B"] == 1


def test_missing_source_bucketed_under_unknown():
    """Listings without a source field land in the _unknown bucket
    rather than being silently dropped."""
    listings = [
        _li(url="https://x.test/with-source"),
        {"url": "https://x.test/no-source", "title": "T", "price_usd": 1, "area_m2": 1, "zone": "z"},
    ]
    listings[1].pop("source", None)
    audit = compute_audit(listings)
    assert "_unknown" in audit["per_source"]
    assert audit["per_source"]["_unknown"]["raw"] == 1


def test_overlap_count_is_per_unique_fingerprint_not_per_listing():
    """If src A has the same listing twice (two duplicate scrapes) and
    src B has it once, the matrix should record overlap=1, not 2.
    Otherwise duplicate scrapes would inflate the cross-source overlap."""
    shared = dict(url="https://x.test/share", title="X",
                  price_usd=100_000, area_m2=500, zone="z")
    listings = [
        _li(source="A", **shared),
        _li(source="A", **shared),  # A's duplicate scrape
        _li(source="B", **shared),
    ]
    audit = compute_audit(listings)
    assert audit["overlap_matrix"]["A"]["B"] == 1
    # A's per-source count: raw=2, unique=1, kept=0, shared=1
    assert audit["per_source"]["A"]["raw"] == 2
    assert audit["per_source"]["A"]["unique_in_source"] == 1
    assert audit["per_source"]["A"]["shared_with_others"] == 1


def test_sum_conservation_per_source():
    """For each source: unique_in_source == kept_as_unique + shared_with_others."""
    listings = [
        _li(source="A", url=f"https://x.test/a{i}", title=f"A{i}")
        for i in range(5)
    ] + [
        _li(source="B", url="https://x.test/a3", title="A3"),  # overlaps with A's #3
    ]
    audit = compute_audit(listings)
    for src, block in audit["per_source"].items():
        assert block["unique_in_source"] == block["kept_as_unique"] + block["shared_with_others"], (
            f"{src} violated sum conservation: {block}"
        )


def test_write_audit_emits_json_file(tmp_path):
    listings = [
        _li(source="A", url="https://x.test/a"),
        _li(source="B", url="https://x.test/b"),
    ]
    write_audit(listings, tmp_path)
    out = tmp_path / "dedup_audit.json"
    clusters = tmp_path / "duplicate_clusters.json"
    assert out.exists()
    assert clusters.exists()
    on_disk = json.loads(out.read_text())
    assert on_disk["total_in_dataset"] == 2
    assert sorted(on_disk["per_source"].keys()) == ["A", "B"]
