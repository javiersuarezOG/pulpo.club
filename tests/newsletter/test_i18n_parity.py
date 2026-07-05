"""EN/ES parity guard for the newsletter i18n table.

Every key in `automation/newsletter/i18n.py` STRINGS must carry a non-empty
value for EVERY supported locale. This is the guard the string-migration
follow-up (launch audit) brings the renderer's copy under: ~18 user-visible
strings that used to live as inline `if locale == "en" … else …` ternaries in
render_html.py / build_issue.py now sit in this table, so a one-sided edit
(add/change EN, forget ES — or vice-versa) fails HERE instead of silently
shipping an asymmetric email to Spanish-first readers.

If a locale is added to `Locale`, this test automatically requires every key
to cover it (partial translations must be a deliberate, visible choice).
"""
from __future__ import annotations

from typing import get_args

from automation.newsletter import i18n

_LOCALES = get_args(i18n.Locale)  # ("en", "es")


def test_locale_set_is_nonempty():
    assert _LOCALES, "i18n.Locale resolved to no locales — parity guard is inert"


def test_every_string_key_has_every_locale():
    problems: list[str] = []
    for key, row in i18n.STRINGS.items():
        if not isinstance(row, dict):
            problems.append(f"{key}: value is {type(row).__name__}, expected dict")
            continue
        for loc in _LOCALES:
            val = row.get(loc)
            if not isinstance(val, str) or val == "":
                problems.append(f"{key}: locale {loc!r} missing or empty")
    assert not problems, (
        "newsletter i18n table has asymmetric keys:\n  " + "\n  ".join(problems)
    )


def test_migrated_render_keys_are_present():
    """Spot-check that the strings pulled out of render_html.py / build_issue.py
    actually landed in the table (guards against a future revert that moves
    copy back inline without anyone noticing)."""
    required = [
        "favorites.eyebrow", "favorites.headline.many", "favorites.open_all",
        "favorites.chip.price_dropped", "favorites.chip.still_listed.one",
        "favorites.card_cta", "favorites.summary.none_moved",
        "favorites.summary.some_moved", "preheader.with_rest", "preheader.fallback",
        "spotlight.reported_by", "pick.pill.under_area_avg",
        "filter.summary.land", "filter.summary.under_price",
    ]
    missing = [k for k in required if k not in i18n.STRINGS]
    assert not missing, f"migrated i18n keys missing from the table: {missing}"
