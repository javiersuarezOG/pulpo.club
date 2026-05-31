"""Subject-line tests for scripts/send_newsletter.py::_subject_for.

The inbox subject is product-visible chrome, not just transport metadata:
the From column already carries the brand, so the subject should add the
tier ("Pro") and the issue identifier, not duplicate "Pulpo · ...". The
issue-content tease moves to the hidden preheader (see
tests/newsletter/test_components.py::test_pro_general_renders_hidden_preheader).
"""
from __future__ import annotations
import sys
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import send_newsletter as send  # noqa: E402


def _issue(*, n: int = 1, cohort: str = "pro_prefs"):
    return SimpleNamespace(issue_number=n, cohort=cohort)


def test_subject_en_is_brand_tier_issue():
    out = send._subject_for(_issue(n=1), "en")
    assert out == "Pulpo Pro · Issue 01"


def test_subject_es_uses_edicion():
    out = send._subject_for(_issue(n=7), "es")
    assert out == "Pulpo Pro · Edición 07"


def test_subject_zero_pads_issue_number():
    assert send._subject_for(_issue(n=42), "en") == "Pulpo Pro · Issue 42"
    assert send._subject_for(_issue(n=3), "es") == "Pulpo Pro · Edición 03"


def test_subject_preview_mode_prefixes_with_cohort_tag():
    """Operator previews keep the loud [PULPO PREVIEW · cohort] prefix
    so they're trivially distinguishable from real broadcasts in the
    operator's own inbox."""
    out = send._subject_for(_issue(n=1, cohort="pro_prefs"), "en", preview=True)
    assert out.startswith("[PULPO PREVIEW · pro_prefs]")
    assert "Issue 01" in out


def test_subject_drops_redundant_brand_prefix_from_v3():
    """Guard: never reintroduce the wordy v3 subject that duplicated
    brand + appended ' · 10 picks this fortnight'. That copy moved to
    the hidden preheader."""
    for n in (1, 14, 99):
        en = send._subject_for(_issue(n=n), "en")
        es = send._subject_for(_issue(n=n), "es")
        assert "10 picks this fortnight" not in en
        assert "10 selecciones esta quincena" not in es
        # Issue prefix is exactly the tag once.
        assert en.count("Pulpo") == 1
        assert es.count("Pulpo") == 1
