"""ig_render.py — render a Social-Brain post into real slide images + a queue item.

Bridges the generator (ig_generate_post → storyboard + caption) to the actual
Instagram publisher (ig_publish, which posts poster_path + carousel_photo_paths).
Rendering reuses the campaign renderer (ig_campaign_poster.render_slide, HTML→JPEG
via Playwright) — the same engine the paraíso campaign shipped on.

SAFE-BY-DEFAULT: the first-wave carousel is entirely DESIGNED slides + the one
curated zone photo — NO raw broker photos, so there is no watermark/broker-phone
risk and nothing needs human photo-review before it can publish. Real listing
photos (each needing a watermark check) are a later, opt-in enhancement.

  slide 1  — OPENER: curated zone photo + intriguing hook (or a designed
             text opener if the zone has no curated photo yet)
  slide 2  — DETAIL: the listing (zone · price · one honest fact), designed
  slide 3+ — USP cards: the listing's own reasons_to_buy, designed
  last     — CTA: tu pedazo de paraíso → link en bio, designed

render_post() returns a queue item in the shape ig_publish consumes.
"""
from __future__ import annotations

import re
from pathlib import Path

from automation import ig_campaign_poster as cp
from automation import ig_zone_images

ASSETS_ROOT = Path("web/data/ig_assets/social_brain")

# per-angle accent colour + eyebrow label (the three viral angles + supporting)
_ANGLE = {
    "aspiration":     ("#0e7490", "POV"),
    "education":      ("#8957e5", "El #1"),
    "transformation": ("#d1477a", "Diáspora"),
    "social_proof":   ("#c0392b", "Diáspora"),
    "investment":     ("#2da44e", "Inversión"),
    "scarcity":       ("#e8462a", "Escasez"),
    "authority":      ("#1f6feb", "Autoridad"),
}


def _color_eyebrow(lever: str) -> tuple[str, str]:
    return _ANGLE.get(lever, ("#e8462a", "Pulpo"))


def _accent(line: str) -> str:
    """Pick a word to accent in the opener — the last meaningful word of the
    hook (what the curiosity gap lands on), stripped of punctuation."""
    words = re.findall(r"[\wáéíóúñ]+", line, re.IGNORECASE)
    return words[-1] if words else ""


def _fmt_price(p) -> str:
    return f"${p:,.0f}" if isinstance(p, (int, float)) and p > 0 else ""


def _opener_spec(post: dict, color: str, eyebrow: str) -> dict:
    """Curated zone photo + hook if available; else a designed text opener."""
    op = post["slides"][0]
    line = op["text_es"]
    # avoid doubling the eyebrow inside the hook (e.g. eyebrow "POV" + "POV: …")
    if eyebrow and line.upper().startswith(eyebrow.upper()):
        line = re.sub(rf"^{re.escape(eyebrow)}\s*[:：]?\s*", "", line, flags=re.IGNORECASE) or line
    zone_label = (post.get("zone") or "").replace("-", " ").title()
    dept = post.get("department") or ""
    sub = f"{zone_label} · {dept}".strip(" ·") or zone_label
    entry = ig_zone_images.get(post.get("zone"))
    if entry:
        return {"t": "story", "img": entry["image"], "eye": eyebrow, "line": line,
                "accent": _accent(line), "sub": sub, "scrim": "down",
                "small": "pulpo.club · link en bio"}
    # no curated photo → designed text opener (still on-brand, still safe).
    # l1 = the intriguing hook, l2 = its payoff (the meaning beat).
    meaning = next((s["text_es"] for s in post["slides"] if s["role"] == "meaning"), sub)
    return {"t": "statement", "eyebrow": eyebrow, "l1": line, "l2": meaning, "punch": sub}


def _middle_specs(post: dict, eyebrow: str) -> list[dict]:
    specs: list[dict] = []
    zone_label = (post.get("zone") or "").replace("-", " ").title()
    price = _fmt_price(post.get("price_usd"))
    # detail card: the listing at a glance
    place = next((s["text_es"] for s in post["slides"] if s["role"] == "place"), zone_label)
    specs.append({"t": "detail", "eyebrow": eyebrow, "loc": zone_label,
                  "price": price, "facts": place})
    # usp cards from the listing's own reasons_to_buy (the proof beats)
    proofs = [s["text_es"] for s in post["slides"] if s["role"] == "proof"][:3]
    for i, usp in enumerate(proofs):
        specs.append({"t": "usp", "eyebrow": f"Por qué · {i + 1}", "title": usp, "body": ""})
    return specs


def _cta_spec() -> dict:
    return {"t": "cta", "big": "Tu pedazo de paraíso", "sub": "pulpo.club · link en bio"}


def build_specs(post: dict) -> list[dict]:
    """The full DESIGNED-safe slide plan (opener → detail → usps → cta)."""
    color, eyebrow = _color_eyebrow(post["lever"])
    return [_opener_spec(post, color, eyebrow), *_middle_specs(post, eyebrow), _cta_spec()]


def _attribution(post: dict) -> str:
    """Attribution line for a curated zone photo (required for CC-BY/SA).
    Empty for CC0 / no-photo openers."""
    entry = ig_zone_images.get(post.get("zone"))
    if not entry:
        return ""
    lic = (entry.get("license") or "").lower()
    if "cc0" in lic or "public domain" in lic:
        return ""
    zl = (post.get("zone") or "").replace("-", " ").title()
    return f"📸 {zl}: {entry.get('credit')} ({entry.get('license')}) vía Wikimedia Commons"


def render_post(post: dict, *, out_root: Path = ASSETS_ROOT, renderer=cp.render_slide) -> dict:
    """Render every slide of `post` to a JPEG and return the ig_publish queue item.
    Designed-safe: the only photo is the curated, licensed zone image."""
    color, _ = _color_eyebrow(post["lever"])
    specs = build_specs(post)
    slug = f"sb_d{post['day']:03d}_{post['lever']}"
    out_dir = out_root / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[str] = []
    for i, spec in enumerate(specs, 1):
        p = renderer(spec, color, out_dir / f"slide{i}.jpg")
        # store as repo-relative posix path (ig_publish turns web/ → public URL)
        paths.append(str(Path(p).as_posix()))

    comment = post["comment_es"]
    attr = _attribution(post)
    if attr:
        comment = f"{comment}\n\n{attr}"

    return {
        "day": post["day"],
        "shelf": "social_brain",
        "format": "carousel",
        "story_id": post["lever"],
        "selector": "social_brain_v1",
        "poster_type": specs[0]["t"],
        "palette": post["lever"],
        "assets_dir": str(out_dir.as_posix()),
        "poster_path": paths[0],
        "poster_overrides": {},
        "caption": post["caption_es"],
        "comment": comment,
        "carousel_photo_paths": paths[1:],
        "attribution_code": post.get("attribution_code"),
        "opener_kind": post.get("opener_kind"),
        "listing_ids": [post["listing_id"]],
        "primary_listing_id": post["listing_id"],
        "status": "scheduled",
        "approved": False,   # a human flips this to True in review before it can publish
        "posted": False,
        "posted_at": None,
        "posted_media_id": None,
    }
