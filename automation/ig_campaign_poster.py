"""ig_campaign_poster.py — "Tu pedazo de paraíso" campaign slide renderer.

Renders the fresh, white/colorful, bilingual-caption campaign approved by
Sebastian (2026-07-10) into 1080×1350 IG carousel slides.  Two families:

  - PHOTO slides   — a real, hand-inspected listing photo full-bleed with a
                     colored category ribbon, ★ Destacado flag, and a white
                     price/feature pill.  Used by the Top-10 posts.
  - DESIGN slides  — solid-color cards (coral for inspiration, category
                     color for Top-10 closers) carrying a statement, a real
                     data stat, a USP, a compare, a news blurb, a CTA, or a
                     listing detail.  Used by the inspiration posts and as
                     the closing/overflow slide where clean photos run out
                     (apartments).

Design language mirrors the approved review board exactly: Nunito (rounded,
warm, "bien de aquí"), the Pulpo octopus-with-eyes signing every slide, a
faint octopus watermark on design cards, and the category color system.

Rendering reuses ig_poster._render_via_playwright (headless Chromium at
1080×1350) so we share the one browser dependency the nightly already
installs.  build_slide_html() is pure (no I/O beyond the optional photo
base64-encode) so unit tests can assert on markup without a browser.

Category colors are the single source of truth here and must match
web/app + the review board:

    Casas de Playa      #0a97ab   Apartamentos       #c67d12
    Terrenos de Playa   #1073b8   Terrenos de Lago   #2f9e44
    Casas de Lago       #0e9c8a   Inspiración        #e8462a
"""
from __future__ import annotations

import argparse
import base64
import html
import json
from pathlib import Path

from automation.ig_poster import _render_via_playwright, POSTER_W, POSTER_H

# ── category colors (single source of truth; mirror web/app + board) ───
CATEGORY_COLORS = {
    "casas_playa":    "#0a97ab",
    "terrenos_playa": "#1073b8",
    "casas_lago":     "#0e9c8a",
    "apartamentos":   "#c67d12",
    "terrenos_lago":  "#2f9e44",
    "inspiracion":    "#e8462a",
    "cierre":         "#0a97ab",
}
INSPIRACION = CATEGORY_COLORS["inspiracion"]

# The octopus-with-eyes, matching the approved board.  Inlined so slides
# are self-contained (no external image fetch at render time).
_OCT = (
    '<svg viewBox="0 0 48 48" fill="currentColor" aria-hidden="true">'
    '<path d="M24 8c-7 0-12 5-12 12v5c0 2-1 3-3 4-2 1.4-3 2.8-3 4.6 0 2 1.7 3.4 '
    '3.6 3.4 1.8 0 2.7-1.4 3-2.6.4 1.3 1.4 2.6 3 2.6 1.5 0 2.6-1.2 3-2.6.5 1.5 '
    '1.6 2.6 3.4 2.6s2.9-1.1 3.4-2.6c.4 1.4 1.5 2.6 3 2.6 1.6 0 2.6-1.3 3-2.6.3 '
    '1.2 1.2 2.6 3 2.6 1.9 0 3.6-1.4 3.6-3.4 0-1.8-1-3.2-3-4.6-2-1-3-2-3-4v-5c0-'
    '7-5-12-12-12Z"/>'
    '<circle cx="19" cy="17" r="1.8" fill="#fff"/><circle cx="29" cy="17" r="1.8" fill="#fff"/>'
    "</svg>"
)

# Nunito: rounded, friendly, free — the render-box stand-in for Avenir Next.
_FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@600;700;800;900&display=swap" rel="stylesheet">'
)

_BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1350px}
body{font-family:"Nunito",-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
  -webkit-font-smoothing:antialiased;overflow:hidden}
.slide{position:relative;width:1080px;height:1350px;overflow:hidden;color:#fff;
  display:flex;flex-direction:column;padding:96px 90px}
/* ---- photo slide ---- */
.slide.photo{justify-content:space-between;background-size:cover;background-position:center}
.scrim{position:absolute;inset:0;z-index:0;background:linear-gradient(178deg,
  rgba(0,0,0,.34) 0%,rgba(0,0,0,0) 30%,rgba(0,0,0,.14) 55%,rgba(0,0,0,.80) 100%)}
.slide>*{position:relative;z-index:1}
.ptop{display:flex;align-items:flex-start;justify-content:space-between;gap:20px}
.ribbon{font-weight:900;font-size:38px;letter-spacing:.01em;background:var(--c);
  color:#fff;padding:20px 34px;border-radius:999px;box-shadow:0 10px 26px -10px rgba(0,0,0,.5)}
.star{font-weight:900;font-size:36px;background:#fff;color:var(--c);padding:20px 32px;
  border-radius:999px;white-space:nowrap;box-shadow:0 10px 26px -10px rgba(0,0,0,.5)}
.pbot{margin-top:auto;display:flex;flex-direction:column;gap:30px}
.pricepill{align-self:flex-start;font-weight:900;font-size:44px;background:#fff;color:#161c20;
  padding:26px 40px;border-radius:999px;box-shadow:0 12px 30px -12px rgba(0,0,0,.5)}
.pfoot{display:flex;align-items:center;justify-content:space-between;gap:20px}
.purl{font-weight:800;font-size:40px;color:#fff;text-shadow:0 2px 12px rgba(0,0,0,.85)}
.oct{width:74px;height:74px;color:#fff;filter:drop-shadow(0 3px 8px rgba(0,0,0,.55))}
/* ---- design slide ---- */
.slide.design{justify-content:center;gap:28px;background:var(--c)}
.slide.design.grad{background:linear-gradient(150deg,var(--c),color-mix(in oklab,var(--c) 52%,#12181d) 135%)}
.deco{position:absolute;right:-70px;bottom:-80px;z-index:0;opacity:.13;width:560px;height:560px;color:#fff}
.eyebrow{align-self:flex-start;font-weight:900;font-size:34px;letter-spacing:.03em;
  text-transform:uppercase;color:#fff;background:rgba(0,0,0,.20);padding:16px 30px;border-radius:999px}
.eyebrow.solid{background:#fff;color:var(--c)}
.big{font-weight:900;font-size:300px;line-height:.9;letter-spacing:-.02em}
.big.sm{font-size:190px}
.label{font-weight:700;font-size:52px;line-height:1.32}
.src{margin-top:8px;font-weight:800;font-size:34px;opacity:.85}
.head1{font-weight:800;font-size:76px;line-height:1.02;opacity:.96}
.head2{font-weight:900;font-size:132px;line-height:.98;letter-spacing:-.02em}
.punch{font-weight:800;font-size:50px;line-height:1.15;margin-top:6px}
.title{font-weight:900;font-size:96px;line-height:1.02;letter-spacing:-.01em}
.body{font-weight:700;font-size:52px;line-height:1.32}
.cmp{display:flex;flex-direction:column;gap:22px;margin:6px 0}
.cmp .row{font-weight:800;font-size:44px;line-height:1.28;padding:28px 32px;border-radius:26px;display:flex;gap:20px}
.cmp .bad{background:rgba(0,0,0,.22)}
.cmp .good{background:#fff;color:var(--c);font-weight:900}
.note{font-weight:900;font-size:50px;line-height:1.18}
.price{font-weight:900;font-size:150px;line-height:1}
.loc{font-weight:800;font-size:48px;opacity:.95}
.foot-oct{position:absolute;left:90px;bottom:84px;z-index:1;width:78px;height:78px;color:#fff}
"""


def _e(s: str) -> str:
    return html.escape(s or "")


def _br(s: str) -> str:
    return _e(s).replace("\n", "<br>")


def _doc(inner: str) -> str:
    return (
        "<!DOCTYPE html><html lang=\"es\"><head><meta charset=\"UTF-8\">"
        f"{_FONTS_LINK}<style>{_BASE_CSS}</style></head><body>{inner}</body></html>"
    )


def _encode_photo(path: str) -> str:
    data = Path(path).read_bytes()
    ext = Path(path).suffix.lstrip(".").lower() or "jpeg"
    if ext == "jpg":
        ext = "jpeg"
    return f"data:image/{ext};base64,{base64.b64encode(data).decode()}"


# ── slide builders (pure) ──────────────────────────────────────────────

def _photo(spec: dict, color: str) -> str:
    src = _encode_photo(spec["img"])
    top = [f'<span class="ribbon">{_e(spec["ribbon"])}</span>']
    if spec.get("star"):
        top.append('<span class="star">★ Destacado</span>')
    bot = []
    if spec.get("badge"):
        bot.append(f'<span class="pricepill">{_e(spec["badge"])}</span>')
    bot.append(
        '<div class="pfoot"><span class="purl">pulpo.club · link en bio</span>'
        f'<span class="oct">{_OCT}</span></div>'
    )
    return (
        f'<div class="slide photo" style="--c:{color};background-image:url({src})">'
        '<div class="scrim"></div>'
        f'<div class="ptop">{"".join(top)}</div>'
        f'<div class="pbot">{"".join(bot)}</div></div>'
    )


def _design(color: str, inner: str, grad: bool = False) -> str:
    cls = "slide design grad" if grad else "slide design"
    return (
        f'<div class="{cls}" style="--c:{color}">'
        f'<span class="deco">{_OCT}</span>{inner}'
        f'<span class="foot-oct">{_OCT}</span></div>'
    )


def _statement(spec: dict, color: str) -> str:
    eb = f'<span class="eyebrow">{_e(spec["eyebrow"])}</span>' if spec.get("eyebrow") else ""
    pu = f'<div class="punch">{_e(spec["punch"])}</div>' if spec.get("punch") else ""
    inner = (
        f'{eb}<div><div class="head1">{_e(spec["l1"])}</div>'
        f'<div class="head2">{_e(spec["l2"])}</div></div>{pu}'
    )
    return _design(color, inner)


def _stat(spec: dict, color: str) -> str:
    src = f'<div class="src">{_e(spec["src"])}</div>' if spec.get("src") else ""
    big_cls = "big sm" if len(spec["big"]) > 4 or "\n" in spec["big"] else "big"
    inner = (
        '<span class="eyebrow">Dato real</span>'
        f'<div class="{big_cls}">{_br(spec["big"])}</div>'
        f'<div class="label">{_br(spec["label"])}</div>{src}'
    )
    return _design(color, inner)


def _usp(spec: dict, color: str) -> str:
    inner = (
        f'<span class="eyebrow">{_e(spec["eyebrow"])}</span>'
        f'<div class="title">{_e(spec["title"])}</div>'
        f'<div class="body">{_e(spec["body"])}</div>'
    )
    return _design(color, inner)


def _compare(spec: dict, color: str) -> str:
    inner = (
        f'<span class="eyebrow">{_e(spec["eyebrow"])}</span>'
        '<div class="cmp">'
        f'<div class="row bad"><span>✕</span><span>{_e(spec["bad"])}</span></div>'
        f'<div class="row good"><span>✓</span><span>{_e(spec["good"])}</span></div></div>'
        f'<div class="note">{_e(spec["note"])}</div>'
    )
    return _design(color, inner)


def _news(spec: dict, color: str) -> str:
    inner = (
        f'<span class="eyebrow solid">{_e(spec["eyebrow"])}</span>'
        f'<div class="title">{_e(spec["head"])}</div>'
        f'<div class="body">{_e(spec["body"])}</div>'
        f'<div class="src">{_e(spec["src"])}</div>'
    )
    return _design(color, inner)


def _cta(spec: dict, color: str) -> str:
    inner = (
        f'<div class="head2">{_br(spec["big"])}</div>'
        f'<div class="punch">{_e(spec["sub"])}</div>'
    )
    return _design(color, inner, grad=True)


def _detail(spec: dict, color: str) -> str:
    inner = (
        f'<span class="eyebrow">{_e(spec["eyebrow"])}</span>'
        f'<div class="price">{_e(spec["price"])}</div>'
        f'<div class="body">{_e(spec["facts"])}</div>'
        f'<div class="loc">📍 {_e(spec["loc"])}</div>'
    )
    return _design(color, inner)


_DISPATCH = {
    "photo": _photo, "statement": _statement, "stat": _stat, "usp": _usp,
    "compare": _compare, "news": _news, "cta": _cta, "detail": _detail,
}


def build_slide_html(spec: dict, color: str) -> str:
    """Pure: build the full HTML doc for one slide.  `spec["t"]` selects
    the builder; `color` is the category/inspiration hex."""
    t = spec.get("t")
    if t not in _DISPATCH:
        raise ValueError(f"unknown slide type {t!r}; valid: {sorted(_DISPATCH)}")
    return _doc(_DISPATCH[t](spec, color))


def render_slide(spec: dict, color: str, output_path: Path) -> Path:
    """Render one slide spec to a 1080×1350 PNG via headless Chromium."""
    html_doc = build_slide_html(spec, color)
    return _render_via_playwright(html_doc, output_path, width=POSTER_W, height=POSTER_H)


# ── CLI (render a single slide from a JSON spec, for iteration) ─────────

def _main() -> None:
    ap = argparse.ArgumentParser(description="Render one campaign slide to PNG.")
    ap.add_argument("--spec", required=True, help="JSON slide spec (inline or @file)")
    ap.add_argument("--color", default=INSPIRACION, help="category/inspiration hex")
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    raw = args.spec
    if raw.startswith("@"):
        raw = Path(raw[1:]).read_text(encoding="utf-8")
    spec = json.loads(raw)
    out = render_slide(spec, args.color, args.output)
    print(f"rendered {out}")


if __name__ == "__main__":
    _main()
