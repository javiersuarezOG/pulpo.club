"""Post-generation quality lint for LLM descriptions — plan 008.

NOT a fail-closed gate: a banned-phrase hit logs + counts, it does not
reject the response (rejecting would re-spend the API call for a tone
issue). Consumers: the per-listing JSONL log event in
automation/llm_enrichment.py (quality_flags key), the metrics dict's
quality_flagged counter, and scripts/retrofit_descriptions.py's
before/after report (plan 011). tests/test_description_lint.py is the
contract test.

The banned-phrase list is intentionally duplicated between the v4
prompt text (automation/llm_enrichment_prompts.py — model instruction)
and this module (measurement); when adding a phrase, add it to both.
"""
from __future__ import annotations

# Closed set, lowercase. EN + ES. Each entry is a phrase that appeared in
# >=1% of the 2026-06-12 corpus audit and is banned by the v4 prompt.
BANNED_PHRASES: tuple[str, ...] = (
    "discover", "dream home", "don't miss", "paradise", "oasis",
    "stunning", "breathtaking", "exceptional opportunity", "hidden gem",
    "perfect canvas", "tranquil", "unparalleled", "prime location",
    "your vision",
    "descubra", "hogar soñado", "no pierda", "paraíso",
    "impresionante", "oportunidad excepcional", "joya escondida",
    "lienzo perfecto", "incomparable",
)


def lint_description(text: str | None) -> list[str]:
    """Return the banned phrases found in *text* (case-insensitive).
    Empty list = clean. None/empty input = clean."""
    if not text:
        return []
    low = text.lower()
    return [p for p in BANNED_PHRASES if p in low]
