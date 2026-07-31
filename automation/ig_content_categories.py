"""ig_content_categories.py — the 7 content levers, canonical.

Sebas's "Inspiration categories v1.0": seven psychological levers, each
aimed at a different buyer. This is the strategic dimension the "paraíso"
format didn't name explicitly. It's the single source of truth that:

  * the Creative Director rotates across (so the feed never leans on one
    note) and, once attribution is live, learns which lever converts
    which audience to Free vs Pro;
  * the Copywriter writes to (tone + evidence per lever);
  * per-post code-stamping reads (the <category> in ig-d<day>-<category>);
  * the /go attribution router validates against (api/go/[code].js's
    CONTENT_CATEGORIES allow-list MUST equal SLUGS here — enforced by
    tests/test_ig_content_categories.py, the grep-contract pattern from
    email_type_contract).

Mirrors how the app already drives shelves/filters from a registry
(web/app/config/registry.ts): config, not hard-coded branches.

`default_tier` is the *starting* Free/Pro lean (top-of-funnel emotional
levers → Free; rational/credibility levers → Pro). The Growth Hacker may
later override per-audience once the /go router proves what converts — the
tier is a hypothesis, not a hardcode.
"""
from __future__ import annotations

# slug → lever definition. slug is the stable key (feeds the /go code and
# utm_term); keep it a lowercase [a-z_] token so the router regex accepts it.
CATEGORIES: dict[str, dict] = {
    "scarcity": {
        "name_es": "Escasez y urgencia",
        "name_en": "Scarcity & Urgency",
        "lever": "The window is closing — inventory shrinks, prices rise, early movers win.",
        "audience": "fence-sitters",
        "needs": "price-appreciation data",
        "default_tier": "free",
        "copy_guidance": (
            "Lead with a real, shrinking number (how few oceanfront lots remain). "
            "Create time pressure without hype; the scarcity is a fact, not a sales tactic."
        ),
    },
    "authority": {
        "name_es": "Autoridad y credibilidad",
        "name_en": "Authority & Credibility",
        "lever": "Validated, not speculative — hard data from UN, InSight Crime, World Bank.",
        "audience": "skeptics",
        "needs": "official stats",
        "default_tier": "pro",
        "copy_guidance": (
            "Cite one sourced, dated figure from the Fact Ledger and nothing else. "
            "Dry, confident, no adjectives. The number does the persuading."
        ),
    },
    "social_proof": {
        "name_es": "Prueba social",
        "name_en": "Social Proof",
        "lever": "You're not the only one — diaspora and foreign investors are already buying.",
        "audience": "hesitant buyers",
        "needs": "data + emotion",
        "default_tier": "free",
        "copy_guidance": (
            "Show the movement (who is buying, from where) with a stat, then land it "
            "emotionally: they already saw what you're still deciding on."
        ),
    },
    "aspiration": {
        "name_es": "Aspiración y estilo de vida",
        "name_en": "Aspiration & Lifestyle",
        "lever": "Sells the feeling — Sunday, 7am, the Pacific 30 metres away.",
        "audience": "emotional / local buyers",
        "needs": "cinematic photo",
        "default_tier": "free",
        "copy_guidance": (
            "Sensory, present-tense, second person. Almost no data — the hero photo "
            "carries it. Salvadoran warmth; make them feel the morning."
        ),
    },
    "investment": {
        "name_es": "Lógica de inversión",
        "name_en": "Investment Logic",
        "lever": "Capital preservation in a dollar economy — appreciation, IRR, hard assets.",
        "audience": "rational investors, diaspora",
        "needs": "financial data",
        "default_tier": "pro",
        "copy_guidance": (
            "Speak to capital, not lifestyle: dollarization, appreciation, land as a "
            "hard asset. Concrete figures from the Fact Ledger; calm, peer-to-peer tone."
        ),
    },
    "transformation": {
        "name_es": "Narrativa de transformación",
        "name_en": "Transformation Narrative",
        "lever": "The country reinvented itself — from forgotten to top emerging market.",
        "audience": "old mental models",
        "needs": "before/after macro story",
        "default_tier": "free",
        "copy_guidance": (
            "Before/after arc: the country people remember vs the data today. "
            "Reframe an outdated belief with one macro fact, then the invitation."
        ),
    },
    "education": {
        "name_es": "Educación y descubrimiento",
        "name_en": "Education & Discovery",
        "lever": "Here's how it works — buying as a foreigner, Coatepeque vs Ilopango.",
        "audience": "friction-blocked buyers",
        "needs": "Pulpo as guide",
        "default_tier": "free",
        "copy_guidance": (
            "Answer one real question a buyer is stuck on. Helpful, plain, no pressure — "
            "position Pulpo as the guide. The CTA is 'we'll show you', not 'buy now'."
        ),
    },
}

# Ordered slug list — the canonical set the router + code-stamper share.
SLUGS: list[str] = list(CATEGORIES.keys())

REQUIRED_FIELDS = (
    "name_es",
    "name_en",
    "lever",
    "audience",
    "needs",
    "default_tier",
    "copy_guidance",
)
VALID_TIERS = ("free", "pro")


def get(slug: str) -> dict | None:
    """The lever definition for a slug, or None if unknown."""
    return CATEGORIES.get(slug)


def is_valid(slug: str) -> bool:
    return slug in CATEGORIES
