"""ig_facts.py — the Fact Ledger: verified, sourced, dated stats.

Five of the seven content levers cite hard numbers (authority, investment,
social_proof, transformation, and sometimes education). This module is the
ONLY place a caption may pull a macro statistic from. No LLM ever invents a
number on a credibility post — it cites a ledger fact by id, and
`stat_violations()` is the guard that catches a stray un-sourced figure.

Every fact carries figure + source + source_url + as_of date, and — where
the number is contested — a `caveat` so the Copywriter frames it honestly
(credibility dies the moment we overstate). Bilingual statements are
ready-to-drop caption lines.

This is STABLE macro data only (safety, remittances, tourism, the dollar).
Dynamic Pulpo-inventory numbers ("139 of 1,916 are oceanfront") are
computed live from ranked.json at generation time, NOT frozen here — a
frozen inventory count would rot within a nightly.

Config-as-code, mirroring ig_content_categories.py (the proposal called it
ig_facts.json; a typed Python module is more testable and consistent).
"""
from __future__ import annotations

import re


# id → fact. `levers` lists which content categories may cite it. `number`
# is the bare figure (for the stat-trace guard); `caveat` is required framing.
FACTS: dict[str, dict] = {
    "homicide_rate_2024": {
        "number": 1.9,
        "value_es": "1.9 homicidios por cada 100 mil habitantes",
        "value_en": "1.9 homicides per 100,000",
        "statement_es": (
            "El Salvador cerró 2024 con una tasa oficial de 1.9 homicidios por cada "
            "100 mil habitantes — de las más bajas del hemisferio."
        ),
        "statement_en": (
            "El Salvador closed 2024 with an official homicide rate of 1.9 per 100,000 "
            "— among the lowest in the hemisphere."
        ),
        "source": "Gobierno de El Salvador, vía InSight Crime 2024 Homicide Round-Up",
        "source_url": "https://insightcrime.org/news/insight-crime-2024-homicide-round-up/",
        "as_of": "2024-12-31",
        "caveat": (
            "Cifra OFICIAL del gobierno; no sigue el Protocolo de Bogotá (excluye "
            "ciertas muertes). Siempre citar como 'cifra oficial' — nunca como dato neutral."
        ),
        "levers": ["authority", "social_proof", "transformation"],
    },
    "remesas_2024": {
        "number": 8.479,
        "value_es": "$8,479 millones en remesas",
        "value_en": "$8.479 billion in remittances",
        "statement_es": (
            "En 2024 los salvadoreños en el exterior enviaron $8,479 millones en "
            "remesas — 91.6% desde Estados Unidos."
        ),
        "statement_en": (
            "In 2024, Salvadorans abroad sent $8.479 billion in remittances — "
            "91.6% of it from the United States."
        ),
        "source": "Banco Central de Reserva de El Salvador (BCR)",
        "source_url": "https://estadisticas.bcr.gob.sv/serie/ingresos-mensuales-de-remesas-familiares?lang=en",
        "as_of": "2024-12-31",
        "caveat": "",
        "levers": ["investment", "social_proof", "transformation"],
    },
    "tourism_2024": {
        "number": 3.9,
        "value_es": "3.9 millones de visitantes",
        "value_en": "3.9 million visitors",
        "statement_es": (
            "El Salvador recibió un récord de 3.9 millones de visitantes en 2024, "
            "17% más que en 2023."
        ),
        "statement_en": (
            "El Salvador welcomed a record 3.9 million visitors in 2024, up 17% "
            "from 2023."
        ),
        "source": "Ministerio de Turismo / Visit El Salvador",
        "source_url": "https://www.visitelsalvador.ai/blog/record-tourisme-el-salvador-2024-4-millions",
        "as_of": "2024-12-31",
        "caveat": "",
        "levers": ["social_proof", "transformation", "aspiration"],
    },
    "dollarized_since_2001": {
        "number": 2001,
        "value_es": "economía dolarizada desde 2001",
        "value_en": "dollarized economy since 2001",
        "statement_es": (
            "El Salvador usa el dólar estadounidense desde 2001 — tu inversión no "
            "vive el riesgo cambiario de otros países de la región."
        ),
        "statement_en": (
            "El Salvador has used the US dollar since 2001 — your investment carries "
            "none of the currency risk of other countries in the region."
        ),
        "source": "Ley de Integración Monetaria (vigente desde el 1 de enero de 2001)",
        "source_url": "https://www.bcr.gob.sv/",
        "as_of": "2001-01-01",
        "caveat": "",
        "levers": ["investment", "transformation"],
    },
}

REQUIRED_FIELDS = (
    "number",
    "value_es",
    "value_en",
    "statement_es",
    "statement_en",
    "source",
    "source_url",
    "as_of",
    "levers",
)


def get(fact_id: str) -> dict | None:
    return FACTS.get(fact_id)


def for_lever(lever: str) -> list[dict]:
    """Facts a given content lever may cite (with their ids attached)."""
    return [{"id": k, **v} for k, v in FACTS.items() if lever in v["levers"]]


def all_facts() -> list[dict]:
    return [{"id": k, **v} for k, v in FACTS.items()]


# ── the stat-trace guard ───────────────────────────────────────────────
# A "macro stat" is a figure shaped like a national statistic — a percent, a
# "por cada 100 mil", a "$X millones/mil millones", a "X millones de …". These
# MUST trace to the ledger. Listing figures (price $350,000, 1,000 m², 3
# recámaras) are NOT macro stats and are exempt — they come from the listing.
_MACRO_STAT_RE = re.compile(
    r"""(
        \d[\d.,]*\s*%                                   |  # 12%, 8.2 %
        \d[\d.,]*\s*por\s+cada\s+[\d.,]+\s*mil          |  # 1.9 por cada 100 mil
        \$?\s*[\d.,]+\s*(?:mil\s+)?millones             |  # $8,479 millones / 3.9 millones
        \d[\d.,]*\s*million(?:s)?                        |  # 3.9 million
        \d[\d.,]*\s*billion                                # $8.479 billion
    )""",
    re.IGNORECASE | re.VERBOSE,
)


_DIGIT_GROUP = re.compile(r"\d[\d.,]*")


def _digit_seq(token: str) -> str:
    """A number token reduced to its bare digit sequence (separators dropped),
    so '8,479' / '8.479' / '8479' all compare equal — copy uses many forms."""
    return re.sub(r"\D", "", token)


def _ledger_digit_sequences() -> set[str]:
    """Every number that appears in the ledger's canonical COPY (statements +
    values + the bare figure), as bare digit sequences. Tracing against the
    copy — not the scaled `number` field — is what makes '$8,479 millones'
    (in a statement) trace even though `number` is 8.479 (billions)."""
    out: set[str] = set()
    for f in FACTS.values():
        blobs = [f["statement_es"], f["statement_en"], f["value_es"], f["value_en"], str(f["number"])]
        for blob in blobs:
            for tok in _DIGIT_GROUP.findall(blob):
                seq = _digit_seq(tok)
                if seq:
                    out.add(seq)
    return out


def stat_violations(caption: str) -> list[str]:
    """Macro-stat figures in `caption` that do NOT trace to the ledger's copy.
    Empty list = clean. This is the "no un-sourced numbers" guard; the
    generator cites ledger statements verbatim so it should never trip, but a
    stray LLM-invented figure (a percentage, a 'X millones') will."""
    if not caption:
        return []
    ledger = _ledger_digit_sequences()
    bad: list[str] = []
    for m in _MACRO_STAT_RE.finditer(caption):
        frag = m.group(0)
        nums = {_digit_seq(t) for t in _DIGIT_GROUP.findall(frag)}
        nums.discard("")
        # clean if every macro number in the fragment traces to the ledger
        if nums and nums <= ledger:
            continue
        bad.append(frag.strip())
    return bad
