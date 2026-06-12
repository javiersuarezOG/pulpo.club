"""Display-gate contract (plan 003): the single source of truth for
whether a listing's card image may be shown. Consumers are the featured
pools (pulpo/featured_listing.py) and the newsletter picks
(automation/newsletter/build_issue.py); the frontend mirrors this in
web/app/lib/card-image.ts.
"""

from pulpo.display_gates import is_card_displayable


class _Obj:
    """Attribute-style listing (the featured-pool path passes objects)."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def test_card_eligible_true_no_overlay_displayable():
    assert is_card_displayable({"card_eligible": True, "has_text_overlay": False}) is True


def test_card_eligible_true_overlay_none_displayable():
    # None = no OCR signal; not a positive text-overlay flag → still shows.
    assert is_card_displayable({"card_eligible": True, "has_text_overlay": None}) is True


def test_card_eligible_true_missing_overlay_displayable():
    assert is_card_displayable({"card_eligible": True}) is True


def test_text_overlay_true_not_displayable():
    assert is_card_displayable({"card_eligible": True, "has_text_overlay": True}) is False


def test_card_eligible_false_not_displayable():
    assert is_card_displayable({"card_eligible": False, "has_text_overlay": False}) is False


def test_card_eligible_none_not_displayable():
    # Photo phase never approved a card image → ineligible by design.
    assert is_card_displayable({"card_eligible": None}) is False


def test_card_eligible_missing_not_displayable():
    assert is_card_displayable({}) is False


def test_works_on_objects_not_just_dicts():
    assert is_card_displayable(_Obj(card_eligible=True, has_text_overlay=False)) is True
    assert is_card_displayable(_Obj(card_eligible=True, has_text_overlay=True)) is False
    assert is_card_displayable(_Obj(card_eligible=False)) is False
    # Missing attributes → getattr default None → ineligible.
    assert is_card_displayable(_Obj()) is False


def test_truthy_non_true_card_eligible_not_displayable():
    # Strict identity: only the boolean True passes, not 1 or "yes".
    assert is_card_displayable({"card_eligible": 1}) is False
    assert is_card_displayable({"card_eligible": "true"}) is False
