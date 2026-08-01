"""The Fact Ledger is complete, sourced, dated, tied to the registry, and
its stat-trace guard catches un-sourced macro numbers while leaving listing
figures alone. Credibility posts cite ONLY from here."""
from __future__ import annotations

import re
from datetime import date

from automation import ig_facts as facts
from automation import ig_content_categories as cats


def test_every_fact_is_complete():
    for fid, f in facts.FACTS.items():
        for field in facts.REQUIRED_FIELDS:
            assert f.get(field) not in (None, ""), f"{fid} missing {field}"
        assert isinstance(f["number"], (int, float))
        assert f["value_es"] != f["value_en"]  # bilingual, not copy-paste


def test_every_fact_is_sourced_and_dated():
    for fid, f in facts.FACTS.items():
        assert re.match(r"^https?://", f["source_url"]), f"{fid} source_url not a URL"
        assert f["source"], f"{fid} has no named source"
        date.fromisoformat(f["as_of"])  # raises if not a real ISO date


def test_fact_levers_reference_real_registry_slugs():
    # A fact tagged for a lever that doesn't exist = it can never be cited.
    for fid, f in facts.FACTS.items():
        for lever in f["levers"]:
            assert lever in cats.CATEGORIES, f"{fid} tags unknown lever {lever!r}"


def test_no_crime_fact_exists():
    # HARD RULE (2026-08-01): the ledger carries NO crime/homicide fact, and
    # no fact statement may reference crime/safety-by-numbers framing.
    assert facts.get("homicide_rate_2024") is None
    for fid, f in facts.FACTS.items():
        for field in ("statement_es", "statement_en", "value_es", "value_en"):
            assert facts.mentions_banned_topic(f[field]) == [], f"{fid} {field} names a banned topic"


def test_banned_topic_guard_catches_crime_framing():
    for phrase in (
        "El país más seguro del hemisferio es un dato.",
        "The safest country in the hemisphere.",
        "una tasa de 1.9 homicidios por cada 100 mil habitantes",
        "libre de pandillas y maras",
        "gang violence is down",
    ):
        assert facts.mentions_banned_topic(phrase), f"missed: {phrase!r}"
    # a clean lifestyle/investment line trips nothing
    assert facts.mentions_banned_topic("Domingo, 7am, el Pacífico a 30 metros.") == []


def test_for_lever_and_get():
    inv = {f["id"] for f in facts.for_lever("investment")}
    assert "remesas_2024" in inv and "dollarized_since_2001" in inv
    # authority now cites tourism / dollarization — NOT crime
    auth = {f["id"] for f in facts.for_lever("authority")}
    assert auth and "homicide_rate_2024" not in auth
    assert facts.get("tourism_2024")["number"] == 3.9
    assert facts.get("nope") is None


def test_stat_guard_passes_sourced_numbers():
    # A caption citing ledger figures is clean (remesas + tourism, both in-ledger).
    clean = "En 2024 se enviaron $8,479 millones en remesas y llegaron 3.9 millones de visitantes."
    assert facts.stat_violations(clean) == []


def test_stat_guard_flags_an_invented_macro_stat():
    bad = "El 73% de los extranjeros ya compró aquí."  # 73% is in no ledger fact
    v = facts.stat_violations(bad)
    assert v and "73%" in v[0]


def test_stat_guard_ignores_listing_figures():
    # Price + size + rooms are listing data, not macro stats — never flagged.
    listing = "Casa de 3 recámaras, 1,000 m², frente al mar · $350,000. pulpo.club"
    assert facts.stat_violations(listing) == []
