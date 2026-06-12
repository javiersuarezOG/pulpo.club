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
  - pulpo/featured_listing.py + automation/ig_photo_gate.py read
    HIRES_WATERMARK_ISSUE / has_watermark_issue (plan 005).
"""

from typing import Any

# The deterministic aesthetic detector
# (automation/aesthetic_deterministic.py) flags corner-density / OCR-word
# watermarks with this exact issue string (see its module docstring's
# "Issues vocabulary" + the literal at aesthetic_deterministic.py:117).
# Single source of truth for the CONSUMER side: the producer owns the
# literal, the curated-surface gates read it through this name so the
# string isn't scattered across featured_listing.py + ig_photo_gate.py.
HIRES_WATERMARK_ISSUE = "logo_or_watermark"


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


def has_watermark_issue(li: Any) -> bool:
    """True when the hires deterministic aesthetic pass flagged the hero as
    a logo/watermark (HIRES_WATERMARK_ISSUE in li.hires_aesthetic_issues).

    Consumed by the curated surfaces — featured pools (_is_elite/_is_soft)
    and the IG gate — to drop a hero the pipeline already detected as
    watermarked. None/missing issues = no signal = not flagged.
    """
    get = li.get if isinstance(li, dict) else lambda k: getattr(li, k, None)
    issues = get("hires_aesthetic_issues") or []
    return HIRES_WATERMARK_ISSUE in issues
