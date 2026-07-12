"""Free-member filter read path (bug 6 / PR-3b).

An email-only subscriber can set a filter via the login-free
/api/newsletter-prefs page, which stores it on the Resend contact's
`last_name`. This exercises the pipeline READ: list_audience parses last_name
→ ResendContact.pref_filter, and detect_cohort routes a free contact WITH a
filter to `free_prefs` (personalized) instead of `anonymous` (broad fallback).
"""

from automation.newsletter import subscribers
from automation.newsletter.build_issue import detect_cohort
from automation.newsletter.types import Preference, Recipient


def _rows(*contacts):
    return {"data": list(contacts)}


def test_list_audience_parses_filter_from_last_name():
    payload = _rows(
        {"id": "c1", "email": "a@example.com", "unsubscribed": False,
         "first_name": "pulpo-locale:es", "last_name": "pulpo-filter:pt=land;mx=500000"},
        {"id": "c2", "email": "b@example.com", "unsubscribed": False,
         "first_name": "", "last_name": ""},  # no filter
    )
    contacts = subscribers.list_audience("aud", api_key="x", get_override=lambda *a, **k: payload)
    by_email = {c.email: c for c in contacts}

    assert by_email["a@example.com"].pref_filter == {"property_types": ["land"], "max_price_usd": 500000.0}
    assert by_email["a@example.com"].locale == "es"          # first_name side-channel still works
    assert by_email["b@example.com"].pref_filter is None     # empty last_name → no filter


def test_list_audience_ignores_garbage_last_name():
    payload = _rows({"id": "c3", "email": "c@example.com", "unsubscribed": False,
                     "last_name": "John Smith"})  # a real name, not our prefix
    (contact,) = subscribers.list_audience("aud", api_key="x", get_override=lambda *a, **k: payload)
    assert contact.pref_filter is None


def _free_recipient(pref: Preference) -> Recipient:
    return Recipient(
        email_hash="h", display_name=None, locale="en", tier="free",
        has_account=False, preference=pref, saved_count=0, saves=[],
        preference_source="free_prefs" if _has(pref) else "none",
    )


def _has(pref: Preference) -> bool:
    return bool(pref.property_types or pref.max_price_usd or pref.zones or pref.categories)


def test_detect_cohort_email_only_with_filter_is_free_prefs():
    # The regression this feature turns on: has_account=False USED to always
    # mean "anonymous" (broad fallback), ignoring any filter.
    withf = _free_recipient(Preference(property_types=["land"], max_price_usd=500000))
    assert detect_cohort(withf) == "free_prefs"


def test_detect_cohort_email_only_without_filter_is_anonymous():
    nof = _free_recipient(Preference())
    assert detect_cohort(nof) == "anonymous"


def test_pref_filter_constructs_preference_via_splat():
    # subscribers.py does Preference(**c.pref_filter); prove the decoded dict
    # is always a valid kwargs set (paired with test_prefs_codec's field guard).
    from automation.newsletter import prefs_codec
    d = prefs_codec.decode("pulpo-filter:pt=condo;mx=300000;z=el_tunco")
    pref = Preference(**d)
    assert pref.property_types == ["condo"]
    assert pref.max_price_usd == 300000.0
    assert pref.zones == ["el_tunco"]
