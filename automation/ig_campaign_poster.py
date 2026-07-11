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
import zlib
from pathlib import Path

from automation.ig_poster import _render_via_playwright, POSTER_W, POSTER_H

# ── category colors (single source of truth; mirror web/app + board) ───
# Photo (Top-10) posts use the category colors for their ribbons.  The
# design-only inspiration/wrap cards use the cool per-day palette below —
# one distinct hue per card, walking violet → blue → teal → green with a
# teal finale.  No red/orange on the text cards (the flat-red run was
# replaced 2026-07-11); ``inspiracion`` is kept only for back-compat.
CATEGORY_COLORS = {
    "casas_playa":    "#0a97ab",
    "terrenos_playa": "#1073b8",
    "casas_lago":     "#0e9c8a",
    "apartamentos":   "#c67d12",
    "terrenos_lago":  "#2f9e44",
    "inspiracion":    "#e8462a",
    "cierre":         "#0a97ab",
    # design-card cool palette (one hue per inspiration/wrap card)
    "insp_violet":    "#7048e8",   # day 201
    "insp_indigo":    "#4263eb",   # day 203
    "insp_blue":      "#1c7ed6",   # day 205
    "insp_cyan":      "#1098ad",   # day 207
    "insp_teal":      "#0c8599",   # day 209
    "insp_seagreen":  "#0ca678",   # day 211
    "insp_green":     "#2f9e44",   # day 213 (day 214 uses "cierre")
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

# Brand lockup stamped on every design card: octopus + pulpo.club wordmark
# + the campaign tagline.  Anchored bottom-left, above the vignette.
_BRAND = (
    '<div class="brand"><span class="m">' + _OCT + "</span>"
    '<span class="txt"><span class="wm">pulpo<span class="club">.club</span></span>'
    '<span class="kick">Tu pedazo de paraíso.<br>Pulpo te lo encuentra.</span></span></div>'
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
.slide.photo>*{position:relative;z-index:1}
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
/* ---- design slide: crafted, brand-forward ground ---- */
.slide.design{justify-content:center;padding-bottom:210px;isolation:isolate;
  background:
    radial-gradient(1150px 820px at 20% 8%, color-mix(in oklab,var(--c) 82%,#ffffff) 0%, transparent 56%),
    radial-gradient(1050px 1150px at 96% 108%, color-mix(in oklab,var(--c) 55%,#0a1216) 0%, transparent 62%),
    linear-gradient(152deg, var(--c) 0%, color-mix(in oklab,var(--c) 60%,#0b141a) 132%)}
.slide.design.grad{background:
    radial-gradient(1150px 820px at 20% 8%, color-mix(in oklab,var(--c) 82%,#ffffff) 0%, transparent 56%),
    linear-gradient(150deg, var(--c), color-mix(in oklab,var(--c) 46%,#0b141a) 135%)}
/* full-bleed background layers (localización + tech motif, grain, scrims) */
.lyr{position:absolute;inset:0;z-index:0;pointer-events:none}
.lyr svg{width:100%;height:100%;display:block}
.grain{background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='170' height='170'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.82' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix type='saturate' values='0'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  opacity:.05;mix-blend-mode:overlay}
.tscrim{background:linear-gradient(102deg, rgba(0,0,0,.24) 0%, rgba(0,0,0,.10) 38%, transparent 64%)}
.vig{background:linear-gradient(to bottom, rgba(255,255,255,.05) 0%, transparent 20%, transparent 55%, rgba(0,0,0,.30) 100%)}
.content{position:relative;z-index:2;display:flex;flex-direction:column;gap:28px;align-items:flex-start;width:100%}
.eyebrow{align-self:flex-start;font-weight:900;font-size:34px;letter-spacing:.03em;
  text-transform:uppercase;color:#fff;background:rgba(0,0,0,.24);padding:16px 30px;border-radius:999px}
.eyebrow.solid{background:#fff;color:var(--c)}
.big{font-weight:900;font-size:300px;line-height:.9;letter-spacing:-.02em;text-shadow:0 6px 40px rgba(0,0,0,.18)}
.big.sm{font-size:190px}
.label{font-weight:700;font-size:52px;line-height:1.32}
.src{margin-top:8px;font-weight:800;font-size:34px;opacity:.86}
.head1{font-weight:800;font-size:76px;line-height:1.02;opacity:.96}
.head2{font-weight:900;font-size:132px;line-height:.98;letter-spacing:-.02em;text-shadow:0 6px 40px rgba(0,0,0,.16)}
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
/* brand lockup */
.brand{position:absolute;left:90px;bottom:82px;z-index:3;display:flex;align-items:center;gap:22px}
.brand .m{width:92px;height:92px;color:#fff;filter:drop-shadow(0 4px 12px rgba(0,0,0,.42))}
.brand .txt{display:flex;flex-direction:column;gap:8px}
.brand .wm{font-weight:900;font-size:74px;letter-spacing:-.02em;color:#fff;line-height:.92}
.brand .wm .club{opacity:.74;font-weight:800}
.brand .kick{font-weight:800;font-size:25px;letter-spacing:.1em;text-transform:uppercase;color:#fff;opacity:.82;max-width:600px;line-height:1.25}
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


def _rng(seed: int):
    """Deterministic LCG (matches the preview's seeded RNG) so each slide's
    motif is a stable, distinct constellation across re-renders."""
    s = seed % 233280

    def nxt() -> float:
        nonlocal s
        s = (s * 9301 + 49297) % 233280
        return s / 233280

    return nxt


def _pin(x: float, y: float, s: float, op: float, color: str) -> str:
    """A map-pin glyph (teardrop + hole), tip anchored at (x, y)."""
    t = f"translate({x - 12 * s:.1f},{y - 23 * s:.1f}) scale({s})"
    body = (
        '<path d="M12 1C7.6 1 4 4.6 4 9c0 5.6 8 13.5 8 13.5S20 14.6 20 9c0-4.4-3.6-8-8-8z" '
        f'fill="#fff" fill-opacity="{op}"/>'
    )
    hole = f'<circle cx="12" cy="9" r="3" fill="{color}" fill-opacity="0.9"/>'
    return f'<g transform="{t}">{body}{hole}</g>'


def _motif(seed: int, color: str) -> str:
    """The localización + tech ground: a lat/long grid, located map pins on
    the coast, and octopus tentacle-lines reaching each one from the hub —
    Pulpo locating the whole market and surfacing the best.  Seeded per
    slide so every card is a different constellation."""
    rnd = _rng(seed * 9301 + 49297)
    W, H = 1080, 1350
    hub = (996, 1016)
    anchors = [(604, 168), (812, 236), (946, 470), (900, 690), (730, 120)]
    pins = [(ax + (rnd() * 70 - 35), ay + (rnd() * 56 - 28)) for ax, ay in anchors]
    feat_idx = 1  # one pin reads brighter as the surfaced best (no star/number)

    grid = []
    x = 90
    while x < W:
        grid.append(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}" stroke="#fff" stroke-opacity="0.06" stroke-width="1.6"/>')
        x += 150
    y = 110
    while y < H:
        grid.append(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" stroke="#fff" stroke-opacity="0.06" stroke-width="1.6"/>')
        y += 150

    lines = []
    for i, (px, py) in enumerate(pins):
        mx = (hub[0] + px) / 2 + (rnd() * 260 - 130)
        my = (hub[1] + py) / 2 + (rnd() * 160 - 80)
        feat = i == feat_idx
        lines.append(
            f'<path d="M {hub[0]} {hub[1]} Q {mx:.0f} {my:.0f} {px:.0f} {py:.0f}" fill="none" '
            f'stroke="#fff" stroke-opacity="{0.34 if feat else 0.15}" '
            f'stroke-width="{4.5 if feat else 3}" stroke-linecap="round"/>'
        )
        lines.append(
            f'<circle cx="{px:.0f}" cy="{py:.0f}" r="{7 if feat else 5}" '
            f'fill="#fff" fill-opacity="{0.5 if feat else 0.28}"/>'
        )

    ps = [
        _pin(px, py - 6, 2.8 if i == feat_idx else 1.9, 0.95 if i == feat_idx else 0.4, color)
        for i, (px, py) in enumerate(pins)
    ]

    coord = (
        '<text x="990" y="905" text-anchor="end" font-family="ui-monospace,monospace" '
        'font-size="25" fill="#fff" fill-opacity="0.42" letter-spacing="2">13.49°N · 89.31°W</text>'
    )
    hub_oct = (
        f'<g transform="translate({hub[0] - 150},{hub[1] - 150})">'
        '<svg width="300" height="300" viewBox="0 0 48 48" fill="#fff" fill-opacity="0.16">'
        '<path d="M24 8c-7 0-12 5-12 12v5c0 2-1 3-3 4-2 1.4-3 2.8-3 4.6 0 2 1.7 3.4 3.6 3.4 1.8 0 '
        '2.7-1.4 3-2.6.4 1.3 1.4 2.6 3 2.6 1.5 0 2.6-1.2 3-2.6.5 1.5 1.6 2.6 3.4 2.6s2.9-1.1 3.4-2.6c.4 '
        '1.4 1.5 2.6 3 2.6 1.6 0 2.6-1.3 3-2.6.3 1.2 1.2 2.6 3 2.6 1.9 0 3.6-1.4 3.6-3.4 0-1.8-1-3.2-3-'
        '4.6-2-1-3-2-3-4v-5c0-7-5-12-12-12Z"/></svg></g>'
    )
    return (
        '<svg viewBox="0 0 1080 1350" preserveAspectRatio="xMidYMid slice">'
        + "".join(grid) + hub_oct + "".join(lines) + "".join(ps) + coord + "</svg>"
    )


def _design(color: str, inner: str, grad: bool = False) -> str:
    # Seed the motif from the slide's own content → stable, distinct per slide.
    seed = zlib.crc32(inner.encode("utf-8"))
    cls = "slide design grad" if grad else "slide design"
    return (
        f'<div class="{cls}" style="--c:{color}">'
        f'<div class="lyr">{_motif(seed, color)}</div>'
        '<div class="lyr grain"></div>'
        '<div class="lyr tscrim"></div>'
        '<div class="lyr vig"></div>'
        f'<div class="content">{inner}</div>'
        f'{_BRAND}</div>'
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
