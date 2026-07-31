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


def test_contested_figures_carry_a_caveat():
    # The homicide figure is the government's (excludes some deaths); it MUST
    # carry framing so the Copywriter never states it as neutral fact.
    assert facts.get("homicide_rate_2024")["caveat"]
    assert "oficial" in facts.get("homicide_rate_2024")["caveat"].lower()


def test_for_lever_and_get():
    inv = {f["id"] for f in facts.for_lever("investment")}
    assert "remesas_2024" in inv and "dollarized_since_2001" in inv
    assert facts.get("tourism_2024")["number"] == 3.9
    assert facts.get("nope") is None


def test_stat_guard_passes_sourced_numbers():
    # A caption citing ledger figures is clean.
    clean = "En 2024 se enviaron $8,479 millones en remesas. La tasa fue 1.9 por cada 100 mil."
    assert facts.stat_violations(clean) == []


def test_stat_guard_flags_an_invented_macro_stat():
    bad = "El 73% de los extranjeros ya compró aquí."  # 73% is in no ledger fact
    v = facts.stat_violations(bad)
    assert v and "73%" in v[0]


def test_stat_guard_ignores_listing_figures():
    # Price + size + rooms are listing data, not macro stats — never flagged.
    listing = "Casa de 3 recámaras, 1,000 m², frente al mar · $350,000. pulpo.club"
    assert facts.stat_violations(listing) == []
