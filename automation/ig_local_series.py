"""ig_local_series.py — local-voice content engine for the IG autopilot.

Turns a real listing (candidate + ranked listing + already-downloaded photo
paths) into a complete carousel post — slide specs for
``automation/ig_campaign_poster.py``, a caption, and a first comment — in a
Salvadoran voice, so the self-running feed reads like a chero who knows
where the good land is, not a brand explaining a tool.

Three rotating formats:

  - ``guess``       ¿Cuánto cuesta? — the price is HIDDEN on the cover and
                    REVEALED on the last slide. Built to make people drop a
                    number in the comments (early velocity = reach). The
                    flywheel; weighted 2× in the rotation.
  - ``numero_uno``  El #1 de la semana — the ranker as authority
                    ("sin cuñados, sin paja, solo datos").
  - ``regreso``     Para cuando regresés — the diaspora format. Ships per
                    Javier's 2026-07-24 override of the diaspora half of
                    Sebastian's caption brief (see automation/
                    ig_caption_lint.py). Written warm, not tag-your-cousin.

Rotation is deterministic by post index (see ``FORMAT_ROTATION``) so the
feed stays varied AND the admin console can always show what the next three
posts will be. **Pure functions only** — no I/O, no network, no rendering.
The autopilot downloads the photos and renders the slides; this module only
decides what each post SAYS and SHOWS. Every caption + comment is designed
to pass ``ig_caption_lint.check`` (no listing-speak, no ``!!``, ≤2
back-to-back emoji).
"""
from __future__ import annotations

from typing import Callable, Optional

from automation.ig_units import (
    format_area_m2,
    format_distance,
    format_price_per_m2,
    format_price_usd,
)
from pulpo.countries import active as _active_country

_COUNTRY = _active_country().name_en
_C = _COUNTRY.replace(" ", "")

# The rotation. ``guess`` appears twice per cycle — it's the engagement
# flywheel, so we lead with it more often than the other two.
FORMAT_ROTATION: tuple[str, ...] = ("guess", "numero_uno", "guess", "regreso")

# Minimum usable listing photos each format needs (the autopilot skips a
# listing that can't yield this many and tries the next one).
_MIN_PHOTOS = {"guess": 2, "numero_uno": 2, "regreso": 1}


# ── category → color + ribbon (mirrors ig_campaign_poster.CATEGORY_COLORS)
#
# The listing's property_type + beach proximity choose the ribbon label and
# the slide color. Kept in sync with the category color keys the campaign
# poster already knows.

def _near_beach(candidate: dict) -> bool:
    d = candidate.get("dist_beach_km")
    return d is not None and d <= 3.0


def category(candidate: dict) -> tuple[str, str, str]:
    """Return (color_key, ribbon_label, noun) for a candidate.

    color_key indexes ig_campaign_poster.CATEGORY_COLORS; ribbon_label is
    the ES pill text; noun is the ES category noun used in prose."""
    pt = (candidate.get("property_type") or "").lower()
    near = _near_beach(candidate)
    if pt == "condo":
        return "apartamentos", "APARTAMENTO", "apartamento"
    if pt == "house":
        return ("casas_playa", "CASA DE PLAYA" if near else "CASA",
                "casa de playa" if near else "casa")
    # land / default
    return ("terrenos_playa", "TERRENO DE PLAYA" if near else "TERRENO",
            "terreno de playa" if near else "terreno")


def _zone_title(zone: Optional[str]) -> str:
    """"el-tunco" → "El Tunco"."""
    if not zone:
        return _COUNTRY
    return " ".join(w.capitalize() for w in str(zone).replace("_", "-").split("-"))


def _zone_hashtag(zone: Optional[str]) -> str:
    if not zone:
        return ""
    return "#" + "".join(w.capitalize() for w in str(zone).replace("_", "-").split("-"))


def _dist_phrase(candidate: dict) -> Optional[str]:
    d = candidate.get("dist_beach_km")
    if d is None:
        return None
    if d <= 0.05:
        return "Frente al mar."
    return f"A {format_distance(d)} del mar."


def _value_line(candidate: dict) -> str:
    """One honest reason the listing is worth a look — prefers the
    below-zone-price signal, falls back to distance, then price/m²."""
    pct = candidate.get("price_vs_zone_pct")
    if isinstance(pct, (int, float)) and pct <= -8:
        return f"{abs(round(pct))}% bajo el precio de la zona."
    dist = _dist_phrase(candidate)
    if dist:
        return dist
    ppm = candidate.get("price_per_m2")
    if ppm is not None:
        return f"{format_price_per_m2(ppm)} — de los mejores de la zona."
    return "De los mejores de la zona, comparado contra todo el mercado."


# ── first-comment hashtags (discovery lives in the comment, not caption) ─

_CORE_HASHTAGS: tuple[str, ...] = (
    f"#{_C}", "#BienesRaices", f"#TerrenosEn{_C}", "#SurfCity",
    f"#PlayasDe{_C}", "#SalvadorenosPorElMundo", "#TuPedazoDeParaiso",
)


def _hashtags(candidate: dict) -> str:
    tags = list(_CORE_HASHTAGS)
    zt = _zone_hashtag(candidate.get("zone"))
    if zt and zt not in tags:
        tags.insert(4, zt)
    return " ".join(tags)


# ── format builders ─────────────────────────────────────────────────────
#
# Each returns a Post dict:
#   {format, color_key, slides:[spec,...], caption, comment}
# `slides` specs feed ig_campaign_poster.build_slide_html directly; photo
# slides carry `img` = a local path the autopilot already prepared.


def _guess(candidate: dict, listing: dict, photos: list[str]) -> dict:
    color_key, ribbon, _noun = category(candidate)
    zone = _zone_title(candidate.get("zone"))
    area = format_area_m2(candidate.get("area_m2"))
    price = format_price_usd(candidate.get("price_usd"))
    value = _value_line(candidate)

    slides = [{
        "t": "guess", "img": photos[0], "ribbon": ribbon,
        "hook": "¿Cuánto\ncuesta?", "sub": f"{area} en {zone}.\nAdiviná 👇",
    }]
    if len(photos) >= 3:
        slides.append({
            "t": "photo", "img": photos[1], "ribbon": ribbon,
            "badge": f"{zone} · {area}",
        })
        reveal_img = photos[2]
    else:
        reveal_img = photos[1]
    slides.append({
        "t": "reveal", "img": reveal_img, "ribbon": ribbon,
        "kicker": "¿Le atinaste?", "price": price,
    })

    caption = (
        f"**{zone}. {area}. ¿Cuánto creés que vale?**\n\n"
        "Tirá tu número en los comentarios antes de deslizar. Sin googlear.\n\n"
        "· · ·\n\n"
        f"{price}. {value}\n\n"
        "¿Muy caro o muy barato? Lo comparamos contra todo el mercado del país "
        "y sale de los mejores.\n\n"
        "pulpo.club · link en bio"
    )
    comment = (
        "¿Le atinaste? Tirá tu número 👇\n\n"
        "Comparamos cada propiedad por precio, zona y acceso, y te mostramos "
        "solo las mejores. El Top 10 en tu correo cada domingo.\n"
        "pulpo.club\n\n"
        f"{_hashtags(candidate)}"
    )
    return {"format": "guess", "color_key": color_key,
            "slides": slides, "caption": caption, "comment": comment}


def _numero_uno(candidate: dict, listing: dict, photos: list[str]) -> dict:
    color_key, ribbon, noun = category(candidate)
    zone = _zone_title(candidate.get("zone"))
    price = format_price_usd(candidate.get("price_usd"))
    value = _value_line(candidate)

    slides = [
        {"t": "statement", "eyebrow": "EL #1 DE LA SEMANA",
         "l1": f"La mejor {noun}", "l2": f"de {_COUNTRY}.",
         "punch": "Según los datos, no según un cuñado."},
        {"t": "photo", "img": photos[0], "ribbon": ribbon, "star": True,
         "badge": f"{price} · {zone}"},
        {"t": "photo", "img": photos[1], "ribbon": ribbon,
         "badge": "Ver el Top 10 → pulpo.club"},
    ]
    caption = (
        f"**El #1 de esta semana: {zone}.**\n\n"
        f"Cada semana comparamos todas las propiedades del país y las ordenamos "
        "de mejor a peor. Sin cuñados, sin paja, solo datos.\n\n"
        f"Por qué está en el #1: {value}\n\n"
        "¿Vos en cuál te quedás — playa o lago? El Top 10 completo, cada domingo "
        "en tu correo.\n\n"
        "pulpo.club · link en bio"
    )
    comment = (
        "Así rankeamos: precio, zona y acceso, cada propiedad del país, "
        "cada semana. Vos ves solo lo mejor.\n"
        "El Top 10 en tu correo cada domingo 👉 pulpo.club\n\n"
        f"{_hashtags(candidate)}"
    )
    return {"format": "numero_uno", "color_key": color_key,
            "slides": slides, "caption": caption, "comment": comment}


def _regreso(candidate: dict, listing: dict, photos: list[str]) -> dict:
    # Diaspora format — warm, not tag-your-cousin. Uses a coastal color.
    color_key, ribbon, _noun = category(candidate)
    zone = _zone_title(candidate.get("zone"))
    price = format_price_usd(candidate.get("price_usd"))

    slides = [
        {"t": "statement", "eyebrow": "PARA CUANDO REGRESÉS",
         "l1": "Un pedazo de", "l2": "tu país.",
         "punch": "Te lo estamos guardando."},
        {"t": "photo", "img": photos[0], "ribbon": ribbon,
         "badge": f"{zone} · {price}"},
        {"t": "cta", "big": "Tu pedazo\nde paraíso", "sub": "pulpo.club · link en bio"},
    ]
    caption = (
        "**Para el salvadoreño que anda lejos y un día quiere volver.**\n\n"
        f"Un pedazo de {zone} — para los findes, para la familia, para tener algo "
        "que de verdad es tuyo aquí. No es sueño, es un link.\n\n"
        "· · ·\n\n"
        "*For the Salvadoran living abroad who dreams of coming home. Your piece "
        "of the coast is one link away.*\n\n"
        "pulpo.club · link en bio"
    )
    comment = (
        "Todas las propiedades del país, rankeadas por valor, en un solo lugar. "
        "Desde donde estés.\n"
        "pulpo.club\n\n"
        f"{_hashtags(candidate)}"
    )
    return {"format": "regreso", "color_key": color_key,
            "slides": slides, "caption": caption, "comment": comment}


_BUILDERS: dict[str, Callable[[dict, dict, list], dict]] = {
    "guess": _guess, "numero_uno": _numero_uno, "regreso": _regreso,
}


# ── public API ───────────────────────────────────────────────────────────

def format_for_index(post_index: int) -> str:
    """The format the Nth autopilot post should use (deterministic)."""
    return FORMAT_ROTATION[post_index % len(FORMAT_ROTATION)]


def min_photos(fmt: str) -> int:
    return _MIN_PHOTOS.get(fmt, 2)


def build_post(
    fmt: str, candidate: dict, listing: dict, photos: list[str]
) -> Optional[dict]:
    """Build the Post for `fmt`, or None if `photos` is too short for it.

    Returns {format, color_key, slides, caption, comment}. Pure — the caller
    renders `slides` and enqueues the caption/comment."""
    if fmt not in _BUILDERS:
        raise ValueError(f"unknown format {fmt!r}; valid: {sorted(_BUILDERS)}")
    if len(photos) < min_photos(fmt):
        return None
    return _BUILDERS[fmt](candidate, listing, photos)
