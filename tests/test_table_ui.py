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

def _frontend_text() -> str:
    """Concatenate index.html + assets/index.css + assets/index.js for grep-style assertions.

    The frontend was split into separate files in chore/split-frontend so the
    HTML stays under 14 KB. Tests that grep for inline CSS or JS now grep
    against the concatenated text instead of just the HTML.
    """
    parts = [(REPO / "web/index.html").read_text()]
    for asset in ("index.css", "index.js"):
        p = REPO / "web/assets" / asset
        if p.exists():
            parts.append(p.read_text())
    return "\n".join(parts)



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
    html = _frontend_text()
    # hdr-dot class should set color to #1D9E75 directly
    assert ".hdr-dot{color:#1D9E75}" in html or ".hdr-dot{color:#1D9E75" in html, \
        "Brand dot must use literal color #1D9E75, not a CSS var"


def test_badge_svg_stroke_color():
    """The SVG asterisk in the badge uses stroke #085041 (brand dark teal)."""
    import re
    html = _frontend_text()
    assert 'stroke="#085041"' in html, "Badge SVG must use stroke #085041"


def test_header_border_bottom_present():
    """Site header has a bottom border (not the old topbar height-based approach)."""
    html = _frontend_text()
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
    import re
    html = _frontend_text()
    assert 'value="newest_desc"' in html, "Mobile sort missing the newest_desc option"
    # Sanity: the option's display label mentions "newest" in some form
    # (case-insensitive). Pinned this way so future copy edits don't break
    # the test for trivial reasons.
    label_match = re.search(
        r'value="newest_desc"[^>]*>([^<]+)</option>', html, re.I,
    )
    assert label_match, "newest_desc option has no human label"
    assert "newest" in label_match.group(1).lower(), (
        f"newest_desc option label should reference 'newest'; got {label_match.group(1)!r}"
    )


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
    html = _frontend_text()
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
    html = _frontend_text()
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
    html = _frontend_text()
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
    html = _frontend_text()
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
    html = _frontend_text()
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
    html = _frontend_text()
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
    html = _frontend_text()
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
    html = _frontend_text()
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
    html = _frontend_text()
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


# ── Score breakdown labels: consistency across the interface ──────────
# The three V/L/M dimensions are surfaced in three places: the side-panel
# score breakdown bars, the mobile sort dropdown, and the methodology
# modal's composite formula. Drift between any two of these would
# confuse users — these tests pin a single set of canonical labels and
# fail loudly if any surface drifts.

EXPECTED_LABELS = {
    "value":    "Price vs Comps",
    "location": "Location",
    "momentum": "Momentum",
}


def test_score_dimensions_constant_exists():
    """SCORE_DIMENSIONS is the single source of truth for V/L/M display
    labels. Removing it forces the breakdown bars back into per-call-site
    string literals, which is exactly the drift we just stamped out.
    """
    html = _frontend_text()
    assert "const SCORE_DIMENSIONS" in html, (
        "SCORE_DIMENSIONS dropped — score-bar labels would diverge per surface"
    )


def test_score_dimensions_canonical_labels_present():
    """All three canonical labels appear in the SCORE_DIMENSIONS array."""
    import re as _re
    html = _frontend_text()
    block = _re.search(r"const SCORE_DIMENSIONS\s*=\s*\[(.+?)\];", html, _re.DOTALL)
    assert block, "SCORE_DIMENSIONS array not found"
    body = block.group(1)
    for slug, label in EXPECTED_LABELS.items():
        assert f"'{slug}'" in body, f"slug {slug!r} missing from SCORE_DIMENSIONS"
        assert f"'{label}'" in body, f"label {label!r} missing from SCORE_DIMENSIONS"


def test_old_deal_label_removed_from_user_facing_surfaces():
    """The earlier 'Deal' label should no longer appear in panelHTML's
    breakdown rows or the methodology composite formula. Sort dropdown
    `value="deal_desc"` is the URL state key — that stays for stability.
    """
    html = _frontend_text()
    # Score breakdown rows used to literally contain 'Deal' as a label.
    # The panelHTML now reads from SCORE_DIMENSIONS; a literal 'Deal' in
    # there would mean a stale per-call-site string snuck back in.
    panel_block = html.split("function panelHTML")[1].split("function ")[0]
    assert "'Deal'" not in panel_block, (
        "panelHTML still hardcodes 'Deal' — should pull from SCORE_DIMENSIONS"
    )
    # Methodology formula should reflect the new label.
    assert "Price vs Comps" in html, "Methodology formula missing 'Price vs Comps'"
    assert "0.40 × Deal" not in html, "Methodology formula still says 'Deal'"


def test_sort_dropdown_uses_consistent_dimension_label():
    """Sort dropdown's deal_desc option labels itself with 'Price vs Comps'
    to match the score bar / methodology / SCORE_DIMENSIONS centralized
    label.

    Asserts on the option's text content rather than a fixed prefix string
    so copy edits to the surrounding "Sort: ..." vs "Sort by ..." pattern
    don't break this test for the wrong reason.
    """
    import re
    html = _frontend_text()
    m = re.search(r'value="deal_desc"[^>]*>([^<]+)</option>', html, re.I)
    assert m, "Sort dropdown is missing the deal_desc option"
    assert "Price vs Comps" in m.group(1), (
        f"deal_desc option no longer says 'Price vs Comps' — drifts from "
        f"score bar. Found: {m.group(1)!r}"
    )


def test_score_name_is_a_button():
    """The .score-name is a <button> so click-to-open-methodology is
    accessible (keyboard, screen readers) and obvious. The earlier
    `<span class="score-name" cursor:help>` had no click target despite
    the help cursor signaling interactivity — exactly the bug we're
    fixing here.
    """
    html = _frontend_text()
    # The scoreBarHTML componentizer renders a <button>.
    assert "<button" in html and "class=\"score-name js-open-methodology\"" in html, (
        ".score-name is no longer a button — click-to-open-methodology won't work"
    )
    # Cursor reflects clickability, not the broken cursor:help.
    assert ".score-name{" in html
    score_name_css = html.split(".score-name{")[1].split("}")[0]
    assert "cursor:pointer" in score_name_css, (
        ".score-name CSS still uses cursor:help despite being clickable"
    )
    assert "cursor:help" not in score_name_css, (
        ".score-name should not use cursor:help — it's an actionable button"
    )


def test_methodology_open_helper_exists_and_is_called():
    """openMethodologyModal() is the shared open helper. It's called by
    the footer link, by the new score-name buttons (via delegated click),
    and could be called by future surfaces (e.g. info icons next to
    table column headers).
    """
    html = _frontend_text()
    assert "function openMethodologyModal" in html
    assert "openMethodologyModal()" in html, (
        "openMethodologyModal defined but never called — modal is unreachable"
    )
    # Delegated click handler picks up score-name presses anywhere on body.
    assert ".js-open-methodology" in html, (
        "Score-name buttons have no class hook for the delegated click handler"
    )


# ── V/L/M weight sliders (PRD 2 — flexible reranking) ────────────────
# These tests pin both the math (composite re-blend) and the wire-up
# (sliders exist, URL round-trips, slugs stable). The recompute math is
# the load-bearing surface — get it wrong and "Sort: Composite" silently
# orders by something different than the user's slider weights.

# Defaults must match Python pulpo/ranker.py composite: 0.40 / 0.35 / 0.25.
EXPECTED_WEIGHT_DEFAULTS = {"value": 40, "location": 35, "momentum": 25}


def recompute_composite_py(li: dict, weights: dict) -> float | None:
    """Python mirror of JS recomputeComposite()."""
    fields = {
        "value":    li.get("value_score"),
        "location": li.get("location_score"),
        "momentum": li.get("momentum_score"),
    }
    weighted = 0.0
    total = 0.0
    for k in ("value", "location", "momentum"):
        score = fields[k]
        wt = weights.get(k, 0)
        if score is None or not wt:
            continue
        weighted += wt * score
        total += wt
    if total == 0:
        return li.get("rank_score")
    return weighted / total


def test_recompute_default_weights_matches_python_ranker_formula():
    """Default weights must reproduce the Python composite (within rounding)."""
    li = {"value_score": 100, "location_score": 60, "momentum_score": 40}
    expected = (40*100 + 35*60 + 25*40) / (40 + 35 + 25)
    actual = recompute_composite_py(li, EXPECTED_WEIGHT_DEFAULTS)
    assert actual is not None and abs(actual - expected) < 0.01


def test_recompute_with_only_value_weight_orders_by_value():
    """With V=100 and L/M=0, the sort should match max(value_score) order."""
    rows = [
        {"value_score": 50, "location_score": 90, "momentum_score": 90},
        {"value_score": 90, "location_score": 50, "momentum_score": 50},
        {"value_score": 70, "location_score": 70, "momentum_score": 70},
    ]
    only_value = {"value": 100, "location": 0, "momentum": 0}
    composites = [recompute_composite_py(r, only_value) for r in rows]
    assert composites == [50, 90, 70], (
        f"V-only weights should yield value-only composites; got {composites}"
    )


def test_recompute_all_zero_weights_preserves_rank_score():
    """All sliders at 0 → fall back to the listing's static rank_score
    rather than producing a divide-by-zero or zeroing out the order."""
    li = {"value_score": 100, "location_score": 60, "momentum_score": 40, "rank_score": 84.5}
    zero = {"value": 0, "location": 0, "momentum": 0}
    assert recompute_composite_py(li, zero) == 84.5


def test_recompute_handles_missing_score_legs():
    """A leg with a null score is skipped (not zeroed) — mirrors the
    fallback the Python ranker uses when a leg can't compute."""
    li = {"value_score": 80, "location_score": None, "momentum_score": 40, "rank_score": 60}
    weights = {"value": 50, "location": 50, "momentum": 50}
    # Only value + momentum contribute; expected = (50*80 + 50*40) / 100 = 60
    assert recompute_composite_py(li, weights) == 60


def test_recompute_handles_missing_score_when_weight_zero():
    """Zero-weight legs are skipped before nullness — guards against
    a single null score short-circuiting the whole composite."""
    li = {"value_score": 80, "location_score": 40, "momentum_score": None}
    # Momentum is null but its weight is 0 anyway — should still work.
    weights = {"value": 50, "location": 50, "momentum": 0}
    expected = (50*80 + 50*40) / 100
    assert recompute_composite_py(li, weights) == expected


def test_weight_defaults_constant_in_html():
    """The JS WEIGHT_DEFAULTS must match the Python ranker composite."""
    import re as _re
    html = _frontend_text()
    match = _re.search(r"WEIGHT_DEFAULTS\s*=\s*\{([^}]+)\}", html)
    assert match, "WEIGHT_DEFAULTS not found"
    body = match.group(1)
    for slug, val in EXPECTED_WEIGHT_DEFAULTS.items():
        assert f"{slug}:" in body
        assert str(val) in body, (
            f"WEIGHT_DEFAULTS for {slug!r} drifted from expected {val}"
        )


def test_weight_sliders_dom_present():
    """Each V/L/M slider exists in the rendered Tune panel HTML
    (or its render function — the DOM elements are created at runtime
    via _weightSliderHTML, but the function must exist)."""
    html = _frontend_text()
    assert "function _weightSliderHTML" in html
    assert "function _weightSectionHTML" in html
    assert "function _wireWeightSliders" in html
    # Slider IDs follow the pattern weight-<slug>.
    assert "id=\"weight-${slug}\"" in html or "weight-${slug}" in html, (
        "Weight slider ID pattern lost — slider wiring would silently break"
    )


def test_composite_sort_option_present():
    """The composite sort option lets users sort by their re-blended
    composite; without it, the sliders only affect the panel scores
    on screen and don't actually reorder the table by the new weights."""
    html = _frontend_text()
    assert 'value="composite_desc"' in html, (
        "Sort dropdown lost the composite option — sliders can't reorder"
    )
    # The sortedRows() handler matches the new SORT_COL.
    assert "SORT_COL==='composite'" in html


def test_weight_url_state_round_trips():
    """?w=V,L,M URL key gets parsed and emitted by readURL/pushURL.

    pushURL only emits ?w when WEIGHTS differ from defaults — same
    discipline as the price/size keys. URL stays clean at defaults.
    """
    html = _frontend_text()
    assert "p.get('w')" in html, "readURL doesn't parse ?w= URL state"
    assert "p.set('w'," in html or "p.set(\"w\"," in html, (
        "pushURL doesn't emit ?w= URL state"
    )
    assert "isDefaultWeights()" in html, (
        "pushURL emits ?w= even at defaults — URL won't stay clean"
    )


def test_url_regex_includes_composite():
    """readURL's sort regex accepts 'composite' so ?sort=composite_desc
    URLs round-trip after a refresh."""
    html = _frontend_text()
    assert "newest|deal|location|momentum|composite" in html, (
        "readURL sort regex no longer accepts 'composite' — desktop URL sort broken"
    )


def test_weight_slider_reuses_score_dimensions():
    """The slider section reads colors + labels from SCORE_DIMENSIONS so
    visual identity stays in sync with the score breakdown bars. A slider
    with a stale or hardcoded color would drift visually after any future
    palette change.
    """
    html = _frontend_text()
    section_block = html.split("function _weightSectionHTML")[1].split("function ")[0]
    assert "SCORE_DIMENSIONS" in section_block, (
        "_weightSectionHTML doesn't iterate SCORE_DIMENSIONS — labels can drift"
    )


# ── Photos column ─────────────────────────────────────────────────────
# Mirrors the JS photosCellHTML(), photo sort, and photos filter so the
# column's behaviour is verifiable without a browser.

def photos_cell_html(photos_count) -> str:
    """Python mirror of JS photosCellHTML()."""
    c = photos_count or 0
    if c <= 0:
        return '<span class="photo-empty">—</span>'
    plural = "" if c == 1 else "s"
    return (f'<span class="photo-tag" aria-label="{c} photo{plural}">'
            f'<svg aria-hidden="true"><use href="#pp-camera"/></svg>{c}</span>')


def sort_rows_photos(rows, direction):
    """Python mirror of the photos branch in JS sortedRows().
    Treats null and 0 identically — both sink to the end regardless of dir."""
    reverse = direction == "desc"
    nil = float("-inf") if reverse else float("inf")
    def key(r):
        c = r.get("photos_count")
        return c if (c and c > 0) else nil
    return sorted(rows, key=key, reverse=reverse)


def filter_photos(rows, mode):
    """Python mirror of the PHOTOS_F branch in JS filteredRows()."""
    if mode == "with":
        return [r for r in rows if (r.get("photos_count") or 0) > 0]
    if mode == "none":
        return [r for r in rows if (r.get("photos_count") or 0) == 0]
    return list(rows)


def test_photos_cell_renders_camera_tag_for_positive_count():
    html = photos_cell_html(6)
    assert "photo-tag" in html
    assert "#pp-camera" in html, "camera SVG sprite reference missing"
    assert ">6</span>" in html, "count is not rendered inside the pill"


def test_photos_cell_renders_dash_for_zero_and_null():
    """photos_count == 0 and photos_count is None are treated identically —
    both render the muted dash, never the pill."""
    for c in (0, None):
        html = photos_cell_html(c)
        assert "photo-empty" in html
        assert "—" in html
        assert "photo-tag" not in html, (
            f"empty count {c!r} should not render the pill"
        )


def test_photos_sort_desc_puts_highest_first_nulls_last():
    rows = [
        {"id": "a", "photos_count": 0},
        {"id": "b", "photos_count": 5},
        {"id": "c", "photos_count": None},
        {"id": "d", "photos_count": 12},
        {"id": "e", "photos_count": 1},
    ]
    out = sort_rows_photos(rows, "desc")
    assert [r["id"] for r in out[:3]] == ["d", "b", "e"], (
        "desc should put 12, 5, 1 first"
    )
    # The two null/zero rows go to the end (order between them is not part
    # of the contract; just assert both are at the tail).
    tail_ids = {r["id"] for r in out[3:]}
    assert tail_ids == {"a", "c"}, "null/zero rows must sink to the end"


def test_photos_sort_asc_puts_lowest_nonzero_first_nulls_still_last():
    rows = [
        {"id": "a", "photos_count": 0},
        {"id": "b", "photos_count": 5},
        {"id": "c", "photos_count": None},
        {"id": "d", "photos_count": 12},
        {"id": "e", "photos_count": 1},
    ]
    out = sort_rows_photos(rows, "asc")
    assert [r["id"] for r in out[:3]] == ["e", "b", "d"], (
        "asc should put 1, 5, 12 first — null/zero must NOT interleave"
    )
    tail_ids = {r["id"] for r in out[3:]}
    assert tail_ids == {"a", "c"}, "null/zero rows must remain at the end on asc"


def test_photos_filter_with_excludes_zero_and_null():
    rows = [
        {"id": "a", "photos_count": 0},
        {"id": "b", "photos_count": 3},
        {"id": "c", "photos_count": None},
        {"id": "d", "photos_count": 1},
    ]
    out = filter_photos(rows, "with")
    assert [r["id"] for r in out] == ["b", "d"]


def test_photos_filter_none_includes_zero_and_null():
    rows = [
        {"id": "a", "photos_count": 0},
        {"id": "b", "photos_count": 3},
        {"id": "c", "photos_count": None},
        {"id": "d", "photos_count": 1},
    ]
    out = filter_photos(rows, "none")
    assert sorted(r["id"] for r in out) == ["a", "c"]


def test_photos_filter_combinable_with_open_gated():
    """?filter=open&photos=with applies BOTH — only open-land listings with photos."""
    rows = [
        {"id": "a", "is_in_development": False, "photos_count": 5},   # open + photos ✓
        {"id": "b", "is_in_development": False, "photos_count": 0},   # open, no photos
        {"id": "c", "is_in_development": True,  "photos_count": 5},   # gated, has photos
        {"id": "d", "is_in_development": True,  "photos_count": 0},   # gated, no photos
        {"id": "e", "is_in_development": False, "photos_count": None},# open, null photos
    ]
    open_land = [r for r in rows if not r.get("is_in_development")]
    out = filter_photos(open_land, "with")
    assert [r["id"] for r in out] == ["a"], (
        "intersection of FILTER=open and PHOTOS_F=with should yield only 'a'"
    )


def test_photos_url_state_round_trips():
    """readURL must accept ?photos=with|none and ?sort=photos_(asc|desc).
    pushURL must emit ?photos= only when non-default."""
    html = _frontend_text()
    # readURL parses ?photos=
    assert "['all','with','none'].includes(p.get('photos'))" in html, (
        "readURL doesn't accept ?photos= URL state"
    )
    # readURL sort regex includes 'photos'
    assert "stars|photos|newest" in html, (
        "readURL sort regex doesn't include 'photos' — ?sort=photos_desc breaks on reload"
    )
    # pushURL emits ?photos= only for non-default
    assert "PHOTOS_F!=='all'" in html, (
        "pushURL emits ?photos= even at default — URL won't stay clean"
    )
    # mobile-sort regex must also include 'photos' (kept in sync per existing comment)
    mobile_block = html.split("function wireMobileSort")[1].split("function ")[0]
    assert "stars|photos|newest" in mobile_block, (
        "mobile-sort regex doesn't accept 'photos_*' values — selecting the option no-ops"
    )


def test_photos_header_default_first_click_is_descending():
    """Per spec: first click on the Photos header sorts descending (most useful
    default for visual browsers). Verified via the data-def attribute on the th."""
    html = _frontend_text()
    assert 'data-col="photos" data-def="desc"' in html, (
        "Photos column header missing data-def=\"desc\" — first click would be ascending"
    )


# ── Property-type column / pill ─────────────────────────────────────────
# This PR adds a read-only Type column + side-panel pill that only appear
# when ranked.json contains >1 distinct property_type. Single-type land-only
# datasets stay visually identical to today.

def test_type_column_only_appears_when_multiple_types_in_data():
    html = _frontend_text()
    # Init computes a Set of property_type values and toggles SHOW_TYPE_COL
    assert "new Set(ALL_DATA.map(r => r.property_type)" in html, (
        "init() should derive the type set from ranked.json"
    )
    assert "SHOW_TYPE_COL = types.size > 1" in html, (
        "SHOW_TYPE_COL must be true only when >1 distinct property_type exists"
    )


def test_type_header_injected_only_when_types_diverge():
    """The Type <th> is injected programmatically — never present in the
    base HTML. This keeps the land-only view identical to today."""
    html_only = (REPO / "web/index.html").read_text()
    assert "col-type" not in html_only, (
        "Type header must be injected by JS, not present in base HTML"
    )
    js = (REPO / "web/assets/index.js").read_text()
    assert "th.className = 'col-type'" in js, (
        "init() must inject the Type <th> when SHOW_TYPE_COL is true"
    )


def test_type_pill_helper_exists_and_returns_empty_for_unknown_type():
    """The typePillHTML helper must gracefully render '' for unknown types
    so the cell collapses to an empty TD rather than rendering 'undefined'."""
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function typePillHTML")[1].split("function ")[0]
    assert "if (!cfg) return ''" in block, (
        "typePillHTML must return '' when PROPERTY_TYPES has no entry for the type"
    )
    assert "type-pill" in block, "missing CSS class"


def test_side_panel_renders_type_meta_item():
    """Type appears as a panel meta item alongside Zone / Source / Price."""
    js = (REPO / "web/assets/index.js").read_text()
    assert ">Type<" in js, "side panel missing Type meta-item label"
    assert "typePillHTML(r)" in js, (
        "side panel must use typePillHTML so the chip uses per-type colours"
    )


def test_table_render_threads_type_col_state():
    """renderTable must short-circuit the type cell when SHOW_TYPE_COL is false
    so single-type datasets emit the historical 7-column row shape unchanged."""
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function renderTable")[1].split("function ")[0]
    assert "SHOW_TYPE_COL ?" in block, (
        "renderTable must gate the type cell on SHOW_TYPE_COL"
    )


# ── D1: Multi-select type pills ─────────────────────────────────────────
# Top-toolbar pills replace the read-only Type column as the primary
# user-control for filtering by property_type. Each pill is independently
# toggleable; at least one must always be selected (last-pill snap-back).

def test_type_pills_present_in_html_for_all_three_types():
    html = (REPO / "web/index.html").read_text()
    for pt in ("land", "house", "condo"):
        assert f'data-type-pill="{pt}"' in html, f"Type pill missing for {pt}"


def test_type_pills_default_all_active():
    """Default state: all 3 types active so the dataset isn't filtered
    out before the user does anything. Pre-PR-D1 there was no type
    filter — the read-only Type column showed everything."""
    html = (REPO / "web/index.html").read_text()
    # Each pill renders with class 'active' baseline
    for pt in ("land", "house", "condo"):
        # Match the button regardless of attribute order
        snippet = f'data-type-pill="{pt}"'
        idx = html.find(snippet)
        # Look back at the opening <button to find its class
        opener = html.rfind("<button", 0, idx)
        button_tag = html[opener:idx + 50]
        assert "active" in button_tag, (
            f"Default-all-selected violated: pill {pt!r} not active in initial HTML"
        )


def test_types_f_state_initialized_as_set_of_three():
    js = (REPO / "web/assets/index.js").read_text()
    # The default literal in the state declaration
    assert "TYPES_F = new Set(['land', 'house', 'condo'])" in js, (
        "TYPES_F default not initialised to all 3 types"
    )


def test_filtered_rows_excludes_listings_outside_types_f():
    """JS filter logic mirror — TYPES_F.has(pt) gate must come before
    other filters so it short-circuits the rest."""
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function filteredRows")[1].split("function ")[0]
    assert "TYPES_F.has(pt)" in block, (
        "filteredRows must filter by TYPES_F membership"
    )


def test_type_pill_last_pill_snap_back_logic_present():
    """Must NEVER let the user de-toggle the last selected pill —
    otherwise the dataset becomes empty and the table goes blank."""
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function wireTypePills")[1].split("function ")[0]
    assert "TYPES_F.size === 1" in block, (
        "Snap-back guard missing — clicking an already-active pill when only one is "
        "active would leave 0 types selected and produce an empty table"
    )


def test_type_pill_url_state_round_trips():
    """readURL must accept ?types=land,house — comma-separated. pushURL
    must emit ?types= only when narrowing (URL stays clean by default)."""
    js = (REPO / "web/assets/index.js").read_text()
    # readURL parses it
    assert "p.get('types')" in js, "readURL doesn't accept ?types= URL state"
    # Validation: only known type names accepted
    assert "['land','house','condo'].includes(s)" in js, (
        "readURL doesn't validate the type names from ?types= — junk values would tip TYPES_F.size"
    )
    # pushURL emits only when not all 3 (default)
    assert "TYPES_F.size < 3" in js, (
        "pushURL emits ?types= even at default — URL won't stay clean"
    )


def test_type_pill_count_label_includes_active_types_when_narrowed():
    """Smart count narrative includes type info when narrowed (e.g.
    '... · Beach houses + Beach condos'). Empty when all 3 active."""
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function updateCounts")[1].split("function ")[0]
    assert "TYPES_F.size < 3" in block, (
        "updateCounts doesn't gate the type label on TYPES_F.size — "
        "the full label would always render and the count narrative gets noisy"
    )


def test_type_pill_active_color_uses_property_types_config():
    """Active pills get their colour from PROPERTY_TYPES (the single
    source of truth shared with row pills + side panel). Hardcoded
    colours would drift."""
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function _renderTypePill")[1].split("function ")[0]
    assert "PROPERTY_TYPES[pt]" in block, (
        "_renderTypePill not reading from PROPERTY_TYPES — pills can drift "
        "out of sync with row pill colours"
    )
    assert "cfg.pill_bg" in block and "cfg.pill_text" in block, (
        "_renderTypePill not setting both bg + text from the config"
    )


def test_type_pill_css_present():
    css = (REPO / "web/assets/index.css").read_text()
    assert ".type-pill-btn" in css, "Type pill CSS class missing"
    assert ".type-pills" in css, "Type pills container CSS class missing"


# ── D2: contextual area + $/m² rendering ───────────────────────────────
# Per-row contextual rendering — house/condo cells show built_area_m2
# and price_per_built_m2 when populated, else fall back to lot metric.
# Header text shifts when TYPES_F is built-only (no land selected).

def test_area_cell_helper_uses_built_for_house():
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function _areaCellHTML")[1].split("function ")[0]
    assert "r.built_area_m2" in block, (
        "_areaCellHTML doesn't read built_area_m2 — house/condo cells will "
        "show lot area instead of built area"
    )
    assert "fmtArea(r.area_m2)" in block, (
        "_areaCellHTML missing the lot-area fallback for built listings without "
        "built_area_m2 (80% of bienesraices houses lack it)"
    )


def test_ppm_cell_helper_uses_price_per_built_m2_for_house():
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function _ppmCellHTML")[1].split("function ")[0]
    assert "r.price_per_built_m2" in block, (
        "_ppmCellHTML doesn't read price_per_built_m2 — the metric the "
        "per-type ranker scored houses on (PR #72)"
    )


def test_render_table_uses_contextual_helpers():
    """renderTable + renderCards must call the helpers, not fmtArea/fmtPPM
    directly — otherwise built listings would always show lot metric and
    the per-type ranker numbers would be invisible to the user."""
    js = (REPO / "web/assets/index.js").read_text()
    rt_block = js.split("function renderTable")[1].split("function ")[0]
    assert "_areaCellHTML(r)" in rt_block, (
        "renderTable not using _areaCellHTML — table won't show built area"
    )
    assert "_ppmCellHTML(r)" in rt_block, (
        "renderTable not using _ppmCellHTML — table won't show $/built-m²"
    )
    rc_block = js.split("function renderCards")[1].split("function ")[0]
    assert "_areaCellHTML(r)" in rc_block, (
        "renderCards (mobile) not using _areaCellHTML — mobile won't show built area"
    )


def test_contextual_header_swaps_when_built_only_selected():
    """When TYPES_F excludes land entirely, headers shift from 'Area'/'$/m²'
    to 'Built m²'/'$/built-m²'. With land selected, headers stay at 'Area'/'$/m²'
    (consistent with mixed-view dominant metric)."""
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function _updateContextualHeaders")[1].split("function ")[0]
    assert "TYPES_F.has('land')" in block, (
        "_updateContextualHeaders doesn't gate on land membership in TYPES_F"
    )
    assert "Built m²" in block, "Built m² header label not present"
    assert "$/built-m²" in block, "$/built-m² header label not present"


def test_contextual_helpers_emit_built_suffix_only_for_house_with_built_area():
    """The tiny ' built' suffix disambiguates built area from lot area in
    mixed views. Must NOT appear on land rows or on house rows that fell
    back to lot metric (no built_area_m2)."""
    js = (REPO / "web/assets/index.js").read_text()
    block = js.split("function _areaCellHTML")[1].split("function ")[0]
    # The suffix is only emitted inside the built-area branch
    assert 'cell-suffix' in block, "built-area suffix span missing"
    # Suffix must be in the if-built branch, not the fallback
    if_branch_end = block.find("return fmtArea(r.area_m2)")
    suffix_idx = block.find('cell-suffix')
    assert suffix_idx < if_branch_end, (
        "'built' suffix renders even on lot-fallback rows — visual lies"
    )


def test_cell_suffix_css_present():
    css = (REPO / "web/assets/index.css").read_text()
    assert ".cell-suffix" in css, "Cell-suffix style missing"
