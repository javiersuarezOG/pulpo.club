"""Single source of truth for the display-gate contract (plan 003).

Owner rule (2026-06-12): an image that's just text — a flyer, logo, or
render — must NEVER be shown on any surface. Curated surfaces (featured
pools, newsletter picks) DROP the listing when its card image is not
displayable; inventory surfaces (Browse/Discover, Saved, map cards) keep
the listing findable but swap the bad image for the category fallback —
that swap lives on the frontend in `web/app/lib/card-image.ts`, which
mirrors this predicate.

Consumers:
  - pulpo/featured_listing.py (_is_elite, _is_soft)
  - automation/newsletter/build_issue.py (_listing_has_eligible_photo,
    _absolute_photo)
"""

from typing import Any


def is_card_displayable(li: Any) -> bool:
    """Single source of truth: may this listing's card image be shown?

    card_eligible is the photo phase's verdict (resolution floor + not a
    logo/placeholder); has_text_overlay is the positive OCR flag for
    branded/flyer images. A None/missing card_eligible means the photo
    phase never approved a card image — treated as NOT displayable by
    design (that IS the hard rule). The frontend mirrors this predicate
    in its card-image fallback helper.
    """
    get = li.get if isinstance(li, dict) else lambda k: getattr(li, k, None)
    return get("card_eligible") is True and get("has_text_overlay") is not True
