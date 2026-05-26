from pathlib import Path

from automation.sitemap import SECTION_ENTRIES, write_sitemap


# Source-of-truth category list. Mirrors CATEGORY_KEYS in
# web/app/lib/categories.ts (Python can't import TS at runtime, so the
# list is duplicated; the test below catches drift).
CATEGORY_KEYS = {
    "new_this_week",
    "price_drops",
    "off_market",
    "best_documented",
    "beachfront",
    "ocean_view",
    "mountain_view",
    "water_features",
    "flat_buildable",
    "build_ready",
    "commercial",
    "under_50k",
    "under_100k",
    "motivated_sellers",
}


def test_sitemap_includes_public_legal_and_contact_routes():
    paths = {path for path, _changefreq, _priority in SECTION_ENTRIES}

    assert {"/terms", "/privacy", "/cookies", "/subscription", "/imprint", "/contact"} <= paths
    assert "/account" not in paths
    assert "/saved" not in paths


def test_sitemap_covers_every_browse_category():
    """Every CATEGORY_KEYS value must be a /browse?cat=… sitemap entry.

    A new category landing in web/app/lib/categories.ts without a matching
    sitemap entry would mean Google never discovers the new long-tail
    category URL. Test fails closed so the drift is caught at PR time.
    """
    paths = {path for path, _changefreq, _priority in SECTION_ENTRIES}
    expected = {f"/browse?cat={k}" for k in CATEGORY_KEYS}
    missing = expected - paths
    assert not missing, f"sitemap is missing /browse?cat=… entries: {sorted(missing)}"


def test_sitemap_hreflang_query_urls_are_escaped_once(tmp_path: Path):
    out = tmp_path / "sitemap.xml"

    write_sitemap(out, [])
    xml = out.read_text(encoding="utf-8")

    assert "https://pulpo.club/browse?cat=beachfront&amp;lang=es" in xml
    assert "&amp;amp;lang=es" not in xml


def test_sitemap_emits_every_category_with_hreflang(tmp_path: Path):
    """Each category entry produces one <url> with EN + ES + x-default
    hreflang alternates pointing at /browse?cat=…(&lang=es)."""
    out = tmp_path / "sitemap.xml"
    write_sitemap(out, [])
    xml = out.read_text(encoding="utf-8")

    for k in CATEGORY_KEYS:
        en = f"https://pulpo.club/browse?cat={k}"
        es = f"https://pulpo.club/browse?cat={k}&amp;lang=es"
        assert f"<loc>{en}</loc>" in xml, f"missing <loc> for {k}"
        assert f'hreflang="en" href="{en}"' in xml, f"missing en hreflang for {k}"
        assert f'hreflang="es" href="{es}"' in xml, f"missing es hreflang for {k}"
        assert f'hreflang="x-default" href="{en}"' in xml, f"missing x-default for {k}"
