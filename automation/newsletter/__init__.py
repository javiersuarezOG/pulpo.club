"""Pulpo fortnightly newsletter — build + render (PR-NL-2, dry-run only).

Public entry points:
    build_issue(recipient, listings, history, issue_date) -> Issue
    render_html(issue, locale) -> str

PR-NL-2 ships the renderer + per-cohort build path; sending is wired in PR-NL-3.
Dry-run only: nothing in this module talks to Resend.
"""

from .types import Recipient, Preference, IssuePick, Issue, Commentary, Cohort
from .build_issue import build_issue
from .render_html import render_html

__all__ = [
    "Recipient",
    "Preference",
    "IssuePick",
    "Issue",
    "Commentary",
    "Cohort",
    "build_issue",
    "render_html",
]
