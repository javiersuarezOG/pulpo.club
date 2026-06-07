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


def test_widget_does_not_carry_a_hardcoded_version_mirror():
    """v4.4 (2026-06-01): the widget used to maintain a hardcoded
    `TEMPLATE_VERSIONS` map that had to be bumped in lock-step with
    every Python TEMPLATE_VERSION change. That mirror is gone —
    replaced by a fetch to /api/admin/newsletter/template-version
    which reads the Python constant from disk at request time.

    This guard prevents the mirror from creeping back in. If a
    future change re-adds a literal `TEMPLATE_VERSIONS = { ... }`
    object with hardcoded version strings, this test fails and the
    reviewer is forced to consciously decide whether to reintroduce
    the drift risk. The hardcoded version pattern is unmistakable:
    `vN.N` literal next to a `YYYY-MM-DD` literal inside the same
    object. Operator-facing template chrome reads
    `templateVersions[nl.template]` (state from useState), not a
    module-level constant.
    """
    src = _WIDGET_PATH.read_text(encoding="utf-8")
    # If a `TEMPLATE_VERSIONS = { … }` const declaration ever reappears
    # at module scope with a literal version + date pair, fail.
    suspicious = re.search(
        r'const\s+TEMPLATE_VERSIONS\s*=\s*\{[\s\S]*?'
        r'version\s*:\s*[\'"]v\d+\.\d+[\'"][\s\S]*?'
        r'lastUpdated\s*:\s*[\'"]\d{4}-\d{2}-\d{2}[\'"]',
        src,
    )
    assert suspicious is None, (
        "Found a hardcoded `const TEMPLATE_VERSIONS = { version: 'vN.N', "
        "lastUpdated: 'YYYY-MM-DD' }` block in the widget. This mirror "
        "was deliberately removed in v4.4 — versions are now fetched "
        "from /api/admin/newsletter/template-version at runtime. Don't "
        "reintroduce the mirror; use the fetch path instead."
    )
    # And the runtime consumer should read from state, not a constant.
    assert "templateVersions[" in src, (
        "Widget no longer references `templateVersions[...]` — the "
        "useState-backed lookup may have been refactored out. The "
        "operator-facing template chrome needs to render the fetched "
        "version somewhere."
    )


def test_python_template_version_shape():
    """Sanity guard on the Python source-of-truth constants — both the
    weekly General and the one-shot Welcome version lines must follow
    the `<prefix>-vN.N-YYYY-MM-DD` shape so the API endpoint's
    `SHORT_VERSION_RE` (in api/admin/newsletter/template-version.js)
    can extract the short `vN.N` form for the admin widget chrome.

    A misformatted constant (typo, missing year, wrong dash style)
    would silently render the full string on the operator chip until
    someone noticed. Catching it here keeps the admin widget pretty
    AND keeps the API endpoint's match logic correct.

    Also asserts that the date inside the version line agrees with
    LAST_UPDATED — bumping one without the other is the classic drift
    bug. Each template (General / Welcome) carries its own pair.
    """
    from automation.newsletter.components import _common

    general_pattern = re.compile(r"^newsletter-(v[\d.]+)-(\d{4}-\d{2}-\d{2})$")
    m_general = general_pattern.match(_common.TEMPLATE_VERSION)
    assert m_general, (
        f"TEMPLATE_VERSION isn't in 'newsletter-vN.N-YYYY-MM-DD' form: "
        f"{_common.TEMPLATE_VERSION!r}"
    )

    welcome_pattern = re.compile(r"^welcome-(v[\d.]+)-(\d{4}-\d{2}-\d{2})$")
    m_welcome = welcome_pattern.match(_common.WELCOME_TEMPLATE_VERSION)
    assert m_welcome, (
        f"WELCOME_TEMPLATE_VERSION isn't in 'welcome-vN.N-YYYY-MM-DD' form: "
        f"{_common.WELCOME_TEMPLATE_VERSION!r}"
    )

    # Welcome-back carries its own pair too — the admin template-version
    # API extracts it for the "Pro · Welcome-back" card chip, and
    # SHORT_VERSION_RE (`-vN.N-`) must be able to pull the short form.
    welcome_back_pattern = re.compile(r"^welcome-back-(v[\d.]+)-(\d{4}-\d{2}-\d{2})$")
    m_welcome_back = welcome_back_pattern.match(_common.WELCOME_BACK_TEMPLATE_VERSION)
    assert m_welcome_back, (
        f"WELCOME_BACK_TEMPLATE_VERSION isn't in 'welcome-back-vN.N-YYYY-MM-DD' "
        f"form: {_common.WELCOME_BACK_TEMPLATE_VERSION!r}"
    )

    # Free general (free-tier weekly) carries its own pair so the admin
    # template-version API can chip the "Free · Weekly" card, and
    # SHORT_VERSION_RE (`-vN.N-`) must pull the short form from the
    # `free-general-vN.N-YYYY-MM-DD` line.
    free_general_pattern = re.compile(r"^free-general-(v[\d.]+)-(\d{4}-\d{2}-\d{2})$")
    m_free_general = free_general_pattern.match(_common.FREE_GENERAL_TEMPLATE_VERSION)
    assert m_free_general, (
        f"FREE_GENERAL_TEMPLATE_VERSION isn't in 'free-general-vN.N-YYYY-MM-DD' "
        f"form: {_common.FREE_GENERAL_TEMPLATE_VERSION!r}"
    )

    iso_date = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    assert iso_date.match(_common.LAST_UPDATED), (
        f"LAST_UPDATED isn't ISO-8601 YYYY-MM-DD: {_common.LAST_UPDATED!r}"
    )
    assert iso_date.match(_common.WELCOME_LAST_UPDATED), (
        f"WELCOME_LAST_UPDATED isn't ISO-8601 YYYY-MM-DD: "
        f"{_common.WELCOME_LAST_UPDATED!r}"
    )
    assert iso_date.match(_common.WELCOME_BACK_LAST_UPDATED), (
        f"WELCOME_BACK_LAST_UPDATED isn't ISO-8601 YYYY-MM-DD: "
        f"{_common.WELCOME_BACK_LAST_UPDATED!r}"
    )
    assert iso_date.match(_common.FREE_GENERAL_LAST_UPDATED), (
        f"FREE_GENERAL_LAST_UPDATED isn't ISO-8601 YYYY-MM-DD: "
        f"{_common.FREE_GENERAL_LAST_UPDATED!r}"
    )
    assert m_free_general.group(2) == _common.FREE_GENERAL_LAST_UPDATED, (
        f"FREE_GENERAL_TEMPLATE_VERSION date ({m_free_general.group(2)!r}) "
        f"doesn't match FREE_GENERAL_LAST_UPDATED "
        f"({_common.FREE_GENERAL_LAST_UPDATED!r}). Bump both — Python is "
        f"the source of truth."
    )

    assert m_general.group(2) == _common.LAST_UPDATED, (
        f"TEMPLATE_VERSION date ({m_general.group(2)!r}) doesn't match "
        f"LAST_UPDATED ({_common.LAST_UPDATED!r}). Bump both — Python is "
        f"the source of truth."
    )
    assert m_welcome.group(2) == _common.WELCOME_LAST_UPDATED, (
        f"WELCOME_TEMPLATE_VERSION date ({m_welcome.group(2)!r}) doesn't "
        f"match WELCOME_LAST_UPDATED ({_common.WELCOME_LAST_UPDATED!r}). "
        f"Bump both — Python is the source of truth."
    )
    assert m_welcome_back.group(2) == _common.WELCOME_BACK_LAST_UPDATED, (
        f"WELCOME_BACK_TEMPLATE_VERSION date ({m_welcome_back.group(2)!r}) "
        f"doesn't match WELCOME_BACK_LAST_UPDATED "
        f"({_common.WELCOME_BACK_LAST_UPDATED!r}). Bump both — Python is "
        f"the source of truth."
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
