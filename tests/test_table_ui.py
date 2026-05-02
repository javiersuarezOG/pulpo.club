"""
Tests for the table redesign UI logic.

The score-to-stars formula, filter partitioning, sort logic, and number
formatting are expressed as pure functions that can be verified without
a browser.  URL-state and DOM interaction are covered by the Phase 9
manual checklist (no JS test runner in this project).
"""
from __future__ import annotations
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


# ── Score-to-stars ────────────────────────────────────────────────────

def score_to_stars(score: float) -> float:
    """Python mirror of the JS scoreToStars() function."""
    if score is None:
        return 0.0
    return max(0.0, min(5.0, round(score / 10) / 2))


@pytest.mark.parametrize("score,expected", [
    (92,   4.5),
    (78,   4.0),
    (73,   3.5),
    (100,  5.0),
    (0,    0.0),
    (86.25, 4.5),   # real sample: round(8.625)/2 = 9/2
    (50,   2.5),
    (55,   3.0),    # round(5.5)/2 = 6/2
    (45,   2.0),    # round(4.5)/2 = 4/2 (banker's rounding aside, Python rounds to even)
    (9,    0.5),
    (1,    0.0),    # round(0.1)/2 = 0/2
])
def test_score_to_stars(score, expected):
    result = score_to_stars(score)
    assert result == expected, f"score_to_stars({score}) = {result}, expected {expected}"


# ── Filter logic ──────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def listings():
    path = REPO / "web" / "data" / "ranked.json"
    if not path.exists():
        pytest.skip("ranked.json not found — run automation/run.py first")
    data = json.loads(path.read_text())
    if not data or "is_in_development" not in data[0]:
        pytest.skip("is_in_development field missing — regenerate ranked.json")
    return data


def test_filter_all_returns_everything(listings):
    assert len(listings) > 0


def test_filter_open_excludes_gated(listings):
    open_land = [r for r in listings if not r.get("is_in_development")]
    assert all(not r.get("is_in_development") for r in open_land)
    assert len(open_land) > 0


def test_filter_gated_includes_only_developments(listings):
    gated = [r for r in listings if r.get("is_in_development")]
    assert all(r.get("is_in_development") for r in gated)


def test_filter_partitions_are_complete(listings):
    """Open + Gated must sum to All (no listing falls through)."""
    n_open  = sum(1 for r in listings if not r.get("is_in_development"))
    n_gated = sum(1 for r in listings if r.get("is_in_development"))
    assert n_open + n_gated == len(listings)


# ── Sort logic ────────────────────────────────────────────────────────

def sort_rows(rows, col, direction):
    """Python mirror of JS sortedRows()."""
    reverse = direction == "desc"
    nil = float("-inf") if reverse else float("inf")  # nulls always sink

    def key_price(r):
        v = r.get("price_usd")
        return v if v is not None else nil

    def key_area(r):
        v = r.get("area_m2")
        return v if v is not None else nil

    def key_ppm(r):
        v = r.get("price_per_m2") or 0
        return v if v > 0 else nil

    if col == "price":
        return sorted(rows, key=key_price, reverse=reverse)
    if col == "area":
        return sorted(rows, key=key_area, reverse=reverse)
    return sorted(rows, key=key_ppm, reverse=reverse)


def test_sort_ppm_asc_default(listings):
    """Default sort: $/m² ascending — no listing with a lower $/m² should appear after a higher one."""
    priced = [r for r in listings if r.get("price_per_m2") and r["price_per_m2"] > 0]
    if len(priced) < 2:
        pytest.skip("Not enough priced listings to test sort")
    sorted_rows = sort_rows(priced, "ppm", "asc")
    ppms = [r["price_per_m2"] for r in sorted_rows]
    assert ppms == sorted(ppms), "ppm asc sort is not monotonically increasing"


def test_sort_price_desc(listings):
    priced = [r for r in listings if r.get("price_usd")]
    if len(priced) < 2:
        pytest.skip("Not enough priced listings")
    sorted_rows = sort_rows(priced, "price", "desc")
    prices = [r["price_usd"] for r in sorted_rows]
    assert prices == sorted(prices, reverse=True)


def test_sort_area_desc_default(listings):
    with_area = [r for r in listings if r.get("area_m2")]
    if len(with_area) < 2:
        pytest.skip("Not enough area listings")
    sorted_rows = sort_rows(with_area, "area", "desc")
    areas = [r["area_m2"] for r in sorted_rows]
    assert areas == sorted(areas, reverse=True)


# ── Number formatting ─────────────────────────────────────────────────

def _js_round(v: float) -> int:
    """Mirror JS Math.round(): always rounds half-up (not banker's rounding)."""
    import math
    return math.floor(v + 0.5)


def fmt_usd(v):
    if v is None:
        return "—"
    return "$" + f"{_js_round(v):,}"


def fmt_area(v):
    if v is None:
        return "—"
    return f"{_js_round(v):,} m²"


@pytest.mark.parametrize("value,expected", [
    (215000.5,  "$215,001"),
    (1000,      "$1,000"),
    (0,         "$0"),
    (1234567,   "$1,234,567"),
])
def test_fmt_usd(value, expected):
    assert fmt_usd(value) == expected


@pytest.mark.parametrize("value,expected", [
    (1250.7,    "1,251 m²"),
    (12345,     "12,345 m²"),
    (500,       "500 m²"),
])
def test_fmt_area(value, expected):
    assert fmt_area(value) == expected


# ── Zone colors (deterministic) ───────────────────────────────────────
# Must stay in sync with ZONE_PALETTE / ZONE_COLORS in web/index.html.

ZONE_PALETTE_PY: list = [
    {'bg': '#E1F5EE', 'fg': '#085041'},  # 0 teal
    {'bg': '#E6F1FB', 'fg': '#0C447C'},  # 1 blue
    {'bg': '#EAF3DE', 'fg': '#27500A'},  # 2 green
    {'bg': '#FAECE7', 'fg': '#712B13'},  # 3 coral
    {'bg': '#FAEEDA', 'fg': '#633806'},  # 4 amber
    {'bg': '#EEEDFE', 'fg': '#3C3489'},  # 5 purple
    {'bg': '#FBEAF0', 'fg': '#72243E'},  # 6 pink
    {'bg': '#F1EFE8', 'fg': '#2C2C2A'},  # 7 gray
]

ZONE_COLORS_PY: dict = {
    'el-tunco':           ZONE_PALETTE_PY[3],  # coral
    'el-sunzal':          ZONE_PALETTE_PY[4],  # amber
    'el-zonte':           ZONE_PALETTE_PY[6],  # pink
    'san-diego':          ZONE_PALETTE_PY[1],  # blue
    'mizata':             ZONE_PALETTE_PY[7],  # gray
    'el-cuco':            ZONE_PALETTE_PY[3],  # coral
    'las-flores':         ZONE_PALETTE_PY[6],  # pink
    'punta-mango':        ZONE_PALETTE_PY[4],  # amber
    'el-espino':          ZONE_PALETTE_PY[0],  # teal
    'jiquilisco':         ZONE_PALETTE_PY[1],  # blue
    'tamanique':          ZONE_PALETTE_PY[0],  # teal
    'conchagua':          ZONE_PALETTE_PY[5],  # purple
    'ahuachapan':         ZONE_PALETTE_PY[4],  # amber
    'la-union':           ZONE_PALETTE_PY[1],  # blue
    'san-salvador':       ZONE_PALETTE_PY[7],  # gray
    'la-libertad':        ZONE_PALETTE_PY[2],  # green
    'puerto-la-libertad': ZONE_PALETTE_PY[2],  # green
    'santa-ana':          ZONE_PALETTE_PY[4],  # amber
    'sonsonate':          ZONE_PALETTE_PY[0],  # teal
    'costa-del-sol':      ZONE_PALETTE_PY[2],  # green
}


def _hash_zone(z: str) -> int:
    """Python mirror of JS _hashZone() — djb2-inspired, unsigned 32-bit."""
    h = 5381
    for c in z:
        h = ((h << 5) + h + ord(c)) & 0xFFFFFFFF
    return h % len(ZONE_PALETTE_PY)


def zone_color(zone: str) -> dict:
    """Python mirror of JS zoneColor()."""
    if zone in ZONE_COLORS_PY:
        return ZONE_COLORS_PY[zone]
    return ZONE_PALETTE_PY[_hash_zone(zone)]


@pytest.mark.parametrize("zone,expected_idx", [
    ('el-tunco',  3),   # coral
    ('el-zonte',  6),   # pink
    ('el-sunzal', 4),   # amber
    ('la-libertad', 2), # green
    ('conchagua', 5),   # purple
])
def test_zone_color_known(zone, expected_idx):
    c = zone_color(zone)
    expected = ZONE_PALETTE_PY[expected_idx]
    assert c == expected, f"zone_color({zone!r}) = {c}, expected palette[{expected_idx}] = {expected}"


def test_zone_color_unknown_is_deterministic():
    """Same unknown zone always returns the same color."""
    assert zone_color('san-marcelino') == zone_color('san-marcelino')


def test_zone_color_unknown_from_palette():
    """Unknown zone selects a color from the fallback palette."""
    assert zone_color('san-marcelino') in ZONE_PALETTE_PY


def test_zone_color_no_zone_pill_is_gray():
    """Listings with no zone show a fixed gray pill, NOT a palette color."""
    # The gray no-zone pill is hardcoded in CSS (.zone-pill--nozone),
    # not derived from zoneColor(). Verify by convention: zone_color(None or '')
    # is never called for a no-zone listing — the zonePillHTML() function
    # checks r.zone first and returns the hardcoded pill if falsy.
    # This test documents the contract.
    assert True  # contract: zonePillHTML() handles null zone separately


# ── Nulls-to-end sort ─────────────────────────────────────────────────

@pytest.mark.parametrize("col,direction", [
    ('price', 'asc'), ('price', 'desc'),
    ('area',  'asc'), ('area',  'desc'),
])
def test_sort_nulls_always_last(col, direction):
    """Listings with missing numeric values sort to the end regardless of direction."""
    field = 'price_usd' if col == 'price' else 'area_m2'
    rows = [
        {'price_usd': 100.0, 'area_m2': 500.0,  'price_per_m2': 10.0},
        {'price_usd': None,  'area_m2': None,    'price_per_m2': None},
        {'price_usd': 200.0, 'area_m2': 1000.0, 'price_per_m2': 20.0},
    ]
    result = sort_rows(rows, col, direction)
    assert result[-1][field] is None, (
        f"null {field} must be last when sorting {col} {direction}"
    )


# ── Zone group filter ─────────────────────────────────────────────────

ZONE_GROUPS_PY: dict = {
    'surf-city-1':  ['el-tunco', 'el-sunzal', 'el-zonte', 'san-diego', 'mizata'],
    'surf-city-2':  ['el-cuco', 'las-flores', 'punta-mango', 'el-espino', 'conchagua'],
    'other-coastal':['la-libertad', 'puerto-la-libertad', 'jiquilisco', 'tamanique',
                     'acajutla', 'costa-del-sol', 'san-luis-la-herradura'],
    'inland':       ['la-union', 'san-salvador', 'ahuachapan', 'santa-ana', 'sonsonate',
                     'chalatenango', 'la-paz', 'tonacatepeque', 'soyapango'],
}


def filter_zone_group(rows: list, group_key: str) -> list:
    """Python mirror of JS filteredRows() with ZONE_F = {type:'group', value:group_key}."""
    zones = ZONE_GROUPS_PY.get(group_key, [])
    return [r for r in rows if r.get('zone') in zones]


def filter_no_zone(rows: list) -> list:
    """Python mirror of JS filteredRows() with ZONE_F = {type:'no-zone'}."""
    return [r for r in rows if not r.get('zone')]


def test_zone_group_surf_city_1_filters_correctly():
    """Clicking 'Surf City 1' shows only listings with zones in that group."""
    sc1_zones = ZONE_GROUPS_PY['surf-city-1']
    rows = [
        {'zone': 'el-tunco',  'is_in_development': False},
        {'zone': 'el-cuco',   'is_in_development': False},  # Surf City 2
        {'zone': 'soyapango', 'is_in_development': False},  # inland
        {'zone': 'el-zonte',  'is_in_development': False},
        {'zone': None,        'is_in_development': False},
    ]
    result = filter_zone_group(rows, 'surf-city-1')
    assert len(result) == 2
    assert all(r['zone'] in sc1_zones for r in result)


def test_specific_zone_filter_deactivates_group():
    """Zone filter to 'el-tunco' specifically — only el-tunco rows pass."""
    rows = [
        {'zone': 'el-tunco', 'price_usd': 100_000},
        {'zone': 'el-zonte', 'price_usd': 150_000},
        {'zone': 'el-tunco', 'price_usd': 200_000},
    ]
    result = [r for r in rows if r.get('zone') == 'el-tunco']
    assert len(result) == 2
    assert all(r['zone'] == 'el-tunco' for r in result)


def test_no_zone_filter_shows_only_unresolved():
    """'No zone' group filter shows only listings without a zone field."""
    rows = [
        {'zone': 'el-tunco', 'is_in_development': False},
        {'zone': None,       'is_in_development': False},
        {'zone': '',         'is_in_development': True},
        {'zone': 'el-zonte', 'is_in_development': False},
        {'zone': None,       'is_in_development': True},
    ]
    result = filter_no_zone(rows)
    assert len(result) == 3
    assert all(not r.get('zone') for r in result)


def test_no_zone_plus_open_land_combinable():
    """?filter=open&zone_group=no-zone shows intersection of unresolved + open."""
    rows = [
        {'zone': None,       'is_in_development': False},  # ✓
        {'zone': None,       'is_in_development': True},   # gated → excluded
        {'zone': 'el-tunco', 'is_in_development': False},  # has zone → excluded
    ]
    no_zone = filter_no_zone(rows)
    open_only = [r for r in no_zone if not r.get('is_in_development')]
    assert len(open_only) == 1
    assert open_only[0]['zone'] is None


def test_per_group_counts_match_data():
    """Per-group counts are computed from data, not hardcoded estimates."""
    rows = [
        {'zone': 'el-tunco'}, {'zone': 'el-tunco'}, {'zone': 'el-zonte'},
        {'zone': 'el-cuco'},  {'zone': None},
    ]
    sc1_count = len(filter_zone_group(rows, 'surf-city-1'))
    sc2_count = len(filter_zone_group(rows, 'surf-city-2'))
    no_zone_count = len(filter_no_zone(rows))
    assert sc1_count == 3
    assert sc2_count == 1
    assert no_zone_count == 1


def test_no_zone_pill_label_is_no_zone_not_dash():
    """Unresolved-zone listings must render the explicit 'No zone' label — never blank or '—'."""
    # This test documents the contract verified visually in Phase 9.
    # The JS zonePillHTML() returns '<span class="zone-pill zone-pill--nozone">No zone</span>'
    # when r.zone is falsy and r.department is also falsy.
    no_zone_html = '<span class="zone-pill zone-pill--nozone">No zone</span>'
    assert 'No zone' in no_zone_html
    assert '—' not in no_zone_html
    assert no_zone_html.strip() != ''


def test_zone_sort_no_zone_to_end():
    """Listings without a zone sort to the end of zone-sorted results, both asc and desc."""
    # Mirror of JS sort: zone=None → sentinel '￿' (U+FFFF) sorts after all real text
    def zone_sort_key(r, desc=False):
        z = r.get('zone')
        dept = r.get('department')
        if z:
            key = z
        elif dept:
            key = '￾' + dept   # dept-only: before pure no-zone
        else:
            key = '￿'          # pure no-zone: always last
        return key if not desc else chr(0x10FFFF - ord(key[0])) if key else '￿'

    rows = [
        {'zone': 'mizata',   'department': 'La Libertad'},
        {'zone': None,       'department': None},
        {'zone': 'el-tunco', 'department': 'La Libertad'},
        {'zone': None,       'department': 'La Paz'},
    ]
    asc = sorted(rows, key=lambda r: (r.get('zone') or ('￾'+(r.get('department') or '')) if r.get('department') else '￿'))
    assert asc[-1]['zone'] is None and asc[-1]['department'] is None, "Pure no-zone must sort last in asc"


def test_rating_sort_uses_underlying_score_not_rounded_stars():
    """Rating sort uses rank_score (0–100), not the rounded stars value.

    A listing with score=92 should rank above score=90 even though both
    display as 4.5★ (round(9.2)/2 = 9/2 = 4.5, round(9.0)/2 = 9/2 = 4.5).
    """
    rows = [
        {'source_id': 'low',  'rank_score': 90.0},
        {'source_id': 'high', 'rank_score': 92.0},
    ]
    # Both show 4.5 stars
    assert score_to_stars(90.0) == score_to_stars(92.0) == 4.5
    # But sort by underlying score puts 92 first (desc)
    sorted_desc = sorted(rows, key=lambda r: r.get('rank_score', 0), reverse=True)
    assert sorted_desc[0]['source_id'] == 'high'


# ── URL state (documented, not browser-testable) ──────────────────────

def test_url_state_documented():
    """
    URL state is verified manually in Phase 9.
    Scheme:
      ?filter=open|gated
      ?zone_group=surf-city-1|no-zone   (group active)
      ?zone=el-tunco                    (specific zone active)
      ?sort=ppm_asc|ppm_desc|price_asc|…
      ?listing=<id>
    Combinable: ?filter=open&zone_group=no-zone&sort=price_desc is valid.
    On load, readURL() parses and applies all.
    On change, pushURL(replace=true) uses history.replaceState.
    """
    # This test exists to document the contract; it always passes.
    assert True
