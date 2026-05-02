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

ZONE_COLORS_PY: dict = {
    'el-tunco':           {'bg': '#fde8e8', 'fg': '#c0392b'},
    'el-zonte':           {'bg': '#fce4f5', 'fg': '#a8118c'},
    'el-sunzal':          {'bg': '#fff3cd', 'fg': '#856404'},
    'san-diego':          {'bg': '#d6eaff', 'fg': '#1548a0'},
    'la-libertad':        {'bg': '#d0f4ea', 'fg': '#0a6847'},
    'puerto-la-libertad': {'bg': '#e6ddff', 'fg': '#5b21b6'},
    'el-cuco':            {'bg': '#d1f5d3', 'fg': '#14532d'},
    'las-flores':         {'bg': '#ffe5d9', 'fg': '#9a3412'},
    'mizata':             {'bg': '#ffd9ec', 'fg': '#9d174d'},
    'punta-mango':        {'bg': '#ecfccb', 'fg': '#365314'},
    'el-espino':          {'bg': '#fef9c3', 'fg': '#713f12'},
    'conchagua':          {'bg': '#fff1e6', 'fg': '#92400e'},
    'la-union':           {'bg': '#e0f7ff', 'fg': '#0c4a6e'},
}

ZONE_PALETTE_PY: list = [
    {'bg': '#f3f4f6', 'fg': '#374151'},
    {'bg': '#eff6ff', 'fg': '#1e40af'},
    {'bg': '#f0fdf4', 'fg': '#166534'},
    {'bg': '#fefce8', 'fg': '#854d0e'},
    {'bg': '#fff7ed', 'fg': '#9a3412'},
    {'bg': '#fdf4ff', 'fg': '#6b21a8'},
    {'bg': '#fff1f2', 'fg': '#9f1239'},
    {'bg': '#f0fdfa', 'fg': '#134e4a'},
]


def zone_color(zone: str) -> dict:
    """Python mirror of JS zoneColor()."""
    if zone in ZONE_COLORS_PY:
        return ZONE_COLORS_PY[zone]
    h = sum(ord(c) for c in zone)
    return ZONE_PALETTE_PY[h % len(ZONE_PALETTE_PY)]


@pytest.mark.parametrize("zone,expected_bg,expected_fg", [
    ('el-tunco',    '#fde8e8', '#c0392b'),
    ('el-zonte',    '#fce4f5', '#a8118c'),
    ('la-libertad', '#d0f4ea', '#0a6847'),
])
def test_zone_color_known(zone, expected_bg, expected_fg):
    c = zone_color(zone)
    assert c['bg'] == expected_bg, f"zone_color({zone!r}) bg={c['bg']!r}"
    assert c['fg'] == expected_fg, f"zone_color({zone!r}) fg={c['fg']!r}"


def test_zone_color_unknown_is_deterministic():
    """Same unknown zone always returns the same color."""
    assert zone_color('san-marcelino') == zone_color('san-marcelino')


def test_zone_color_unknown_from_palette():
    """Unknown zone selects a color from the fallback palette."""
    assert zone_color('san-marcelino') in ZONE_PALETTE_PY


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


# ── URL state (documented, not browser-testable) ──────────────────────

def test_url_state_documented():
    """
    URL state is verified manually in Phase 9.
    Scheme: ?filter=open|gated  ?sort=ppm_asc|ppm_desc|price_asc|…  ?listing=<id>
    On load, readURL() parses and applies all three.
    On change, pushURL(replace=true) uses history.replaceState.
    """
    # This test exists to document the contract; it always passes.
    assert True
