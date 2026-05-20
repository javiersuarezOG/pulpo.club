"""Enforce the Privacy Policy's DeepSeek attestation.

The live Privacy Policy at web/app/config/legal-content.ts says:

    "DeepSeek (China) — Listing-text enrichment. Receives listing text
    only; no user-identifiable data is transmitted."

This file makes that claim true-by-construction. If a future refactor
adds a pulpo-user-identifying field to the DeepSeek call path, these
tests fail before the change ships. The Privacy Policy stops being
aspirational.

Threat model — what counts as "user-identifiable":

    Pulpo USER data (the thing we promise not to send):
      - Clerk user IDs (`user_<id>`)
      - Clerk org IDs (`org_<id>`)
      - Clerk session IDs (`sess_<id>`)
      - Stripe customer IDs (`cus_<id>`)
      - Stripe subscription IDs (`sub_<id>`)
      - Stripe payment-intent / checkout-session / invoice IDs
      - Pulpo-internal PostHog distinct IDs (`email:<16-hex>`)
      - Auth tokens (sk_*, pk_*, whsec_*)

    NOT in-scope:
      - Emails that appear in scraped listing text (a broker's email
        on a Zonaprop listing is not "Pulpo user data" — it's third-
        party content that came in via the scraper). We do not promise
        to redact those.
      - Phone numbers in listing copy (same reasoning).

Defense surface — three layers:

    1. The static system prompt has zero user-identifying tokens.
    2. The render_user_prompt() function signature accepts ONLY
       listing-level fields (description + geographic hints). No
       refactor can sneak a `clerk_user_id=` parameter through.
    3. Given a deliberately-malicious description containing fake
       Stripe/Clerk IDs, the rendered prompt is non-amplifying — it
       contains the same tokens as the input and no others. Catches
       the case where someone adds a "user_context" interpolation to
       the template later.
"""
from __future__ import annotations

import inspect
import re

import pytest

from automation.llm_enrichment_prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    LOCATION_HINTS_TEMPLATE,
    render_user_prompt,
)


# Pulpo-user-identifying token patterns. Keep this list synchronized
# with the threat model in the docstring. If a future PR adds a new
# identifier scheme, add the regex here too — the test will start
# catching it everywhere it shouldn't appear.
USER_IDENTIFIER_PATTERNS = {
    "clerk_user_id":         re.compile(r"\buser_[A-Za-z0-9]{8,}"),
    "clerk_org_id":          re.compile(r"\borg_[A-Za-z0-9]{8,}"),
    "clerk_session_id":      re.compile(r"\bsess_[A-Za-z0-9]{8,}"),
    "stripe_customer_id":    re.compile(r"\bcus_[A-Za-z0-9]{8,}"),
    "stripe_subscription_id": re.compile(r"\bsub_[A-Za-z0-9]{8,}"),
    "stripe_payment_intent": re.compile(r"\bpi_[A-Za-z0-9]{8,}"),
    "stripe_checkout_session": re.compile(r"\bcs_(?:test|live)_[A-Za-z0-9]{8,}"),
    "stripe_invoice":        re.compile(r"\bin_[A-Za-z0-9]{8,}"),
    "stripe_secret_key":     re.compile(r"\bsk_(?:test|live)_[A-Za-z0-9]{8,}"),
    "stripe_publishable_key": re.compile(r"\bpk_(?:test|live)_[A-Za-z0-9]{8,}"),
    "stripe_webhook_secret": re.compile(r"\bwhsec_[A-Za-z0-9]{8,}"),
    "posthog_email_distinct_id": re.compile(r"\bemail:[0-9a-f]{16}\b"),
}


def assert_no_user_identifiers(text: str, *, where: str) -> None:
    """Fail the test if any user-identifying pattern matches in `text`.

    The failure message names the pattern and the matched substring so
    a future engineer who breaks the contract gets a one-line
    explanation of which guard fired.
    """
    matches: list[tuple[str, str]] = []
    for name, rx in USER_IDENTIFIER_PATTERNS.items():
        for m in rx.finditer(text):
            matches.append((name, m.group(0)))
    assert not matches, (
        f"Privacy-policy violation: {where} contains user-identifying "
        f"tokens: {matches}\n"
        f"The DeepSeek attestation promises 'no user-identifiable data "
        f"is transmitted.' Adding any of the patterns above breaks that "
        f"claim. If this is intentional (e.g. a deliberate refactor to "
        f"include a user field), update legal-content.ts AND remove the "
        f"failing pattern from USER_IDENTIFIER_PATTERNS here."
    )


# ── Layer 1: the static system prompt is clean ─────────────────────────

def test_system_prompt_has_no_user_identifiers():
    """The SYSTEM_PROMPT is byte-stable + rendered once at import time.

    Any user-identifying token here would be sent on every DeepSeek call
    forever. Static prompts are the highest-risk surface for accidental
    PII inclusion (a copy-pasted debug ID lingering after a fix).
    """
    assert_no_user_identifiers(SYSTEM_PROMPT, where="SYSTEM_PROMPT")


def test_user_prompt_template_has_no_user_identifiers():
    """The USER_PROMPT_TEMPLATE itself (before substitution) must not
    bake any user-identifying tokens into the format string."""
    assert_no_user_identifiers(USER_PROMPT_TEMPLATE, where="USER_PROMPT_TEMPLATE")


def test_location_hints_template_has_no_user_identifiers():
    """Same guard for the LOCATION_HINTS sub-template."""
    assert_no_user_identifiers(
        LOCATION_HINTS_TEMPLATE, where="LOCATION_HINTS_TEMPLATE"
    )


# ── Layer 2: function signature enforces listing-level fields only ─────

def test_render_user_prompt_accepts_only_listing_level_fields():
    """The render_user_prompt() signature is the structural guarantee:
    no `clerk_user_id`, `email`, or any pulpo-user field can be passed
    in unless the signature changes — which would trip this test.

    Pinning the parameter NAMES (not just types) catches refactors that
    rename `original_description` to `user_text` or similar.
    """
    sig = inspect.signature(render_user_prompt)
    parameter_names = list(sig.parameters.keys())

    expected = {
        "original_description",
        "location_text",
        "municipality",
        "department",
        "country",
    }
    actual = set(parameter_names)

    # Every parameter must be one of the listing-level fields. If a new
    # one shows up, this test fails — the engineer adding it must either
    # (a) confirm it's listing-level and add it to `expected` here, or
    # (b) reconsider whether DeepSeek should see it at all.
    forbidden = actual - expected
    assert not forbidden, (
        f"render_user_prompt accepted a new parameter not in the listing-"
        f"level allowlist: {sorted(forbidden)}. The Privacy Policy promises "
        f"DeepSeek receives listing text only — review whether the new "
        f"parameter is user-identifying before extending `expected` in "
        f"this test."
    )


# ── Layer 3: representative renders are clean + non-amplifying ─────────

CLEAN_LISTING_FIXTURES = [
    # Minimal description, no location.
    {"original_description": "Beachfront lot, 1200 m², ocean view."},
    # Spanish description, full geographic hints.
    {
        "original_description": (
            "Terreno frente al mar en Playa El Tunco. 800 m². Acceso "
            "directo a la playa, palmeras, vista panorámica."
        ),
        "location_text": "Playa El Tunco",
        "municipality": "Tamanique",
        "department": "La Libertad",
        "country": "El Salvador",
    },
    # Mixed-language with a broker phone in the source (a legitimately
    # third-party PII type that's NOT in scope for this attestation).
    {
        "original_description": (
            "Lake-view home with infinity pool. 3BR / 2BA. Llamar al "
            "+503 7777-8888 para coordinar visita."
        ),
        "location_text": "Lago de Coatepeque",
    },
    # Empty description — boundary case.
    {"original_description": ""},
    {"original_description": None},
]


@pytest.mark.parametrize("fixture", CLEAN_LISTING_FIXTURES)
def test_clean_listings_render_without_pulpo_user_identifiers(fixture):
    """Every realistic listing renders a prompt that contains zero
    Pulpo-user-identifying tokens, regardless of source content or
    locale."""
    rendered = render_user_prompt(**fixture)
    assert_no_user_identifiers(rendered, where=f"rendered prompt for {fixture!r}")


def test_render_user_prompt_is_non_amplifying():
    """If a scraped listing somehow contains a string that LOOKS like a
    pulpo user identifier (e.g. a Reddit user ID quoted in the listing
    description), the prompt builder must NOT add any *new* identifiers
    on top. Catches a future change that injects something like
    `f"caller={user_id}"` into the template.

    We seed the input with one tokenizable lookalike string per category
    and assert the output contains EXACTLY that set, not more.
    """
    seeded_input = (
        "Saw this listing posted by user_abcd1234efgh and forwarded by "
        "broker on stripe sub_demoNOTREAL5678 — they paid via "
        "cus_demoNOTREAL9999. Reference: sess_demoNOTREAL0000."
    )
    rendered = render_user_prompt(seeded_input)

    # For each pattern category, the rendered output must contain the
    # SAME set of matches as the input (i.e. just propagation, no
    # amplification). If amplification ever happens, the assertion
    # message tells the engineer which category grew.
    for name, rx in USER_IDENTIFIER_PATTERNS.items():
        in_input = set(rx.findall(seeded_input))
        in_output = set(rx.findall(rendered))
        added = in_output - in_input
        assert not added, (
            f"render_user_prompt added new {name} tokens not present in "
            f"the input: {sorted(added)}. The prompt template must only "
            f"propagate description content, never synthesize new "
            f"identifier-looking strings."
        )
