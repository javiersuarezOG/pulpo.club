"""Paywall banner — Pro upsell band shown only on Free-cohort renders.

Visual reference: web/newsletter-mockup-v4-en.html — does NOT appear
in the Pro Preview mockup because the mockup is a Pro recipient.
Appears between picks 03 and the "7 more this week" section header
when `issue.paywall_banner == True`.

Locked contract for v4:
  • Forest-green band, paper text
  • Eyebrow "FREE EDITION" + serif H2 "You're seeing the public cut."
  • Body paragraph + price-anchored "Go Pro — $9.99/month →" CTA
  • Links to `issue.paywall_target_url` (Stripe checkout entrypoint)

Skipped entirely for Pro / Agency / Pro-Preview recipients —
`render_html()` returns "" when `issue.paywall_banner is False`.

Today the block lives inline in `render_html.py`; this re-export
gives future templates the same composition surface.
"""

from __future__ import annotations

from ..render_html import _paywall_banner_html as paywall_banner_html

__all__ = ["paywall_banner_html"]
