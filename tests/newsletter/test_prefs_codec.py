"""Python side of the free-member filter codec parity contract.

The SAME fixture (tests/fixtures/prefs_codec_cases.json) is asserted by the JS
side in tests/api/prefs_codec_contract.test.js. The endpoint (JS) WRITES the
value; this module (Python) READS it in the pipeline — if they drift, the
nightly silently mis-reads every free-member filter. Move both together.
"""

import json
from pathlib import Path

from automation.newsletter import prefs_codec

_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "prefs_codec_cases.json"
_CASES = json.loads(_FIXTURE.read_text())


def _norm(pref: dict) -> dict:
    # The JSON fixture carries max/min as ints; Python decode yields floats.
    # Normalize numeric fields so the cross-language dict comparison is fair —
    # the STRING is the real contract, this just makes the dict assert honest.
    out = dict(pref)
    for k in ("max_price_usd", "min_price_usd"):
        if k in out and out[k] is not None:
            out[k] = float(out[k])
    return out


def test_encode_matches_shared_fixture():
    for c in _CASES["encode"]:
        assert prefs_codec.encode(c["pref"]) == c["out"], c


def test_decode_matches_shared_fixture():
    for c in _CASES["decode"]:
        assert prefs_codec.decode(c["in"]) == _norm(c["out"]), c


def test_decode_never_raises_on_hostile_input():
    # Non-strings → empty dict.
    for bad in (None, 42, b"bytes", {}):
        assert prefs_codec.decode(bad) == {}
    # A tampered string is SANITIZED (not rejected): no markup / separators
    # can survive back into the parsed values — the security property that
    # lets subscribers.py trust the splat and lets the endpoint trust the
    # re-decoded summary. `<script>` collapses to the slug `script`.
    out = prefs_codec.decode("pulpo-filter:pt=<script>;mx=;;;=x")
    for slug in out.get("property_types", []):
        assert all(ch.isalnum() or ch in "_-" for ch in slug)
    # Total on any string — never raises.
    for s in ("", "pulpo-filter:", "random", "pulpo-filter:mn=0"):
        prefs_codec.decode(s)


def test_encode_decode_roundtrip_stable():
    s = "pulpo-filter:pt=land,house;mx=500000"
    assert prefs_codec.encode(prefs_codec.decode(s)) == s


def test_decode_only_emits_valid_preference_fields():
    # Guards the splat in subscribers.py: Preference(**decode(...)) must never
    # get an unknown kwarg. Every key decode emits is a real Preference field.
    from automation.newsletter.types import Preference
    valid = set(Preference().__dict__.keys())
    decoded = prefs_codec.decode("pulpo-filter:pt=land;mx=500000;mn=1;z=x;cat=y")
    assert set(decoded).issubset(valid)
    # And it actually constructs.
    Preference(**decoded)
