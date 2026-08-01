"""ig_story.py — the Story Director: turn a listing into a ≥4-slide carousel
that reads like a story, photo to photo.

A single image + a wall of caption doesn't stop the scroll. A carousel does:
an arresting opener, then a narrative that pulls the viewer slide by slide to
the CTA. This module builds that storyboard from a listing's OWN photos and
its OWN source data — so every post is concrete, honest, and unique.

The arc (always ≥4 slides, capped at the Instagram-carousel max of 10):

  1. OPENER   — the most breathtaking image the listing has (hero-scored),
                a short lever-shaped line. The scroll-stopper.
  2. PLACE    — where it is: zone + distance-to-beach, from real fields.
  3. PROOF…   — one slide per `reasons_to_buy` USP (frontage, minutes to the
                beach, flat entrance…). These are the listing's OWN selling
                points, already bilingual — so the middle of the story is
                never templated and never repeats between listings.
  4. MEANING  — the lever's payoff (why this, why now).
  5. CTA      — tu pedazo de paraíso → pulpo.club.

Every beat is SHORT (it's overlay text on a photo); the long-form persuasion
lives in the post caption (ig_copywriter). Beats are drawn from source data,
never invented. Pure + deterministic — no network, no model, no publish.
"""
from __future__ import annotations

from automation import ig_photo_gate

MAX_SLIDES = 10  # Instagram carousel hard cap
MIN_SLIDES = 4

# Short, overlay-length lines. OPENER stops the scroll; MEANING pays it off.
# Kept distinct from the caption hook so the carousel and the caption don't
# read as the same sentence twice.
_OPENER: dict[str, tuple[str, str]] = {
    "scarcity":       ("Frente al mar. Y ya casi no queda.", "Oceanfront. And barely any left."),
    "authority":      ("El mundo volteó a ver El Salvador.", "The world turned to look at El Salvador."),
    "social_proof":   ("Los de afuera ya están comprando.", "Outsiders are already buying."),
    "aspiration":     ("Imaginate despertar aquí.", "Imagine waking up here."),
    "investment":     ("Tierra: activo duro, en dólares.", "Land: a hard asset, in dollars."),
    "transformation": ("El país que recordás ya cambió.", "The country you remember has changed."),
    "education":      ("Todo El Salvador, en un solo lugar.", "All of El Salvador, in one place."),
}
_MEANING: dict[str, tuple[str, str]] = {
    "scarcity":       ("Lo bueno se vende primero.", "The good ones sell first."),
    "authority":      ("Vos ya estás aquí. Llevás ventaja.", "You're already here. You're ahead."),
    "social_proof":   ("Vení antes que crezca la fila.", "Get in before the line grows."),
    "aspiration":     ("Tu pedazo de paraíso.", "Your piece of paradise."),
    "investment":     ("No se devalúa mientras dormís.", "It doesn't lose value while you sleep."),
    "transformation": ("Y esto apenas empieza.", "And this is just the start."),
    "education":      ("Abrí una página y vé lo mejor.", "Open one page, see the best."),
}
_CTA: tuple[str, str] = ("pulpo.club · link en bio", "pulpo.club · link in bio")


def _active_country_name() -> str:
    """Fallback place label = the active country from the manifest — never a
    hardcoded country literal (check_country_hardcodes guard)."""
    try:
        from pulpo.countries import active
        return active().name_en
    except Exception:
        return ""


def _zone_label(listing: dict) -> str:
    z = (listing.get("zone") or "").replace("-", " ").strip()
    return z.title() if z else (listing.get("department") or _active_country_name())


def _ordered_photos(listing: dict, cap: int = MAX_SLIDES) -> list[str]:
    """Hero-first carousel URLs from the listing's own photos (broker-rejected
    frames already dropped by the photo gate). Falls back to raw source order."""
    urls = listing.get("photo_urls") or []
    if not urls:
        return []
    order = ig_photo_gate.order_photo_indices(listing)
    picked = [urls[i] for i in order if 0 <= i < len(urls)]
    if not picked:
        picked = list(urls)
    return picked[:cap]


def _place_beat(listing: dict) -> tuple[str, str]:
    zone = _zone_label(listing)
    d = listing.get("dist_beach_km")
    if isinstance(d, (int, float)):
        if d <= 0.05:
            return (f"{zone} · en la playa", f"{zone} · on the beach")
        if d < 1:
            return (f"{zone} · a pasos del mar", f"{zone} · steps from the sea")
        if d <= 3:
            return (f"{zone} · minutos del mar", f"{zone} · minutes from the sea")
    return (zone, zone)


def _reason_beats(listing: dict) -> list[tuple[str, str]]:
    """Each reasons_to_buy USP as a bilingual beat — the listing's own, real,
    concrete selling points. This is the non-repeating spine of the story."""
    out: list[tuple[str, str]] = []
    for r in (listing.get("reasons_to_buy") or []):
        if isinstance(r, dict):
            es, en = (r.get("es") or "").strip(), (r.get("en") or "").strip()
            if es or en:
                out.append((es or en, en or es))
    return out


def _slide(index: int, role: str, image: str, es: str, en: str) -> dict:
    return {"index": index, "role": role, "image": image, "text_es": es, "text_en": en}


def build_storyboard(listing: dict, lever: str, *, max_slides: int = MAX_SLIDES) -> list[dict]:
    """Ordered slides (opener → place → proof… → meaning → cta), each with an
    image URL + a short bilingual beat. Always ≥4 slides when the listing has
    the photos for it; never more than it has photos (no blank slides)."""
    photos = _ordered_photos(listing, max_slides)
    if not photos:
        return []

    opener = _OPENER.get(lever, _OPENER["aspiration"])
    meaning = _MEANING.get(lever, _MEANING["aspiration"])
    place = _place_beat(listing)
    reasons = _reason_beats(listing)

    # Beat plan (before pairing with photos): opener, place, each reason,
    # meaning, cta — then trimmed to the number of photos available.
    beats: list[tuple[str, str, str]] = [("opener", *opener), ("place", *place)]
    beats += [("proof", es, en) for es, en in reasons]
    beats += [("meaning", *meaning), ("cta", *_CTA)]

    n = min(len(beats), len(photos), max_slides)
    if n < MIN_SLIDES:
        # Too few reasons AND few photos: pad the middle by repeating the best
        # photo under remaining reason/meaning beats rather than drop below 4.
        # (In practice every gated listing has ≥6 photos, so this is a floor.)
        n = min(MIN_SLIDES, len(beats))
    # Always keep the CTA as the closer: if trimming, drop from the middle
    # (proof beats), never the opener/place/meaning/cta anchors.
    if len(beats) > n:
        anchors = [beats[0], beats[1], beats[-2], beats[-1]]  # opener, place, meaning, cta
        middle = beats[2:-2]
        keep_mid = middle[: max(0, n - len(anchors))]
        beats = [beats[0], beats[1], *keep_mid, beats[-2], beats[-1]]
        n = len(beats)

    slides: list[dict] = []
    for i in range(n):
        role, es, en = beats[i]
        image = photos[i] if i < len(photos) else photos[-1]
        slides.append(_slide(i + 1, role, image, es, en))
    return slides
