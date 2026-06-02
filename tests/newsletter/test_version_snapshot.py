"""Golden-master version guard — you cannot change a template's rendered
output without bumping its version constant.

Why this exists: `render_html.py` is shared across all three Pulpo emails
(General weekly / Welcome / Welcome-back), so the file-level CI guard
(`scripts/diff_newsletter_version.mjs`) can't tell *which* template's
output a change affects — it only checks that `_common.py` was touched.
That let a complete welcome-template restructure ship while
`WELCOME_TEMPLATE_VERSION` stayed stale (the `<meta>` stamp, admin chip,
and PostHog slice key all lied). This guard closes that hole.

How it works: each template is rendered from a FIXED fixture (the
deterministic `ranked_pool`, a pinned date/recipient — never the live
nightly `ranked.json`), the version `<meta>` stamp is stripped, and the
remaining HTML is sha256'd. The hash + the current version constant are
compared against a committed snapshot (`_version_snapshots.json`):

  • render output changed AND version NOT bumped → FAIL
    ("bump <CONST>, then refresh the snapshot")
  • version bumped but render unchanged       → FAIL
    (spurious bump — revert or refresh)
  • both moved together                       → refresh the snapshot

Refresh after an intentional change:
    PULPO_UPDATE_VERSION_SNAPSHOTS=1 PULPO_OFFLINE=1 \
        python3 -m pytest tests/newsletter/test_version_snapshot.py -q
The update path REFUSES to write a changed hash under an unchanged
version, so it can't be used to bypass the bump requirement.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from automation.newsletter import build_issue
from automation.newsletter.components import _common
from automation.newsletter.render_html import (
    render_html,
    render_welcome_html,
    render_welcome_back_html,
)
from automation.newsletter.store import email_hash
from automation.newsletter.types import Preference, Recipient

_SNAPSHOT_PATH = Path(__file__).parent / "_version_snapshots.json"
_UPDATE = os.environ.get("PULPO_UPDATE_VERSION_SNAPSHOTS") == "1"
_META_RE = re.compile(r'<meta name="x-pulpo-template"[^>]*>')
_FIXED_DATE = datetime(2026, 6, 7, 16, 0, 0, tzinfo=timezone.utc)

# template_id → (render fn, version constant name, current value)
_TEMPLATES = {
    "pulpo-pro-general": (render_html, "TEMPLATE_VERSION", _common.TEMPLATE_VERSION),
    "pulpo-pro-welcome": (render_welcome_html, "WELCOME_TEMPLATE_VERSION", _common.WELCOME_TEMPLATE_VERSION),
    "pulpo-pro-welcome-back": (render_welcome_back_html, "WELCOME_BACK_TEMPLATE_VERSION", _common.WELCOME_BACK_TEMPLATE_VERSION),
}


def _recipient(locale: str) -> Recipient:
    """A single pinned Pro recipient — fully fixed so the render is
    reproducible across machines + runs."""
    return Recipient(
        email_hash=email_hash("canonical@pulpo.test"),
        display_name="Javier",
        locale=locale,
        tier="pro",
        has_account=True,
        preference=Preference(
            departments=["La Libertad"], property_types=["land"], max_price_usd=500_000
        ),
    )


def _content_sha(render_fn, ranked) -> str:
    """Render the template EN + ES from the fixed fixture, strip the
    version `<meta>` stamp (so the hash tracks template CONTENT, not the
    version label), and sha256 the concatenation."""
    parts = []
    for locale in ("en", "es"):
        issue = build_issue(
            recipient=_recipient(locale),
            ranked_listings=ranked,
            issue_number=42,
            issue_date=_FIXED_DATE,
            history_rows=None,
        )
        parts.append(_META_RE.sub("", render_fn(issue)))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def test_render_output_is_deterministic(ranked_pool):
    """Self-guard: the canonical render must be reproducible, or the
    snapshot below would be flaky. Renders each template twice."""
    for tid, (fn, _name, _ver) in _TEMPLATES.items():
        a = _content_sha(fn, ranked_pool)
        b = _content_sha(fn, ranked_pool)
        assert a == b, f"{tid} render is non-deterministic ({a[:12]} != {b[:12]})"


def test_render_matches_version_snapshot(ranked_pool):
    """The forcing function: a changed render must carry a version bump."""
    snapshot = json.loads(_SNAPSHOT_PATH.read_text()) if _SNAPSHOT_PATH.exists() else {}
    fresh: dict[str, dict] = {}
    problems: list[str] = []

    for tid, (fn, vname, ver) in _TEMPLATES.items():
        sha = _content_sha(fn, ranked_pool)
        fresh[tid] = {"version": ver, "content_sha256": sha}
        old = snapshot.get(tid)

        if _UPDATE:
            # Regeneration still enforces the bump — can't refresh a changed
            # hash under an unchanged version.
            if old and sha != old["content_sha256"] and ver == old["version"]:
                problems.append(
                    f"{tid}: render output changed but {vname} is still {ver!r} — "
                    f"bump it before refreshing the snapshot."
                )
            continue

        if old is None:
            problems.append(f"{tid}: missing snapshot entry — run PULPO_UPDATE_VERSION_SNAPSHOTS=1.")
        elif sha != old["content_sha256"]:
            if ver == old["version"]:
                problems.append(
                    f"{tid}: RENDER OUTPUT CHANGED but {vname} is still {ver!r}. "
                    f"Bump {vname} (semver) in _common.py, then refresh: "
                    f"PULPO_UPDATE_VERSION_SNAPSHOTS=1 pytest {Path(__file__).name}"
                )
            else:
                problems.append(
                    f"{tid}: render changed + {vname} bumped to {ver!r} — refresh the "
                    f"snapshot: PULPO_UPDATE_VERSION_SNAPSHOTS=1 pytest {Path(__file__).name}"
                )
        elif ver != old["version"]:
            problems.append(
                f"{tid}: {vname} is {ver!r} but the render is unchanged from snapshot "
                f"version {old['version']!r}. Revert the version or refresh the snapshot."
            )

    if _UPDATE:
        if problems:
            pytest.fail("Refusing to update snapshot:\n  " + "\n  ".join(problems))
        _SNAPSHOT_PATH.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n")
        pytest.skip(f"version snapshots refreshed → {_SNAPSHOT_PATH.name}")

    assert not problems, (
        "Version/render snapshot guard failed:\n  " + "\n  ".join(problems)
    )
