"""Pure-function tests for scripts/retrofit_descriptions.py — plan 011.

No network, no file I/O: select_targets() and apply_result() are
import-safe pure functions over plain dicts. The failure modes that
matter for the backfill (selection, geocoding preservation, only-fill-
nulls fact merge) are all covered here; the full-script path follows the
repo precedent of retrofit_geocoding.py (no mocked-network test).
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts.retrofit_descriptions import apply_result, select_targets  # noqa: E402
from automation.llm_enrichment_prompts import PROMPT_VERSION  # noqa: E402
from automation.llm_enrichment_schema import DEFAULT_SCHEMA, validate_response  # noqa: E402


# ── fixtures ────────────────────────────────────────────────────────────

def _entry(**over) -> dict:
    """A pre-008 sidecar entry (no prompt_version key — the selector)."""
    e = {
        "ts": "2026-03-01T00:00:00+00:00",
        "model": "deepseek-chat",
        "schema_version": 3,
        "title_canonical": {"en": "Old Title", "es": "Título Viejo"},
        "short_description_canonical": {
            "en": "Discover this stunning paradise lot with breathtaking views.",
            "es": "Descubra este paraíso impresionante.",
        },
        "reasons_to_buy": [
            {"en": "Perfect for your dream home", "es": "Perfecto para su hogar soñado"},
        ],
        "lat": 13.493111,
        "lng": -89.383222,
        "geocoding_confidence": "high",
        "geocoding_source": "estimated",
        "geocoding_reference": "Playa El Tunco",
        "url_language": "es",
        "tokens_in": 1000,
        "tokens_out": 400,
        "cost_usd": 0.00077,
        "finish_reason": "stop",
        "latency_ms": 5000,
    }
    e.update(over)
    return e


def _listing(**over) -> dict:
    li = {
        "source": "remax",
        "source_id": "123",
        "description": "Casa en venta en El Tunco, 3 habitaciones, construida en 2015.",
        "title_canonical": {"en": "Old Title", "es": "Título Viejo"},
        "short_description_canonical": {"en": "Discover...", "es": "Descubra..."},
        "reasons_to_buy": [],
        "bedrooms": None,
        "bathrooms": None,
        "year_built": None,
        "lat": 13.493111,
        "lng": -89.383222,
    }
    li.update(over)
    return li


def _parsed(**over) -> dict:
    """A valid v4 LLM response (passes validate_response)."""
    p = {
        "title": {"en": " New House Title ", "es": "Título Nuevo"},
        "description": {
            "en": "Three-bedroom house in El Tunco, built 2015.",
            "es": "Casa de tres habitaciones en El Tunco, construida en 2015.",
        },
        "usps": [
            {"en": "Built 2015", "es": "Construida 2015"},
            {"en": "3 bedrooms", "es": "3 habitaciones"},
            {"en": "Walk to beach", "es": "A pasos de la playa"},
        ],
        "extracted_facts": {
            "year_built": 2015, "year_renovated": None, "bedrooms": 3,
            "bathrooms": None, "built_area_m2": None, "parking_spaces": None,
            "furnished": None, "has_pool": None,
        },
        "url_language": "es",
        "latlong": {"lat": 13.7, "lng": -89.2, "source": "estimated",
                    "reference": "El Tunco", "confidence": "medium"},
    }
    p.update(over)
    return p


def test_fixture_response_is_schema_valid():
    """Guard: if DEFAULT_SCHEMA evolves, the fixture must evolve too —
    apply_result's pre-condition is a validated response."""
    ok, reason = validate_response(_parsed(), DEFAULT_SCHEMA)
    assert ok, reason


# ── select_targets ──────────────────────────────────────────────────────

def test_entry_with_current_prompt_version_not_selected():
    sidecar = {"remax|123": _entry(prompt_version=PROMPT_VERSION)}
    ranked = {"remax|123": _listing()}
    targets, counters = select_targets(sidecar, ranked)
    assert targets == []
    assert counters["already_current"] == 1


def test_entry_without_prompt_version_selected():
    sidecar = {"remax|123": _entry()}  # pre-008: no prompt_version key
    ranked = {"remax|123": _listing()}
    targets, counters = select_targets(sidecar, ranked)
    assert targets == ["remax|123"]
    assert counters == {"already_current": 0, "orphaned": 0,
                        "no_source_text": 0, "malformed": 0}


def test_entry_with_older_prompt_version_selected():
    sidecar = {"remax|123": _entry(prompt_version=3)}
    ranked = {"remax|123": _listing()}
    targets, _ = select_targets(sidecar, ranked)
    assert targets == ["remax|123"]


def test_orphaned_key_not_selected():
    sidecar = {"remax|gone": _entry()}
    targets, counters = select_targets(sidecar, {})
    assert targets == []
    assert counters["orphaned"] == 1


def test_listing_without_source_text_not_selected():
    for bad_desc in (None, "", "   "):
        sidecar = {"remax|123": _entry()}
        ranked = {"remax|123": _listing(description=bad_desc)}
        targets, counters = select_targets(sidecar, ranked)
        assert targets == []
        assert counters["no_source_text"] == 1


def test_selection_is_stable_prefix_order():
    sidecar = {
        "a|1": _entry(),
        "b|2": _entry(prompt_version=PROMPT_VERSION),
        "c|3": _entry(),
    }
    ranked = {k: _listing(source=k.split("|")[0], source_id=k.split("|")[1])
              for k in sidecar}
    targets, _ = select_targets(sidecar, ranked)
    assert targets == ["a|1", "c|3"]


# ── apply_result ────────────────────────────────────────────────────────

def test_apply_preserves_geocoding_and_url_language_byte_for_byte():
    entry = _entry()
    listing = _listing()
    frozen = {k: copy.deepcopy(entry[k]) for k in (
        "lat", "lng", "geocoding_confidence", "geocoding_source",
        "geocoding_reference", "url_language")}
    old_desc = copy.deepcopy(entry["short_description_canonical"])

    apply_result(entry, listing, _parsed())

    # The response's latlong/url_language were discarded — cached values
    # survive untouched even though parsed carried different ones.
    for k, v in frozen.items():
        assert entry[k] == v, k
    assert listing["lat"] == frozen["lat"]
    assert listing["lng"] == frozen["lng"]
    # ...while the copy actually changed.
    assert entry["short_description_canonical"] != old_desc
    assert entry["short_description_canonical"]["en"] == (
        "Three-bedroom house in El Tunco, built 2015.")


def test_apply_replaces_copy_on_both_entry_and_listing_normalized():
    entry = _entry()
    listing = _listing()
    apply_result(entry, listing, _parsed())

    # Normalization strips whitespace (title fixture has padding).
    assert entry["title_canonical"] == {"en": "New House Title", "es": "Título Nuevo"}
    assert listing["title_canonical"] == entry["title_canonical"]
    assert listing["short_description_canonical"] == entry["short_description_canonical"]
    assert listing["reasons_to_buy"] == entry["reasons_to_buy"]
    assert len(entry["reasons_to_buy"]) == 3
    # Version stamps make the rewrite idempotent (re-run skips these).
    assert entry["prompt_version"] == PROMPT_VERSION
    assert entry["schema_version"] == DEFAULT_SCHEMA.schema_version


def test_facts_merge_does_not_overwrite_scraper_value():
    entry = _entry()
    listing = _listing(bedrooms=4)  # scraper-parsed value
    apply_result(entry, listing, _parsed())  # LLM says bedrooms=3

    assert listing["bedrooms"] == 4          # scraper wins
    assert listing["year_built"] == 2015     # null filled by extraction
    # The raw (sanitized) extraction is still persisted for audit.
    assert entry["extracted_facts"]["bedrooms"] == 3
    assert entry["extracted_facts"]["year_built"] == 2015


def test_facts_out_of_bounds_coerced_to_none():
    entry = _entry()
    listing = _listing()
    parsed = _parsed()
    parsed["extracted_facts"]["year_built"] = 1492   # out of bounds
    apply_result(entry, listing, parsed)

    assert entry["extracted_facts"]["year_built"] is None
    assert listing["year_built"] is None             # never filled


def test_usage_stamps_refresh_entry_metadata():
    entry = _entry()
    listing = _listing()
    usage = {"ts": "2026-06-12T00:00:00+00:00", "model": "deepseek-chat",
             "tokens_in": 1200, "tokens_out": 500, "cost_usd": 0.00091,
             "finish_reason": "stop", "latency_ms": 4200}
    apply_result(entry, listing, _parsed(), usage)
    assert entry["ts"] == usage["ts"]
    assert entry["tokens_in"] == 1200
    assert entry["cost_usd"] == 0.00091


def test_no_usage_keeps_old_metadata():
    entry = _entry()
    old_ts = entry["ts"]
    apply_result(entry, _listing(), _parsed())
    assert entry["ts"] == old_ts
