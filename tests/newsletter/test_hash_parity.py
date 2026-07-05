"""Python side of the recipient-hash cross-runtime parity guard.

The unsubscribe/resubscribe link's `r=` param is `store.email_hash(email)`
(sha256(salt:email.strip().lower())[:24]). /api/unsubscribe.js re-derives
the SAME hash in JS to find the contact. If the two implementations ever
drift on salt, normalization, algorithm, or truncation, every unsubscribe
link silently no-ops — a bug that has shipped before (unsalted / 16-char).

This test and its JS twin (tests/api/hash_parity.test.js) both assert the
same golden vectors in tests/fixtures/hash_parity_vectors.json. A one-sided
change to either implementation fails that side's test against the shared
`expected` value.
"""
from __future__ import annotations

import json
from pathlib import Path

from automation.newsletter.store import email_hash

_FIXTURE = Path(__file__).parents[1] / "fixtures" / "hash_parity_vectors.json"


def _vectors():
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))["vectors"]


def test_email_hash_matches_shared_golden_vectors():
    for v in _vectors():
        got = email_hash(v["email"], salt=v["salt"])
        assert got == v["expected"], (
            f"Python email_hash drifted for {v['email']!r} (salt {v['salt']!r}): "
            f"got {got!r}, shared golden {v['expected']!r}. If this was an "
            f"intentional hash change, update BOTH runtimes + the fixture."
        )
        assert len(got) == 24


def test_email_hash_normalizes_case_and_whitespace():
    # The trim+lower normalization is load-bearing for parity — pin it.
    a = email_hash("  User@Example.COM  ", salt="s")
    b = email_hash("user@example.com", salt="s")
    assert a == b
