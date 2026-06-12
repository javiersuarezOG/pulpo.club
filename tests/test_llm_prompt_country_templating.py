"""PR-MC-2 — LLM enrichment SYSTEM_PROMPT is country-templated.

The DeepSeek single-call prompt used to hardcode "El Salvador" + a
fixed SV beach reference table. After PR-MC-2 it renders from the
active country's manifest. Tests below assert:

  1. The default-active SV prompt still mentions "El Salvador" and
     carries the SV beach reference table (no regression for the live
     deployment).
  2. A synthetic GT manifest's prompt mentions "Guatemala" and does
     NOT mention "El Salvador" — i.e. swapping countries swaps the
     prompt cleanly with no SV leakage.
  3. The structural invariants the existing prompt relies on (JSON
     contract, Step A–D structure, COASTAL / WALKING-DISTANCE cue
     vocabulary, "Output must be valid JSON only") are preserved on
     both prompts so the model behavior contract doesn't drift.
  4. A partial manifest with no traditional_units or named_beaches
     produces a prompt that's still well-formed (units rule collapses
     out cleanly; beach block reports "no authoritative beach
     coordinates configured").
"""
from __future__ import annotations

from pulpo.countries import CountryManifest, load
from automation.llm_enrichment_prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    system_prompt_for,
)


# ── Structural invariants (apply to every country's prompt) ──────────


_REQUIRED_PHRASES = (
    # JSON contract
    '"title": { "en": "string", "es": "string" }',
    '"description": { "en": "string", "es": "string" }',
    '"usps": [',
    '"url_language": "en or es or mixed"',
    '"latlong":',
    "Output must be valid JSON only",
    # Inference-step framing
    "Step A.",
    "Step B.",
    "Step C.",
    "Step D.",
    # Coastal-cue vocabulary
    "frente al mar",
    "beachfront",
    "AUTHORITATIVE BEACH COORDINATES",
    # Quality-rule preamble
    "Quality rules",
)


def _assert_structural_invariants(prompt: str, ctx: str) -> None:
    for phrase in _REQUIRED_PHRASES:
        assert phrase in prompt, (
            f"[{ctx}] SYSTEM_PROMPT missing required phrase {phrase!r}; "
            f"prompt template may have drifted."
        )


# ── SV: live, default-active behaviour ───────────────────────────────


def test_sv_prompt_mentions_el_salvador():
    sv = load("SV")
    prompt = system_prompt_for(sv)
    assert "El Salvador" in prompt, (
        "SV prompt must address the model as an analyst "
        "'writing listing summaries for buyers in El Salvador'."
    )
    # Specifically the country-templated slots. The "Assume the property
    # is in <country>." sentence wraps across a line in the rendered
    # prompt; we normalize whitespace before matching to be robust.
    normalized = " ".join(prompt.split())
    assert "writing listing summaries for buyers in El Salvador" in normalized
    assert "Assume the property is in El Salvador." in normalized
    assert "El Salvador centroid" in normalized


def test_sv_prompt_includes_traditional_units_rule():
    sv = load("SV")
    prompt = system_prompt_for(sv)
    # SV manifest carries Salvadoran demonym + manzanas + varas
    assert "Salvadoran traditional units" in prompt
    assert "manzanas" in prompt
    assert "varas" in prompt


def test_sv_prompt_carries_beach_reference_block():
    sv = load("SV")
    prompt = system_prompt_for(sv)
    # Spot-check a handful of high-traffic SV beaches
    for name in ("El Tunco", "El Zonte", "El Cuco", "Conchagua"):
        assert name in prompt, (
            f"SV prompt missing named beach {name!r}. Beach reference "
            f"may not be rendering from the manifest."
        )


def test_module_level_system_prompt_matches_active_country():
    """The module-level SYSTEM_PROMPT constant is the active country's
    prompt computed at import time. Should equal system_prompt_for(SV)
    when PULPO_ACTIVE_COUNTRY is unset (default SV).
    """
    sv = load("SV")
    assert SYSTEM_PROMPT == system_prompt_for(sv)


def test_sv_prompt_passes_structural_invariants():
    sv = load("SV")
    _assert_structural_invariants(system_prompt_for(sv), ctx="SV")


# ── GT: synthetic alt-country isolation ──────────────────────────────


def _synthetic_gt_manifest() -> CountryManifest:
    """Build an in-memory GT manifest (no on-disk file) to verify the
    prompt re-templates cleanly per country. Used because shipping a
    full GT manifest is out-of-scope for PR-MC-2 — that lands later
    with the first GT scraper.
    """
    return CountryManifest.from_dict({
        "code": "GT",
        "name_en": "Guatemala",
        "name_es": "Guatemala",
        "name_adjective_en": "Guatemalan",
        "locale_es": "es-GT",
        "locale_en": "en-US",
        "currency": "GTQ",
        "centroid_lat": 15.7835,
        "centroid_lng": -90.2308,
        "traditional_units": ["cuerdas", "caballerías"],
        "named_beaches": [
            ["Monterrico", 13.8833, -90.4667],
            ["Playa Champerico", 14.3000, -91.9167],
        ],
    })


def test_gt_synthetic_prompt_mentions_guatemala_not_el_salvador():
    gt = _synthetic_gt_manifest()
    prompt = system_prompt_for(gt)
    normalized = " ".join(prompt.split())
    # GT-side
    assert "writing listing summaries for buyers in Guatemala" in normalized
    assert "Assume the property is in Guatemala." in normalized
    assert "Guatemala centroid" in normalized
    # No SV leakage. NB: "El Salvador" check has to be on the raw
    # prompt — line breaks don't hide the words individually anyway.
    assert "El Salvador" not in prompt, (
        "GT prompt must not mention El Salvador. Found a leak — the "
        "templating is dropping a hardcoded SV reference somewhere."
    )
    assert "Salvadoran" not in prompt
    assert "manzanas" not in prompt, (
        "GT prompt carries SV's manzanas in the traditional-units rule. "
        "Should be GT's cuerdas + caballerías."
    )


def test_gt_synthetic_prompt_uses_gt_units_and_demonym():
    gt = _synthetic_gt_manifest()
    prompt = system_prompt_for(gt)
    assert "Guatemalan traditional units" in prompt
    assert "cuerdas" in prompt
    assert "caballerías" in prompt


def test_gt_synthetic_prompt_carries_gt_beach_table_only():
    gt = _synthetic_gt_manifest()
    prompt = system_prompt_for(gt)
    assert "Monterrico" in prompt
    assert "Playa Champerico" in prompt
    # No SV beaches leaking
    for sv_beach in ("El Tunco", "El Zonte", "Conchagua"):
        assert sv_beach not in prompt, (
            f"GT prompt leaked SV beach {sv_beach!r}. Beach reference "
            f"is not reading from the per-country manifest."
        )


def test_gt_synthetic_prompt_passes_structural_invariants():
    gt = _synthetic_gt_manifest()
    _assert_structural_invariants(system_prompt_for(gt), ctx="GT")


# ── Prompt v4: to-the-point factual contract (plan 008) ──────────────


def test_prompt_version_is_4():
    """Plan 011's retroactive backfill keys off prompt_version < 4.
    Any future prompt-content change must bump this again."""
    assert PROMPT_VERSION == 4


def test_v4_description_rule_is_short_and_factual():
    """The v4 description contract: 60-word cap present, the v3
    marketing-copy rule gone."""
    assert "MAX 60 words" in SYSTEM_PROMPT
    assert "optimized commercial description" not in SYSTEM_PROMPT


def test_v4_prompt_has_no_land_description_header():
    """Houses and condos go through the same prompt — the old
    LAND DESCRIPTION framing is banned everywhere in the module."""
    from automation import llm_enrichment_prompts as mod
    import inspect
    source = inspect.getsource(mod)
    assert "LAND DESCRIPTION" not in source
    assert "PROPERTY LISTING:" in source


# ── Partial manifests degrade cleanly ────────────────────────────────


def test_minimal_manifest_collapses_units_rule():
    """A country with no traditional_units configured should produce a
    prompt with the units bullet omitted entirely — no malformed
    "Salvadoran traditional units ()" / empty-bullet artifact.
    """
    minimal = CountryManifest.from_dict({
        "code": "ZZ",
        "name_en": "Testland",
        "name_es": "Tierra de Prueba",
        "locale_es": "es-ZZ",
        "locale_en": "en-US",
        "currency": "USD",
        "centroid_lat": 0.0,
        "centroid_lng": 0.0,
        # No traditional_units; no named_beaches
    })
    prompt = system_prompt_for(minimal)
    assert "traditional units" not in prompt
    # Beach reference still renders the placeholder line so the
    # structural template is preserved
    assert "AUTHORITATIVE BEACH COORDINATES" in prompt
    assert "no authoritative beach coordinates configured" in prompt
    # Structural invariants still hold
    _assert_structural_invariants(prompt, ctx="minimal")


def test_minimal_manifest_uses_country_name_for_demonym_fallback():
    """When name_adjective_en is absent the prompt's demonym slot
    falls back to name_en (CountryManifest.name_adjective_en()).
    The units rule is conditional on traditional_units, so a minimal
    manifest with units but no demonym still renders cleanly.
    """
    payload = {
        "code": "ZZ",
        "name_en": "Testland",
        "name_es": "Tierra de Prueba",
        "locale_es": "es-ZZ",
        "locale_en": "en-US",
        "currency": "USD",
        "centroid_lat": 0.0,
        "centroid_lng": 0.0,
        "traditional_units": ["whatevers"],
    }
    manifest = CountryManifest.from_dict(payload)
    prompt = system_prompt_for(manifest)
    # Falls back to "Testland" since no adjective was provided
    assert "Testland traditional units" in prompt
    assert "whatevers" in prompt
