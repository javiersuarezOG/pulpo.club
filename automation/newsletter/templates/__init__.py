"""Pulpo newsletter templates registry.

Maps a stable `template_id` (the same id the admin widget's
`NEWSLETTERS` registry stamps on each newsletter row) to the Python
render function that produces the email HTML for it.

When a new newsletter ships:
  1. Add a template module under `automation/newsletter/templates/`
     (e.g. `pulpo_pro_welcome.py`) exposing a `render(issue) -> str`.
  2. Add a row here mapping the id → `<module>.render`.
  3. Add a row to `NEWSLETTERS` in
     `web/app/admin/widgets/newsletter/NewsletterWidget.jsx` with
     `template: "<id>"` so the admin widget shows the template label
     on the relevant newsletter card.

CI guard: `tests/newsletter/test_templates.py` asserts the id list
here matches the `template` field across `NEWSLETTERS` in the widget
file — if they drift, the test fails red.
"""

from __future__ import annotations

from typing import Callable

from ..types import Issue
from . import (
    pulpo_pro_general,
    pulpo_pro_welcome,
    pulpo_pro_welcome_back,
    pulpo_free_general,
    pulpo_free_welcome,
    pulpo_free_welcome_back,
)

# template_id  →  render function
# Every value MUST be a callable taking exactly one `Issue` argument
# and returning the rendered HTML string. The test_templates.py guard
# enforces this at import time.
TEMPLATES: dict[str, Callable[[Issue], str]] = {
    "pulpo-pro-general": pulpo_pro_general.render,
    "pulpo-pro-welcome": pulpo_pro_welcome.render,
    "pulpo-pro-welcome-back": pulpo_pro_welcome_back.render,
    "pulpo-free-general": pulpo_free_general.render,
    "pulpo-free-welcome": pulpo_free_welcome.render,
    "pulpo-free-welcome-back": pulpo_free_welcome_back.render,
}

__all__ = [
    "TEMPLATES",
    "pulpo_pro_general",
    "pulpo_pro_welcome",
    "pulpo_pro_welcome_back",
    "pulpo_free_general",
    "pulpo_free_welcome",
    "pulpo_free_welcome_back",
]
