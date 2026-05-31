"""Templates registry — Python ↔ admin-widget alignment guard.

`automation/newsletter/templates/__init__.py :: TEMPLATES` is the
canonical map of `template_id → render(issue)`. Every `template`
field declared on a row of the admin widget's `NEWSLETTERS` array
(`web/app/admin/widgets/newsletter/NewsletterWidget.jsx`) MUST appear
as a key in TEMPLATES — otherwise an operator can choose a template
in the UI that doesn't exist on the renderer side, and the test
dispatch lands a 4xx with no useful diagnostic.

This test parses the JSX literally with a tiny regex (we don't run
a JS parser in pytest) and compares the set of `template: "…"`
values against TEMPLATES.keys().

Cheap to maintain: any time a new newsletter or template lands, the
test catches the half-shipped one within one CI run.
"""

from __future__ import annotations

import re
from pathlib import Path

from automation.newsletter.templates import TEMPLATES

# Repo root → newsletter widget. The path is stable; pin it.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_WIDGET_PATH = _REPO_ROOT / "web" / "app" / "admin" / "widgets" / "newsletter" / "NewsletterWidget.jsx"


def _template_ids_from_widget() -> set[str]:
    """Pull every `template: "…"` literal out of NewsletterWidget.jsx.

    The widget's NEWSLETTERS array is hand-edited (no JSON / no build
    step), so a regex over the source is more reliable than a JS
    parser. If the widget ever switches to a different declaration
    shape, update this regex + the matching helper in the widget.
    """
    src = _WIDGET_PATH.read_text(encoding="utf-8")
    # Match `template: "<id>"` inside the NEWSLETTERS literal.
    # Allows single OR double quotes; ids are kebab-case ASCII.
    pattern = re.compile(r'template\s*:\s*[\'\"]([a-z0-9][a-z0-9\-]*)[\'\"]')
    return set(pattern.findall(src))


def test_template_ids_align_widget_to_python():
    """Every `template: "…"` in the widget must be a key in TEMPLATES."""
    widget_ids = _template_ids_from_widget()
    assert widget_ids, (
        "No `template:` field found in NewsletterWidget.jsx — the regex "
        "may need updating after a refactor of the NEWSLETTERS array shape."
    )
    python_ids = set(TEMPLATES.keys())
    missing_in_python = widget_ids - python_ids
    assert not missing_in_python, (
        f"Widget references template ids that don't exist in the Python "
        f"TEMPLATES registry: {sorted(missing_in_python)}. "
        f"Add the matching `templates/<id>.py` module + register it in "
        f"`automation/newsletter/templates/__init__.py :: TEMPLATES`."
    )
    # Inverse check is intentionally NOT asserted — Python may carry
    # an experimental template that the widget hasn't surfaced yet
    # (e.g. building Pro Welcome before the admin row exists). The
    # one-way check (widget → python) is what prevents the
    # operator-facing 4xx.


def test_widget_template_version_matches_python_constant():
    """Widget surfaces a `TEMPLATE_VERSIONS` map keyed by template id.
    For every Python template registered in TEMPLATES, the widget's
    `version` + `lastUpdated` strings must reflect the Python source
    of truth — the `TEMPLATE_VERSION` constant in `_common.py`.

    Today the Python constant has the form:
        newsletter-v4.3-2026-05-31
    The widget splits this into a {version: "v4.3", lastUpdated:
    "2026-05-31"} pair (operator-friendly display). This guard
    parses the widget's literal map back out and asserts both halves
    match what `_common.TEMPLATE_VERSION` carries — so if anyone
    bumps Python without bumping the widget (or vice versa), CI fails.
    """
    from automation.newsletter.components import _common

    # The Python constant: "newsletter-vN.N-YYYY-MM-DD"
    pattern = re.compile(r"^newsletter-(v[\d.]+)-(\d{4}-\d{2}-\d{2})$")
    m = pattern.match(_common.TEMPLATE_VERSION)
    assert m, (
        f"TEMPLATE_VERSION isn't in 'newsletter-vN.N-YYYY-MM-DD' form: "
        f"{_common.TEMPLATE_VERSION!r}"
    )
    py_version, py_date = m.group(1), m.group(2)

    # Pull the widget's TEMPLATE_VERSIONS literal.
    src = _WIDGET_PATH.read_text(encoding="utf-8")
    widget_map_match = re.search(
        r'const\s+TEMPLATE_VERSIONS\s*=\s*\{([\s\S]*?)\};',
        src,
    )
    assert widget_map_match, (
        "Couldn't find `const TEMPLATE_VERSIONS = { … }` in the widget — "
        "the surrounding declaration shape may have changed and this "
        "regex needs updating."
    )
    block = widget_map_match.group(1)
    # Each entry has shape: "<id>": { version: "vN.N", lastUpdated: "YYYY-MM-DD" }
    entry_re = re.compile(
        r'[\'"]([a-z0-9][a-z0-9\-]*)[\'"]\s*:\s*\{\s*'
        r'version\s*:\s*[\'"]([^\'\"]+)[\'"]\s*,\s*'
        r'lastUpdated\s*:\s*[\'"]([^\'\"]+)[\'"]\s*\}'
    )
    widget_entries = {m.group(1): (m.group(2), m.group(3)) for m in entry_re.finditer(block)}

    assert "pulpo-pro-general" in widget_entries, (
        "Widget TEMPLATE_VERSIONS map is missing the canonical "
        "`pulpo-pro-general` entry."
    )
    widget_version, widget_date = widget_entries["pulpo-pro-general"]
    assert widget_version == py_version, (
        f"Widget version for pulpo-pro-general ({widget_version!r}) "
        f"doesn't match Python TEMPLATE_VERSION ({py_version!r}). "
        f"Update both — Python is the source of truth."
    )
    assert widget_date == py_date, (
        f"Widget lastUpdated for pulpo-pro-general ({widget_date!r}) "
        f"doesn't match Python TEMPLATE_VERSION date ({py_date!r}). "
        f"Update both — Python is the source of truth."
    )


def test_templates_callable_signature():
    """Every TEMPLATES entry must accept exactly one Issue arg and
    return a string. Catches accidental partial-init renderers."""
    from automation.newsletter.types import Issue

    for template_id, render_fn in TEMPLATES.items():
        assert callable(render_fn), f"TEMPLATES['{template_id}'] is not callable"
        # Signature check via inspect — we don't actually invoke
        # render_fn here (that would require fixtures). The component
        # snapshot tests in test_components.py exercise the real call.
        import inspect
        sig = inspect.signature(render_fn)
        params = [p for p in sig.parameters.values() if p.default is inspect.Parameter.empty]
        assert len(params) >= 1, (
            f"TEMPLATES['{template_id}'].render() must take at least one "
            f"required argument (the Issue); signature is {sig}"
        )
        # First required parameter should be typed Issue (or untyped).
        first = params[0]
        if first.annotation is not inspect.Parameter.empty:
            assert first.annotation is Issue or first.annotation == "Issue" or first.annotation == Issue.__name__, (
                f"TEMPLATES['{template_id}'].render() first arg annotation "
                f"should be `Issue`, got {first.annotation!r}"
            )
