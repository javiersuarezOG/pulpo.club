"""ig_story_series.py — the inspirational, story-driven content engine.

The direction (Javier, 2026-07-25): **inspire, don't sell.** No price
guesses, no "which do you want to buy". Each post is a *story* — a single
feeling, carried by a real listing's most beautiful photo and one poetic
line in an editorial serif. The image moves you; the price and zone drop to
the first comment and whisper. Pulpo signs quietly at the bottom.

Fourteen distinct stories (see STORIES) rotate with **no repeat inside a
cycle** — deterministic by post index — so no two days feel the same. Each
carries an ``emotion`` tag so the engagement loop (a follow-up PR) can learn
which *stories* connect and lean into them.

Pure functions only — no I/O, no network, no rendering. The autopilot
downloads brand-safe photos and renders the ``story`` slides; this module
decides what each post SAYS and SHOWS.
"""
from __future__ import annotations

from typing import Optional

from automation.ig_units import format_area_m2, format_price_usd
from pulpo.countries import active as _active_country

_COUNTRY = _active_country().name_en
_C = _COUNTRY.replace(" ", "")

# ES property-type noun for the property card on slide 2.
_NOUN = {"land": "terreno", "house": "casa", "condo": "apartamento"}

# ── the story library ─────────────────────────────────────────────────
#
# Each story: a stable id, the slide fields (eyebrow, poetic line with an
# accented word, optional sub, composition), an ``emotion`` tag for the
# learning loop, and ``cap`` — a unique, inspirational caption body (the
# price is NOT here; it whispers in the first comment). Captions are written
# to pass ig_caption_lint (no listing-speak, no "!!", ≤2 back-to-back emoji).

STORIES: tuple[dict, ...] = (
    {"id": "el_mar", "emotion": "regreso", "eye": "Para el que anda lejos",
     "line": "El mar no se ha\nido a ningún lado.", "accent": "mar",
     "sub": "Tu pedazo de costa te sigue esperando.", "pos": "bottom", "scrim": "down",
     "cap": "Te fuiste, pero el mar sigue rompiendo igual que el día que te fuiste. "
            "La costa no se apura. Te espera."},
    {"id": "lunes_domingo", "emotion": "calma", "eye": "La vida que sí querés",
     "line": "Aquí el lunes\ntambién sabe\na domingo.", "accent": "domingo",
     "pos": "center", "scrim": "center",
     "cap": "Despertar sin alarma, café viendo el verde, y la sensación de que no hay prisa. "
            "Así se siente tener lo tuyo aquí."},
    {"id": "raices", "emotion": "legado", "eye": "Raíces", "small": True,
     "line": "Lo que plantés hoy,\nte va a sobrevivir.", "accent": "sobrevivir",
     "sub": "Un pedazo de tierra que lleva tu nombre.", "pos": "bottom", "scrim": "down",
     "cap": "Un árbol que plantás hoy da sombra a quien todavía no conocés. "
            "Eso es tener tierra: sembrar para los que vienen."},
    {"id": "ya_volvio", "emotion": "orgullo", "eye": "Tu país",
     "line": "El país al que\njurabas volver,\nya volvió.", "accent": "ya volvió",
     "pos": "top", "scrim": "up",
     "cap": f"El {_COUNTRY} que dejaste no es el que vas a encontrar. La costa está despierta, "
            "y todavía hay lugar para vos."},
    {"id": "hora_dorada", "emotion": "lugar", "eye": "La hora dorada", "small": True,
     "line": "A las 6, el cielo se pone\ndel color de tu casa.", "accent": "tu casa",
     "pos": "bottom", "scrim": "down",
     "cap": "Esa media hora en que todo se pone dorado y el mundo baja la velocidad. "
            "Imaginá que pasa desde tu terraza."},
    {"id": "aprendan_nadar", "emotion": "familia", "eye": "Para los que vienen",
     "line": "Donde tus hijos\naprendan a nadar.", "accent": "aprendan a nadar",
     "pos": "bottom", "scrim": "down",
     "cap": "No es un terreno: es tardes de sal en el pelo y risas que se oyen desde la casa. "
            "Es donde crecen."},
    {"id": "semaforo_marea", "emotion": "cambio", "eye": "Otra vida es posible",
     "line": "Cambiá el semáforo\npor la marea.", "accent": "la marea",
     "pos": "center", "scrim": "center",
     "cap": "El semáforo o la marea. Los dos te hacen esperar; solo uno te devuelve algo. "
            "Elegí con calma."},
    {"id": "algun_dia", "emotion": "empuje", "eye": "Sin más excusas",
     "line": "Algún día\nes hoy.", "accent": "es hoy", "pos": "center", "scrim": "center",
     "cap": "Siempre es 'algún día'. Algún día el mar, algún día la casa, algún día volver. "
            "Ese día no llega solo."},
    {"id": "olor_lluvia", "emotion": "pertenencia", "eye": "Ser dueño",
     "line": "El olor a lluvia\nsobre tierra tuya.", "accent": "tuya",
     "pos": "bottom", "scrim": "down",
     "cap": "El primer aguacero sobre tierra que es tuya huele distinto. A principio, a raíz, "
            "a que por fin llegaste."},
    {"id": "horizonte", "emotion": "amplitud", "eye": "Espacio de verdad", "small": True,
     "line": "Aquí no hay más vecino\nque el horizonte.", "accent": "el horizonte",
     "pos": "bottom", "scrim": "down",
     "cap": "Sin paredes del vecino, sin ruido ajeno. Solo vos, el aire y una línea de mar "
            "hasta donde alcanza la vista."},
    {"id": "abuelo", "emotion": "memoria", "eye": "Generaciones",
     "line": "Tu abuelo caminó\nesta costa.", "accent": "esta costa",
     "sub": "Vos podés quedártela.", "pos": "bottom", "scrim": "down",
     "cap": "Tu familia conoce esta costa de memoria. Quedártela no es comprar un lugar: "
            "es no soltar el hilo."},
    {"id": "distancia", "emotion": "regreso", "eye": "El regreso",
     "line": "La distancia\nse cura llegando.", "accent": "llegando",
     "pos": "center", "scrim": "center",
     "cap": "La nostalgia no se cura con fotos. Se cura bajando del avión y sabiendo que "
            "hay un lugar que es tuyo."},
    {"id": "tiempo_tuyo", "emotion": "tiempo", "eye": "Calma", "small": True,
     "line": "Un lugar donde el tiempo\npor fin es tuyo.", "accent": "es tuyo",
     "pos": "bottom", "scrim": "down",
     "cap": "Comprar tiempo no se puede, dicen. Aquí casi. Un lugar donde las horas por fin "
            "te pertenecen."},
    {"id": "queda_paraiso", "emotion": "escasez", "eye": "No es para siempre", "small": True,
     "line": "Todavía queda paraíso.\nCada vez menos.", "accent": "Cada vez menos",
     "pos": "bottom", "scrim": "down",
     "cap": "La tierra frente al mar no se fabrica, y cada año queda menos. Todavía estás a "
            "tiempo de tener la tuya."},
)

_BY_ID = {s["id"]: s for s in STORIES}


# ── zone / hashtags / whisper ─────────────────────────────────────────

def _zone_title(zone: Optional[str]) -> str:
    if not zone:
        return _COUNTRY
    return " ".join(w.capitalize() for w in str(zone).replace("_", "-").split("-"))


def _zone_hashtag(zone: Optional[str]) -> str:
    if not zone:
        return ""
    return "#" + "".join(w.capitalize() for w in str(zone).replace("_", "-").split("-"))


_CORE_HASHTAGS: tuple[str, ...] = (
    f"#{_C}", "#BienesRaices", "#SurfCity", f"#PlayasDe{_C}",
    "#SalvadorenosPorElMundo", "#TuPedazoDeParaiso",
)


def _hashtags(candidate: dict) -> str:
    tags = list(_CORE_HASHTAGS)
    zt = _zone_hashtag(candidate.get("zone"))
    if zt and zt not in tags:
        tags.insert(3, zt)
    return " ".join(tags)


# ── rotation ───────────────────────────────────────────────────────────

def story_for_index(post_index: int) -> dict:
    """The story the Nth post uses. Straight cycle over STORIES → no repeat
    within a 14-post cycle (the learning loop reweights this later)."""
    return STORIES[post_index % len(STORIES)]


def min_photos(_story: Optional[dict] = None) -> int:
    return 1  # a story needs only its cover; a 2nd clean photo is a bonus


# ── build ─────────────────────────────────────────────────────────────

def build_post(story: dict, candidate: dict, listing: dict, photos: list[str]) -> Optional[dict]:
    """Build the Post for a story. Brand-safety first: the ONLY listing photo
    shown is the pipeline-vetted hero (``photos[0]``); slide 2 is a
    photo-free brand closer, so no second (less-vetted) image can leak a
    broker logo or phone number. Returns None if no usable photo.

    slides → [story cover (hero photo), cta closer (no photo)].
    Caption inspires; the first comment whispers the real listing details."""
    if isinstance(story, str):
        story = _BY_ID[story]
    if not photos:
        return None
    zone = _zone_title(candidate.get("zone"))
    department = candidate.get("department") or ""
    loc = f"{zone}, {department}" if department and department != zone else zone
    area = format_area_m2(candidate.get("area_m2"))
    price = format_price_usd(candidate.get("price_usd"))
    noun = _NOUN.get((candidate.get("property_type") or "").lower(), "propiedad")

    # Cover: the emotional line stays the hero, but the eyebrow now names the
    # place so the beautiful image is tied to a real location, not a quote.
    cover = {"t": "story", "img": photos[0],
             "eye": f"{story['eye']} · {zone}",
             "line": story["line"], "accent": story.get("accent", "")}
    if story.get("sub"):
        cover["sub"] = story["sub"]
    if story.get("small"):
        cover["small"] = True
    cover["pos"] = story.get("pos", "bottom")
    cover["scrim"] = story.get("scrim", "down")
    # Slide 2 is now a real PROPERTY card (was a generic brand closer) — it
    # references the actual listing on the image: location · size/type ·
    # price · pulpo.club. Still photo-free (no broker-watermark risk).
    facts = " · ".join(x for x in (area, noun) if x and x != "—")
    closer = {"t": "detail", "eyebrow": "La propiedad", "price": price,
              "facts": f"{facts} · en pulpo.club", "loc": loc}
    slides = [cover, closer]

    caption = f"{story['cap']}\n\n📍 {zone}. Mirá esta y las demás en pulpo.club — link en bio."

    # The first comment reinforces the details + carries discovery hashtags.
    spec = " · ".join(x for x in (zone, area, price) if x and x != "—")
    comment = (
        f"{spec}.\n\n"
        "Todas las propiedades del país, rankeadas por valor, en un solo lugar 👉 pulpo.club\n\n"
        f"{_hashtags(candidate)}"
    )
    # color_key drives the closer card's hue (the story cover ignores it —
    # its accent is a fixed warm coral). Ocean blue keeps the closer calm.
    return {"story_id": story["id"], "emotion": story["emotion"], "color_key": "terrenos_playa",
            "slides": slides, "caption": caption, "comment": comment}
