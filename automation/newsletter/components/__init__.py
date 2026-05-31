"""Pulpo newsletter component library.

Every newsletter Pulpo ships is composed from the components in this
package. The canonical reference is `automation.newsletter.templates.
pulpo_pro_general` — the Pulpo Pro General template that powers the
weekly digest. Future templates (Pro Welcome, Free Welcome, Free
Weekly) import from this package and compose their own recipes.

Discoverability
───────────────

Each component module documents its locked contract (what's fixed
across templates, what's swappable) at the top of the file. The
mockup that locked the v4 design lives at
`web/newsletter-mockup-v4-en.html` — open it in a browser for the
visual reference.

How to add a new template
─────────────────────────

1. Decide what changes from the General template. Most templates
   reuse 70-90% of the components.
2. Create `automation/newsletter/templates/<id>.py`:

      from ..components import brand, hero, picks, editorial, personal, paywall
      from ..components._common import CSS, TEMPLATE_VERSION

      def render(issue):
          # compose the body from components in the order you want
          ...

3. Add the template id to the registry in
   `automation/newsletter/templates/__init__.py :: TEMPLATES`.
4. Add the matching newsletter row to `NEWSLETTERS` in
   `web/app/admin/widgets/newsletter/NewsletterWidget.jsx` with
   `template: "<id>"`.
5. The CI alignment check in `tests/newsletter/test_templates.py`
   keeps the JS + Python registries in lock-step — if you forget
   one side, CI fails red.

Why these are currently re-exports
──────────────────────────────────

For v4.2 (2026-05-31) the component modules re-export the existing
private helpers from `render_html.py`. The implementation stays in
one place to minimize blast radius while the architecture beds in.
A follow-up PR will move the function bodies into the matching
component module so each block becomes truly self-contained.

For template authors, the re-export is invisible: import paths and
function signatures are stable.
"""

# NB: sub-modules are NOT eagerly imported here. Templates that need
# them import explicitly:
#
#     from automation.newsletter.components import picks
#     from automation.newsletter.components._common import CSS, escape
#
# Eager imports would trigger a circular cycle today (the component
# modules currently re-export from `render_html.py`, which itself
# imports `TEMPLATE_VERSION` from `_common`). Once the function bodies
# are lifted out of render_html.py into the component modules (follow-
# up PR), this restriction can be lifted.
#
# The `__all__` lists every documented sub-module so editors / IDEs
# still surface them in auto-complete.
__all__ = [
    "_common",
    "brand",
    "editorial",
    "favorites",
    "hero",
    "paywall",
    "personal",
    "picks",
]
