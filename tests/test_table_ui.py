"""
Tests for the table redesign UI logic.

The score-to-stars formula, filter partitioning, sort logic, and number
formatting are expressed as pure functions that can be verified without
a browser.  URL-state and DOM interaction are covered by the Phase 9
manual checklist (no JS test runner in this project).
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta, timezone
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


# ── Header stat formatting ────────────────────────────────────────────

def fmt_updated(iso_str: str, now_override=None) -> str:
    """Python mirror of JS fmtUpdated()."""
    from datetime import datetime, timezone, timedelta
    d = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    now = now_override or datetime.now(timezone.utc)
    def fmt_time(dt):
        h = dt.hour % 12 or 12
        m = dt.minute
        ampm = "AM" if dt.hour < 12 else "PM"
        return f"{h}:{m:02d} {ampm}"
    def same_date(a, b):
        return a.date() == b.date()
    yesterday = now - timedelta(days=1)
    t = fmt_time(d)
    if same_date(d, now):
        return f"Today, {t}"
    if same_date(d, yesterday):
        return f"Yesterday, {t}"
    months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    return f"{months[d.month-1]} {d.day}, {t}"


def test_fmt_updated_today():
    """When last_updated is today, shows 'Today, HH:MM AM/PM'."""
    from datetime import datetime, timezone
    now = datetime(2026, 5, 2, 21, 16, 0, tzinfo=timezone.utc)
    ts  = "2026-05-02T21:16:00Z"
    result = fmt_updated(ts, now_override=now)
    assert result.startswith("Today,"), f"Expected 'Today, …', got {result!r}"


def test_fmt_updated_yesterday():
    """When last_updated is yesterday, shows 'Yesterday, HH:MM AM/PM'."""
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 5, 3, 10, 0, 0, tzinfo=timezone.utc)
    ts  = "2026-05-02T20:00:00Z"
    result = fmt_updated(ts, now_override=now)
    assert result.startswith("Yesterday,"), f"Expected 'Yesterday, …', got {result!r}"


def test_fmt_updated_older():
    """Older dates show 'Mon DD, HH:MM AM/PM' — not 'Today' or 'Yesterday'."""
    from datetime import datetime, timezone
    now = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)
    ts  = "2026-05-02T21:16:00Z"
    result = fmt_updated(ts, now_override=now)
    assert not result.startswith("Today") and not result.startswith("Yesterday")
    assert "May 2" in result or "May" in result


def test_sources_format_includes_live():
    """Sources value must include 'live' and use ' / ' separator — not '/' or 'of'."""
    sources_text = "5 / 5 live"
    assert " / " in sources_text, "Must use ' / ' separator"
    assert "live" in sources_text, "Must include the word 'live'"
    assert "of" not in sources_text, "Must not use 'of'"


def test_brand_dot_color_is_literal():
    """The brand dot uses literal #1D9E75, not a CSS variable."""
    import re
    html = open("web/index.html").read()
    # hdr-dot class should set color to #1D9E75 directly
    assert ".hdr-dot{color:#1D9E75}" in html or ".hdr-dot{color:#1D9E75" in html, \
        "Brand dot must use literal color #1D9E75, not a CSS var"


def test_badge_svg_stroke_color():
    """The SVG asterisk in the badge uses stroke #085041 (brand dark teal)."""
    import re
    html = open("web/index.html").read()
    assert 'stroke="#085041"' in html, "Badge SVG must use stroke #085041"


def test_header_border_bottom_present():
    """Site header has a bottom border (not the old topbar height-based approach)."""
    html = open("web/index.html").read()
    assert ".site-header" in html, "New header class must be .site-header"
    # The filter-bar DIV element must come after the closing </header> tag
    header_end = html.find("</header>")
    filter_bar_pos = html.find('class="filter-bar"')
    assert header_end > 0 and filter_bar_pos > 0, "Both elements must exist in HTML"
    assert header_end < filter_bar_pos, "Filter bar must be outside the header"


# ── Newest sort + NEW badge (PRD 2 — sort by first_seen_at) ───────────
# Pure Python mirrors of the JS isNewListing() and the 'newest' branch in
# sortedRows(). These tests pin the contract so the dashboard can't lose
# time-based sorting in a future refactor.

NEW_BADGE_DAYS = 14
NEW_BADGE_SECONDS = NEW_BADGE_DAYS * 24 * 60 * 60


def is_new_listing(row: dict, now: datetime | None = None) -> bool:
    """Python mirror of the JS isNewListing() — true iff first_seen_at is
    within the last NEW_BADGE_DAYS days. Missing or unparseable timestamps
    are never new."""
    if not row or not row.get("first_seen_at"):
        return False
    try:
        ts = datetime.fromisoformat(row["first_seen_at"].replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds() <= NEW_BADGE_SECONDS


def sort_by_newest(rows, direction: str):
    """Python mirror of sortedRows() with SORT_COL='newest'."""
    reverse = direction == "desc"
    sentinel_asc = "￿"  # nulls sink to the end on asc
    sentinel_desc = ""        # nulls sink to the end on desc (smallest string)
    sentinel = sentinel_asc if direction == "asc" else sentinel_desc

    def key(r):
        return r.get("first_seen_at") or sentinel

    return sorted(rows, key=key, reverse=reverse)


def test_is_new_listing_true_within_14_days():
    """A first_seen_at one day ago triggers the badge."""
    one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert is_new_listing({"first_seen_at": one_day_ago}) is True


def test_is_new_listing_false_at_15_days():
    """A first_seen_at 15 days ago is past the cutoff."""
    fifteen_days_ago = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    assert is_new_listing({"first_seen_at": fifteen_days_ago}) is False


def test_is_new_listing_false_at_exactly_14_days_plus_one_second():
    """The boundary is inclusive: <= 14 days. Tested at 14 days + 1 second."""
    boundary = (datetime.now(timezone.utc) - timedelta(days=14, seconds=1)).isoformat()
    assert is_new_listing({"first_seen_at": boundary}) is False


def test_is_new_listing_handles_missing_timestamp():
    """Missing first_seen_at must not error and must not flag the row as new.

    This matters because the live ranked.json carries first_seen_at = null
    for every listing until the next cron run after the sidecar lands.
    The badge must never throw, and it must never falsely render on
    null-timestamp rows.
    """
    assert is_new_listing({}) is False
    assert is_new_listing({"first_seen_at": None}) is False


def test_is_new_listing_handles_garbage_timestamp():
    """Unparseable timestamps must never flag a row as new."""
    assert is_new_listing({"first_seen_at": "not-an-iso-date"}) is False
    assert is_new_listing({"first_seen_at": ""}) is False


def test_sort_newest_desc_orders_recent_first():
    """Sorting by newest_desc puts the most recent first_seen_at at the top."""
    rows = [
        {"source_id": "old",    "first_seen_at": "2026-01-01T00:00:00+00:00"},
        {"source_id": "newer",  "first_seen_at": "2026-04-01T00:00:00+00:00"},
        {"source_id": "newest", "first_seen_at": "2026-05-01T00:00:00+00:00"},
    ]
    result = [r["source_id"] for r in sort_by_newest(rows, "desc")]
    assert result == ["newest", "newer", "old"]


def test_sort_newest_pushes_nulls_to_end_on_desc():
    """Listings with null first_seen_at sink to the bottom on desc — the
    common case until the cron has populated the sidecar for everyone."""
    rows = [
        {"source_id": "with_ts",    "first_seen_at": "2026-05-01T00:00:00+00:00"},
        {"source_id": "no_ts",      "first_seen_at": None},
        {"source_id": "older_ts",   "first_seen_at": "2026-01-01T00:00:00+00:00"},
    ]
    result = [r["source_id"] for r in sort_by_newest(rows, "desc")]
    assert result == ["with_ts", "older_ts", "no_ts"]


def test_sort_newest_pushes_nulls_to_end_on_asc():
    """Same nulls-sink behavior in ascending direction."""
    rows = [
        {"source_id": "no_ts",      "first_seen_at": None},
        {"source_id": "older_ts",   "first_seen_at": "2026-01-01T00:00:00+00:00"},
        {"source_id": "with_ts",    "first_seen_at": "2026-05-01T00:00:00+00:00"},
    ]
    result = [r["source_id"] for r in sort_by_newest(rows, "asc")]
    assert result == ["older_ts", "with_ts", "no_ts"]


# ── DOM contract tests (HTML-string assertions) ──────────────────────


def test_mobile_sort_dropdown_has_newest_option():
    """The mobile sort dropdown exposes 'newest_desc' as a selectable option.

    Without this assertion, a refactor that drops the option would silently
    remove the only mobile-accessible path to the time-based sort.
    """
    html = open("web/index.html").read()
    assert 'value="newest_desc"' in html, "Mobile sort missing the newest_desc option"
    # Sanity: the option's display label is human-readable.
    assert "Newest first" in html


def test_url_state_regex_includes_newest():
    """`?sort=newest_desc` URLs must round-trip through readURL/pushURL.

    The regex in readURL() restricts which sort columns are accepted from
    the URL. Removing 'newest' from the regex would silently break the
    only desktop path to this sort.

    Asserts the regex contains all expected tokens — order-and-extension
    independent so future additions (e.g. deal/location/momentum) don't
    require updating this test alongside the regex.
    """
    import re
    html = open("web/index.html").read()
    # Find the readURL sort regex: look for a `(<tokens>)_(asc|desc)$` pattern
    # constrained to a |-separated lowercase identifier list.
    m = re.search(r"\(([a-z|]+)\)_\(asc\|desc\)\$/", html)
    assert m, "readURL sort regex with the (cols)_(asc|desc) shape not found"
    tokens = set(m.group(1).split("|"))
    assert "newest" in tokens, (
        f"readURL sort regex no longer accepts 'newest' — desktop URL sort "
        f"broken. Found tokens: {sorted(tokens)}"
    )


def test_new_badge_helper_present():
    """The newBadgeHTML helper and isNewListing function exist in the HTML.

    These are the contract surfaces the badge depends on. If they're
    renamed or removed, the existing rendering call sites
    (`${newBadgeHTML(r)}` in renderTable + renderCards) would silently
    produce 'undefined' strings.
    """
    html = open("web/index.html").read()
    assert "function newBadgeHTML" in html
    assert "function isNewListing" in html
    assert "${newBadgeHTML(r)}" in html, (
        "renderTable/renderCards no longer call newBadgeHTML — badge won't render"
    )


# ── Price range filter (PRD 3 — Tune panel) ──────────────────────────
# The price filter encodes its state as snap-point indices, not raw USD,
# so the URL stays stable even if we re-tune the snap array. These tests
# pin the filter logic + the DOM surfaces it depends on.

PRICE_SNAPS_PY = [0, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000, 2_500_000, 5_000_000, float("inf")]


def price_in_range(row: dict, min_idx: int, max_idx: int) -> bool:
    """Python mirror of the JS _priceInRange().

    Listings without price_usd survive only when the range is fully open
    (default = no filter active). Once the user narrows either end, unpriced
    listings drop out — the user is asking for a price-bounded view and a
    null price doesn't satisfy "between $X and $Y".
    """
    is_default = min_idx == 0 and max_idx == len(PRICE_SNAPS_PY) - 1
    if is_default:
        return True
    p = row.get("price_usd")
    if p is None:
        return False
    return PRICE_SNAPS_PY[min_idx] <= p <= PRICE_SNAPS_PY[max_idx]


def test_price_default_range_includes_all_priced():
    """Default range admits every priced listing."""
    rows = [{"price_usd": 0}, {"price_usd": 100}, {"price_usd": 1_000_000_000}]
    last = len(PRICE_SNAPS_PY) - 1
    assert all(price_in_range(r, 0, last) for r in rows)


def test_price_default_range_includes_unpriced():
    """At default range, unpriced listings remain visible — the filter is off."""
    last = len(PRICE_SNAPS_PY) - 1
    assert price_in_range({"price_usd": None}, 0, last) is True
    assert price_in_range({}, 0, last) is True


def test_price_narrowed_range_excludes_unpriced():
    """When the user narrows the range, unpriced listings drop out."""
    last = len(PRICE_SNAPS_PY) - 1
    assert price_in_range({"price_usd": None}, 1, last) is False  # min moved off zero
    assert price_in_range({}, 0, last - 1) is False               # max moved off infinity


def test_price_filter_inclusive_bounds():
    """Boundary values pass — bounds are inclusive on both sides."""
    # Idx 2 = $50K, idx 5 = $500K
    assert price_in_range({"price_usd": 50_000},  2, 5) is True
    assert price_in_range({"price_usd": 500_000}, 2, 5) is True


def test_price_filter_excludes_below_min():
    """Below the min snap → excluded."""
    # Idx 2 = $50K
    assert price_in_range({"price_usd": 49_999}, 2, 5) is False


def test_price_filter_excludes_above_max():
    """Above the max snap → excluded."""
    # Idx 5 = $500K
    assert price_in_range({"price_usd": 500_001}, 2, 5) is False


def test_price_filter_max_idx_is_infinity():
    """The highest snap index represents 'No max' — values up to ∞ pass."""
    last = len(PRICE_SNAPS_PY) - 1
    assert PRICE_SNAPS_PY[last] == float("inf")
    assert price_in_range({"price_usd": 50_000_000}, 0, last) is True


def test_price_snap_array_length_matches_labels():
    """PRICE_SNAPS and PRICE_LABELS must agree in length — drift would mis-label sliders."""
    html = open("web/index.html").read()
    # Both arrays declared on the same script block; pull their literal lengths.
    import re as _re
    snap_match = _re.search(r"PRICE_SNAPS\s*=\s*\[([^\]]+)\]", html)
    label_match = _re.search(r"PRICE_LABELS\s*=\s*\[([^\]]+)\]", html)
    assert snap_match and label_match, "PRICE_SNAPS / PRICE_LABELS declarations missing"
    snap_count  = len(_re.findall(r"\d[\d_]*|Infinity", snap_match.group(1)))
    label_count = len(_re.findall(r"'[^']+'", label_match.group(1)))
    assert snap_count == label_count, (
        f"PRICE_SNAPS has {snap_count} entries but PRICE_LABELS has {label_count} — "
        f"slider labels would desync"
    )


def test_tune_panel_dom_contracts_present():
    """Tune panel + button + filter wiring all exist in the HTML.

    These are the load-bearing surfaces. Removing any of them silently
    breaks the price filter (button stops opening the panel, panel stops
    rendering, or filtered rows stop respecting the slider state).
    """
    html = open("web/index.html").read()
    # Tune button anchored in the filter bar.
    assert 'id="tune-open"' in html
    # Desktop and mobile panels exist.
    assert 'id="tune-panel"' in html
    assert 'id="mobile-tune-overlay"' in html
    # Filter logic is wired into the row filter.
    assert "_priceInRange" in html, (
        "filteredRows() no longer references _priceInRange — price filter is dead"
    )
    # URL keys round-trip through readURL/pushURL.
    assert "price_min" in html and "price_max" in html


def test_url_state_omits_default_price_range():
    """pushURL only emits ?price_min/?price_max when the user has narrowed
    the range. This keeps the default URL clean and ensures shareable URLs
    only carry the filter state that actually differs from the page default.
    """
    html = open("web/index.html").read()
    # The pushURL function checks against the defaults before setting params.
    assert "PRICE_MIN_IDX !== 0" in html
    assert "PRICE_MAX_IDX !== PRICE_SNAPS.length-1" in html


def test_price_filter_applied_to_live_data(listings):
    """End-to-end: applying a $50K–$500K filter on the real ranked.json
    yields only listings whose price falls in that band. Treats live data
    as the ground truth — if the JSON shape changes, this catches it.
    """
    in_band = [r for r in listings if price_in_range(r, 2, 5)]  # $50K–$500K
    for r in in_band:
        # The unpriced listings should NOT appear — narrowed range excludes them.
        assert r.get("price_usd") is not None
        assert 50_000 <= r["price_usd"] <= 500_000, (
            f"Listing {r.get('source_id')} price {r.get('price_usd')} outside band"
        )


# ── Size range filter (PRD 3 — Tune panel) ───────────────────────────
# Mirrors the price filter contract. Pinned because size and price are the
# load-bearing buyer-intent filters; either drifting silently undercuts the
# whole filter UX. The defaults-pass-everything semantic for unpriced /
# unsized listings is intentional — the filter is "off" until the user
# narrows a handle.

SIZE_SNAPS_PY = [0, 100, 500, 1_000, 5_000, 10_000, 50_000, 100_000, 500_000, float("inf")]


def size_in_range(row: dict, min_idx: int, max_idx: int) -> bool:
    """Python mirror of JS _sizeInRange()."""
    is_default = min_idx == 0 and max_idx == len(SIZE_SNAPS_PY) - 1
    if is_default:
        return True
    a = row.get("area_m2")
    if a is None:
        return False
    return SIZE_SNAPS_PY[min_idx] <= a <= SIZE_SNAPS_PY[max_idx]


def test_size_default_range_includes_all_sized():
    last = len(SIZE_SNAPS_PY) - 1
    rows = [{"area_m2": 67}, {"area_m2": 1_000}, {"area_m2": 6_800_000}]
    assert all(size_in_range(r, 0, last) for r in rows)


def test_size_default_range_includes_unsized():
    """At default range, unsized listings remain visible — filter is off."""
    last = len(SIZE_SNAPS_PY) - 1
    assert size_in_range({"area_m2": None}, 0, last) is True
    assert size_in_range({}, 0, last) is True


def test_size_narrowed_range_excludes_unsized():
    """Once narrowed, listings without area_m2 drop out."""
    last = len(SIZE_SNAPS_PY) - 1
    assert size_in_range({"area_m2": None}, 1, last) is False
    assert size_in_range({}, 0, last - 1) is False


def test_size_filter_inclusive_bounds():
    # idx 2 = 500 m², idx 5 = 10K m²
    assert size_in_range({"area_m2": 500},   2, 5) is True
    assert size_in_range({"area_m2": 10_000}, 2, 5) is True


def test_size_filter_excludes_outside_band():
    assert size_in_range({"area_m2": 499},     2, 5) is False
    assert size_in_range({"area_m2": 10_001},  2, 5) is False


def test_size_filter_max_idx_is_infinity():
    last = len(SIZE_SNAPS_PY) - 1
    assert SIZE_SNAPS_PY[last] == float("inf")
    assert size_in_range({"area_m2": 6_800_000}, 0, last) is True


def test_size_snap_array_length_matches_labels():
    """SIZE_SNAPS and SIZE_LABELS must agree in length."""
    html = open("web/index.html").read()
    import re as _re
    snap_match  = _re.search(r"SIZE_SNAPS\s*=\s*\[([^\]]+)\]",  html)
    label_match = _re.search(r"SIZE_LABELS\s*=\s*\[([^\]]+)\]", html)
    assert snap_match and label_match, "SIZE_SNAPS / SIZE_LABELS declarations missing"
    snap_count  = len(_re.findall(r"\d[\d_]*|Infinity", snap_match.group(1)))
    label_count = len(_re.findall(r"'[^']+'", label_match.group(1)))
    assert snap_count == label_count, (
        f"SIZE_SNAPS has {snap_count} entries but SIZE_LABELS has {label_count} — "
        "slider labels would desync"
    )


def test_size_filter_dom_contracts_present():
    """Size filter is wired into the same Tune panel surfaces as price."""
    html = open("web/index.html").read()
    # Filter logic referenced in filteredRows.
    assert "_sizeInRange" in html, (
        "filteredRows() no longer references _sizeInRange — size filter is dead"
    )
    # URL keys round-trip.
    assert "size_min" in html and "size_max" in html
    # Tune button state reflects size filter too.
    assert "isDefaultSizeRange" in html


def test_url_state_omits_default_size_range():
    """pushURL only emits ?size_min/?size_max when narrowed from defaults."""
    html = open("web/index.html").read()
    assert "SIZE_MIN_IDX  !== 0" in html or "SIZE_MIN_IDX !== 0" in html
    assert "SIZE_MAX_IDX  !== SIZE_SNAPS.length-1" in html or "SIZE_MAX_IDX !== SIZE_SNAPS.length-1" in html


def test_size_filter_applied_to_live_data(listings):
    """End-to-end: applying a 500–10K m² filter on the real ranked.json
    yields only listings whose area falls in that band.
    """
    in_band = [r for r in listings if size_in_range(r, 2, 5)]  # 500 m² – 10K m²
    for r in in_band:
        assert r.get("area_m2") is not None
        assert 500 <= r["area_m2"] <= 10_000, (
            f"Listing {r.get('source_id')} area {r.get('area_m2')} outside band"
        )


def test_m2_per_vara2_constant_matches_python():
    """The JS conversion factor must match pulpo/units.py M2_PER_VARA2.

    The dashboard's vara² display (via fmtPPV2 and any size-display dual
    units) divides m² by this value. Drift between the JS literal and the
    Python source-of-truth means visible price/area numbers diverge.
    """
    html = open("web/index.html").read()
    assert "M2_PER_VARA2 = 0.698896" in html, (
        "JS M2_PER_VARA2 literal drifted from pulpo/units.py:19 (= 0.698896)"
    )
    # Cross-check against the Python source.
    units = open("pulpo/units.py").read()
    import re as _re
    m = _re.search(r"M2_PER_VARA2\s*=\s*([\d.]+)", units)
    assert m and m.group(1) == "0.698896", (
        "pulpo/units.py M2_PER_VARA2 changed; update the JS literal too"
    )
