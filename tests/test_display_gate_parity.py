"""Parity test (plan 015): pin pulpo/display_gates.py::is_card_displayable
to the SAME canonical truth table that the TS predicate
(web/app/lib/card-image.ts::isCardImageDisplayable) is pinned to in
web/app/lib/card-image.parity.test.ts.

Both predicates encode `card_eligible === true && has_text_overlay !==
true`, but were tested independently — nothing asserted they AGREE.
This loads the shared fixture so a one-sided drift fails its parity
test (same defense as the dual-sitemap + email_type_contract
precedents). JSON null is loaded as Python None.

If this test fails on a row, the Python predicate has drifted from the
agreed contract — fix the predicate (or, if the contract genuinely
changed, update BOTH predicates AND the truth table in one PR).
"""

import json
from pathlib import Path

import pytest

from pulpo.display_gates import is_card_displayable

_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "display_gate_truth_table.json"
)


def _load_rows():
    with _FIXTURE.open() as fh:
        return json.load(fh)["rows"]


@pytest.mark.parametrize("row", _load_rows())
def test_python_predicate_matches_truth_table(row):
    li = {
        "card_eligible": row["card_eligible"],
        "has_text_overlay": row["has_text_overlay"],
    }
    assert is_card_displayable(li) is row["expected"], (
        f"display-gate drift: card_eligible={row['card_eligible']!r} "
        f"has_text_overlay={row['has_text_overlay']!r} "
        f"expected {row['expected']} got {is_card_displayable(li)}"
    )


def test_truth_table_covers_full_cross_product():
    # 3 states (true/false/null) x 2 inputs = 9 rows. A missing combo
    # would let a drift slip through unseen.
    rows = _load_rows()
    combos = {(r["card_eligible"], r["has_text_overlay"]) for r in rows}
    assert len(combos) == 9, f"expected 9 unique input combos, got {len(combos)}"
