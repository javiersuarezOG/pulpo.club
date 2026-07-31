"""The IG voice guide stays in lockstep with the 7-lever registry and
names its load-bearing rules. If a lever is added to the registry, the
guide must speak to it (or the Copywriter has no tone for that post)."""
from __future__ import annotations

from pathlib import Path

from automation import ig_content_categories as cats

GUIDE = Path("automation/ig_voice_guide.md")


def test_guide_exists_and_is_substantial():
    assert GUIDE.exists()
    assert len(GUIDE.read_text(encoding="utf-8")) > 1500


def test_guide_covers_every_content_lever():
    text = GUIDE.read_text(encoding="utf-8").lower()
    for slug, c in cats.CATEGORIES.items():
        # the "Tone per lever" section names each lever by its EN label's
        # first word (Scarcity, Authority, Social proof, …).
        term = c["name_en"].split()[0].lower()
        assert term in text, f"voice guide never addresses the {slug} lever ({term})"


def test_guide_states_the_load_bearing_rules():
    text = GUIDE.read_text(encoding="utf-8").lower()
    for must in ("voseo", "link en bio", "· · ·"):
        assert must in text, f"voice guide is missing a core rule: {must!r}"
