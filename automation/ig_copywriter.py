"""ig_copywriter.py — the Copywriter: full, in-voice, lever-aware captions.

Today's ig_caption writes ONE line. The Copywriter writes the whole post —
ES caption + EN caption + first comment — shaped by the content lever
(ig_content_categories), grounded in the Fact Ledger (ig_facts) for stat
levers, and always through ig_caption_lint. The voice is the paraíso voice
codified in ig_voice_guide.md (voseo, one idea, a real number beats an
adjective, the favor-framed CTA).

Robustness contract (matches the newsletter LLM spine):
  * A DETERMINISTIC assembler produces a complete, lint-clean, voice-guide-
    compliant post with NO model call. It is both the offline/CI path AND the
    hard fallback — worst case, output is a good template, never a crash.
  * An optional LLM polish (Claude for voice, DeepSeek mechanical — routed by
    caller) refines the deterministic draft. It runs ONLY if the budget guard
    (llm_cost_guard) allows; its output must survive lint + the Fact-Ledger
    stat guard or it is discarded and the deterministic draft ships.
  * Every path is observable: ig.caption.* PostHog events on generate,
    fallback, and lint-reject.

`generate_post(listing, lever, ...)` returns a dict with both languages, the
first comment, and metadata (model used, lint_ok, facts_cited, reason).
"""
from __future__ import annotations

from typing import Callable, Optional

from automation import ig_caption_lint
from automation import ig_content_categories as cats
from automation import ig_facts

try:
    from automation import posthog_client as _ph
except Exception:  # pragma: no cover - telemetry must never block
    _ph = None

DIV = "\n\n· · ·\n\n"
CTA_ES = "pulpo.club · link en bio"
CTA_EN = "pulpo.club · link in bio"


def _emit(event: str, props: dict) -> None:
    """Fire a PostHog event; never raise (observability, not a dependency)."""
    if _ph is None:
        return
    try:
        _ph.capture(event, props)
    except Exception:  # pragma: no cover
        pass


# ── listing helpers (source-language-safe, no invented data) ───────────

def _active_country_name() -> str:
    """Fallback zone label = the active country's name, from the manifest —
    never a hardcoded country literal (check_country_hardcodes guard)."""
    try:
        from pulpo.countries import active
        return active().name_en
    except Exception:
        return ""


def _zone_label(listing: dict) -> str:
    z = (listing.get("zone") or "").replace("-", " ").strip()
    return z.title() if z else (listing.get("department") or _active_country_name())


def _price(listing: dict) -> Optional[str]:
    p = listing.get("price_usd")
    if isinstance(p, (int, float)) and p > 0:
        return f"${p:,.0f}"
    return None


def _size(listing: dict) -> Optional[str]:
    a = listing.get("area_m2")
    if isinstance(a, (int, float)) and a > 0:
        return f"{a:,.0f} m²"
    return None


def _is_coastal(listing: dict) -> bool:
    d = listing.get("dist_beach_km")
    return isinstance(d, (int, float)) and d <= 3.0


def _feature_line(listing: dict) -> str:
    """One concrete, honest detail line from listing data (never invented)."""
    bits = []
    size = _size(listing)
    if size:
        bits.append(size)
    beds = listing.get("bedrooms")
    if isinstance(beds, int) and beds > 0:
        bits.append(f"{beds} recámara" + ("s" if beds != 1 else ""))
    if _is_coastal(listing):
        bits.append("frente al mar" if (listing.get("dist_beach_km") or 9) < 0.4 else "vista al mar")
    return " · ".join(bits) if bits else _zone_label(listing)


# ── deterministic assembler (the robust core + the fallback) ───────────
# Per-lever hook + body. Each is a callable(listing, fact) -> (hook, body) in
# ES; EN mirrors. Kept short and voseo-correct; a real number/detail leads.

def _det_scarcity(listing, fact):
    zone = _zone_label(listing)
    hook_es = "La tierra frente al mar no se fabrica. Y ya casi no queda."
    body_es = (
        f"Como este terreno en {zone}: {_feature_line(listing)}.\n"
        "En Pulpo las tenemos todas juntas y rankeadas, para que veás las mejores "
        "sin revisar mil sitios."
    )
    hook_en = "Oceanfront land isn't being made — and there's barely any left."
    body_en = (
        f"Like this one in {zone}: {_feature_line(listing)}.\n"
        "At Pulpo we keep them all in one place, ranked, so you see the best "
        "without digging through a dozen sites."
    )
    return hook_es, body_es, hook_en, body_en


def _det_authority(listing, fact):
    zone = _zone_label(listing)
    hook_es = "El mundo entero volteó a ver El Salvador. Y apenas están llegando."
    body_es = (
        f"{fact['statement_es']}\n"
        f"Propiedades como esta en {zone} son las que vienen buscando. Vos ya "
        "estás aquí — llevás ventaja."
    )
    hook_en = "The whole world turned to look at El Salvador. And they're just arriving."
    body_en = (
        f"{fact['statement_en']}\n"
        f"Places like this one in {zone} are exactly what they come looking for. "
        "You're already here — you're ahead."
    )
    return hook_es, body_es, hook_en, body_en


def _det_social_proof(listing, fact):
    zone = _zone_label(listing)
    hook_es = "El mundo descubrió El Salvador. Vos naciste aquí."
    body_es = (
        f"{fact['statement_es']}\n"
        f"Gente de afuera ya está comprando su pedazo — como este en {zone}. "
        "Lo bueno se vende primero; con Pulpo lo ves antes que la fila crezca."
    )
    hook_en = "The world discovered El Salvador. You were born here."
    body_en = (
        f"{fact['statement_en']}\n"
        f"People from abroad are already buying their piece — like this one in "
        f"{zone}. The good ones sell first; with Pulpo you see them before the line grows."
    )
    return hook_es, body_es, hook_en, body_en


def _det_aspiration(listing, fact):
    zone = _zone_label(listing)
    hook_es = "Domingo, 7 de la mañana, y el Pacífico a treinta metros."
    body_es = (
        f"Así se despierta en {zone}. {_feature_line(listing).capitalize()}.\n"
        "Tu pedazo de paraíso, antes que se acabe."
    )
    hook_en = "Sunday, 7am, the Pacific thirty metres away."
    body_en = (
        f"That's waking up in {zone}. {_feature_line(listing).capitalize()}.\n"
        "Your piece of paradise, before it's gone."
    )
    return hook_es, body_es, hook_en, body_en


def _det_investment(listing, fact):
    zone = _zone_label(listing)
    price = _price(listing)
    tail_es = f" Este en {zone}: {price}." if price else f" Como este en {zone}."
    hook_es = "Un activo duro, en una economía en dólares."
    body_es = (
        f"{fact['statement_es']}\n"
        f"La tierra frente al mar no se devalúa mientras dormís.{tail_es}"
    )
    tail_en = f" This one in {zone}: {price}." if price else f" Like this one in {zone}."
    hook_en = "A hard asset, in a dollar economy."
    body_en = (
        f"{fact['statement_en']}\n"
        f"Oceanfront land doesn't lose value while you sleep.{tail_en}"
    )
    return hook_es, body_es, hook_en, body_en


def _det_transformation(listing, fact):
    hook_es = "El país que recordás no es el país de hoy."
    body_es = (
        f"{fact['statement_es']}\n"
        "De olvidado a uno de los mercados emergentes del momento. Y esto apenas "
        "empieza — mirá lo que hay disponible en Pulpo."
    )
    hook_en = "The country you remember isn't the country today."
    body_en = (
        f"{fact['statement_en']}\n"
        "From forgotten to one of the emerging markets of the moment. And this is "
        "just the start — see what's available on Pulpo."
    )
    return hook_es, body_es, hook_en, body_en


def _det_education(listing, fact):
    hook_es = "Dejá de revisar 20 sitios para encontrar tu terreno."
    body_es = (
        "Encuentra24, ReMax, grupos de Facebook, el conocido que “vende barato”… "
        "agotador.\n"
        "Pulpo junta todas las propiedades de El Salvador en un solo lugar y las "
        "ordena de mejor a peor. Vos abrís una sola página y ves lo mejor."
    )
    hook_en = "Stop checking 20 sites to find your land."
    body_en = (
        "Encuentra24, ReMax, Facebook groups, the guy who “sells cheap”… exhausting.\n"
        "Pulpo pulls every property in El Salvador into one place and ranks them "
        "best to worst. You open one page and see the best."
    )
    return hook_es, body_es, hook_en, body_en


_DETERMINISTIC = {
    "scarcity": _det_scarcity,
    "authority": _det_authority,
    "social_proof": _det_social_proof,
    "aspiration": _det_aspiration,
    "investment": _det_investment,
    "transformation": _det_transformation,
    "education": _det_education,
}

# First-comment shapes per lever (the deeper cut + hashtags).
_HASHTAGS = "#ElSalvador #BienesRaices #SurfCity #TuPedazoDeParaiso #PulpoClub"


def _comment(lever: str, fact: Optional[dict]) -> tuple[str, str]:
    if fact and lever in ("authority", "investment", "social_proof", "transformation"):
        es = f"Fuente: {fact['source']}.\n\nRankeadas. El Top 10 en tu correo cada domingo.\n\n{_HASHTAGS}"
        en = f"Source: {fact['source']}.\n\nRanked. The Top 10 in your inbox every Sunday.\n\n{_HASHTAGS}"
    else:
        es = f"Comparamos cada propiedad por precio, zona y acceso y te mostramos solo las mejores.\n\nRankeadas. El Top 10 en tu correo cada domingo.\n\n{_HASHTAGS}"
        en = f"We compare every property by price, location and access and show you only the best.\n\nRanked. The Top 10 in your inbox every Sunday.\n\n{_HASHTAGS}"
    return es, en


def _assemble(hook: str, body: str, cta: str) -> str:
    return f"**{hook}**\n\n{body}\n\n{cta}"


def _pick_fact(lever: str) -> Optional[dict]:
    pool = ig_facts.for_lever(lever)
    return pool[0] if pool else None


def build_deterministic(listing: dict, lever: str) -> dict:
    """The always-available, lint-clean, voice-guide-compliant post."""
    fn = _DETERMINISTIC[lever]
    fact = _pick_fact(lever)
    hook_es, body_es, hook_en, body_en = fn(listing, fact)
    cap_es = _assemble(hook_es, body_es, CTA_ES)
    cap_en = _assemble(hook_en, body_en, CTA_EN)
    com_es, com_en = _comment(lever, fact)
    return {
        "caption_es": cap_es,
        "caption_en": cap_en,
        "comment_es": com_es,
        "comment_en": com_en,
        "facts_cited": [fact["id"]] if fact else [],
    }


# ── lint + fact validation ─────────────────────────────────────────────

def _validate(post: dict) -> list[str]:
    """Lint + Fact-Ledger stat guard across both languages. [] = clean."""
    problems: list[str] = []
    for key in ("caption_es", "caption_en", "comment_es", "comment_en"):
        text = post.get(key, "")
        for v in ig_caption_lint.check(text):
            problems.append(f"{key}:{v.get('code')}:{v.get('matched')}")
        for stat in ig_facts.stat_violations(text):
            problems.append(f"{key}:UNSOURCED_STAT:{stat}")
        for banned in ig_facts.mentions_banned_topic(text):
            problems.append(f"{key}:BANNED_TOPIC:{banned}")
    return problems


# ── public entry ───────────────────────────────────────────────────────

def generate_post(
    listing: dict,
    lever: str,
    *,
    tier: Optional[str] = None,
    llm_polish: Optional[Callable[[dict, dict, dict], Optional[dict]]] = None,
) -> dict:
    """Full in-voice post for a listing under a content lever.

    llm_polish(deterministic_post, listing, lever_def) -> refined_post|None is
    the optional model hook (Claude/DeepSeek, wired by the caller so this module
    stays offline-testable). Its output is used ONLY if it survives lint + the
    stat guard; otherwise the deterministic draft ships. Always returns a valid,
    lint-clean post.
    """
    lever_def = cats.get(lever)
    if lever_def is None:
        raise ValueError(f"unknown lever {lever!r}; valid: {cats.SLUGS}")
    tier = tier or lever_def["default_tier"]

    det = build_deterministic(listing, lever)
    det_problems = _validate(det)
    # The deterministic path is authored clean; a violation here is a real bug
    # we want surfaced, not silently shipped.
    assert not det_problems, f"deterministic caption failed its own lint: {det_problems}"

    model = "deterministic"
    fallback_reason = None
    post = det

    if llm_polish is not None:
        try:
            refined = llm_polish(det, listing, lever_def)
        except Exception as e:  # soft-fail: any model error → deterministic
            refined, fallback_reason = None, f"llm_error:{type(e).__name__}"
        if refined:
            problems = _validate(refined)
            if problems:
                fallback_reason = "lint_reject"
                _emit("ig.caption.lint_rejected", {"lever": lever, "model": "llm", "violations": problems[:5]})
            else:
                post = {**det, **refined}  # keep facts_cited etc. unless overridden
                model = refined.get("model", "llm")
        else:
            fallback_reason = fallback_reason or "llm_empty"

    if model == "deterministic" and fallback_reason:
        _emit("ig.caption.fallback_used", {"lever": lever, "reason": fallback_reason})

    result = {
        **post,
        "lever": lever,
        "tier": tier,
        "model": model,
        "lint_ok": True,
        "fallback_reason": fallback_reason,
    }
    _emit("ig.caption.generated", {
        "lever": lever, "tier": tier, "model": model,
        "facts_cited": result.get("facts_cited", []),
        "chars_es": len(result["caption_es"]),
    })
    return result


# ── wire-format helpers (bilingual caption + comment on one field) ──────

def wire_caption(post: dict) -> str:
    """ES then EN joined by the divider — the single Instagram caption field."""
    return f"{post['caption_es']}{DIV}{post['caption_en']}"


def wire_comment(post: dict) -> str:
    return f"{post['comment_es']}{DIV}{post['comment_en']}"
