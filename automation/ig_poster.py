"""ig_poster.py — Direction A editorial poster renderer for IG batch 1.

Six HTML→PNG poster systems, all rendered through Playwright (Chromium
headless) at 1080×1350 (the IG carousel sweet spot).  Direction A locked
2026-05-26 — see ``pulpo-ig-3-style-directions.html`` for the comparison
that picked Editorial over Data Terminal / Streetwear Drop.

  - TYPO_MAX       headline-dominant.  Ink / paper / cream palettes.
                   Used for the intro post + diversifier heroes.
  - STICKER        photo full-bleed + sticker overlay.  Used for hero
                   listings where the photo carries the post.
  - POST_IT        photo + gold post-it note "el pulpo dejó esto".
                   Used for bargain alerts.
  - BIG_NUMBER     a single shock stat at 170pt.  Used for D7 mejor $/m².
  - RECEIPT        carousel cover styled as a printed receipt.  Used for
                   all 5 listicle cover slides + the wrap (D14).
  - MAP_MARK       silhouette of El Salvador with a zone highlighted.
                   Used for D12 Oriente roundup.

Public API:

    render_poster(candidate, listing, poster_type, palette, output_path)
      → Path                              # full render (Playwright)

    build_html(candidate, listing, poster_type, palette, ...)
      → str                               # pure; tests assert on this

build_html() is intentionally pure (no I/O, no browser) so unit tests
can run without a Chromium install.  The Playwright import lives inside
``_render_via_playwright`` so the module imports cleanly even when
chromium isn't on the box (local dev / unit-test CI without the
nightly's playwright install).

CLI:

    python3 -m automation.ig_poster \\
        --candidate-id remax__001461165132 \\
        --poster-type sticker \\
        --palette ink \\
        --output /tmp/poster.png

Hooks into PR-3's queue builder, which orchestrates the 14-poster batch.
"""
from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any, Optional

from automation._atomic import atomic_write_text
from pulpo.countries import active as _active_country
from automation.ig_units import (
    format_area_m2,
    format_price_per_m2,
    format_price_usd,
    format_zone_delta_pct,
)


# ── constants ──────────────────────────────────────────────────────────

# IG carousel slide aspect: 4:5 at 1080 wide → 1350 tall.
POSTER_W = 1080
POSTER_H = 1350

# Public poster-type identifiers.  Used as routing keys + as CSS class
# names on the wrapper div.  Don't rename without updating the queue
# builder (PR-3) and the admin widget (PR-3).
TYPO_MAX   = "typo_max"
STICKER    = "sticker"
POST_IT    = "post_it"
BIG_NUMBER = "big_number"
RECEIPT    = "receipt"
MAP_MARK   = "map_mark"

POSTER_TYPES = (TYPO_MAX, STICKER, POST_IT, BIG_NUMBER, RECEIPT, MAP_MARK)
PALETTES = ("ink", "paper", "cream")

# Image inputs live under web/photos/.  We use the .hero.jpg variant for
# sticker / post-it backgrounds because it's the up-scaled HD derivative.
DEFAULT_PHOTO_DIR = Path("web/photos")


# Pulpo glyph (the white-on-dark octopus mark).  Inlined so the poster
# is fully self-contained — no external image fetches at render time.
def _pulpo_svg(fill: str = "#ffffff", size: int = 32) -> str:
    return f'''
<svg viewBox="0 0 100 100" width="{size}" height="{size}" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="50" cy="34" rx="22" ry="24" fill="{fill}"/>
  <circle cx="42" cy="32" r="2.5" fill="white"/>
  <circle cx="58" cy="32" r="2.5" fill="white"/>
  <path d="M 30 54 Q 18 68 22 92" stroke="{fill}" stroke-width="4.5" fill="none" stroke-linecap="round"/>
  <path d="M 39 58 Q 30 78 36 94" stroke="{fill}" stroke-width="4.5" fill="none" stroke-linecap="round"/>
  <path d="M 47 60 Q 46 80 50 95" stroke="{fill}" stroke-width="4.5" fill="none" stroke-linecap="round"/>
  <path d="M 55 60 Q 56 80 62 94" stroke="{fill}" stroke-width="4.5" fill="none" stroke-linecap="round"/>
  <path d="M 62 58 Q 70 78 76 92" stroke="{fill}" stroke-width="4.5" fill="none" stroke-linecap="round"/>
  <path d="M 70 54 Q 82 68 80 88" stroke="{fill}" stroke-width="4.5" fill="none" stroke-linecap="round"/>
</svg>
'''.strip()


# ── shared CSS (ported verbatim from pulpo-ig-batch1-mockup-v4.html) ──

_BASE_CSS = """
:root{
  --paper:        oklch(1 0 0);
  --paper-2:      oklch(0.97 0.012 160);
  --paper-3:      oklch(0.94 0.018 160);
  --paper-cream:  oklch(0.96 0.025 85);
  --ink:          oklch(0.22 0.04 165);
  --ink-deep:     oklch(0.14 0.03 165);
  --ink-2:        oklch(0.38 0.035 165);
  --line:         oklch(0.90 0.015 160);
  --accent:       oklch(0.40 0.09 165);
  --accent-2:     oklch(0.62 0.20 25);
  --moss:         oklch(0.55 0.08 145);
  --gold:         oklch(0.72 0.13 80);
  --gold-deep:    oklch(0.55 0.13 70);
  --gold-soft:    oklch(0.86 0.10 80);
  --font-display: "Instrument Serif","Times New Roman",Georgia,serif;
  --font-sans:    "Inter",-apple-system,BlinkMacSystemFont,system-ui,sans-serif;
  --font-mono:    "JetBrains Mono","SFMono-Regular",Menlo,monospace;
  --font-marker:  "Permanent Marker","Caveat",cursive;
  --font-hand:    "Caveat",cursive;
  --font-receipt: "Courier Prime","Courier New",monospace;
}
*{box-sizing:border-box;margin:0;padding:0;}
html,body{width:1080px;height:1350px;background:transparent;font-family:var(--font-sans);}
.poster{width:1080px;height:1350px;position:relative;overflow:hidden;}

/* ============ TYPO_MAX ============ */
.poster.typo_max{padding:64px;display:flex;flex-direction:column;justify-content:space-between;}
.poster.typo_max.ink   {background:var(--ink);color:var(--paper);}
.poster.typo_max.paper {background:var(--paper-2);color:var(--ink);}
.poster.typo_max.cream {background:var(--paper-cream);color:var(--ink);}
.poster.typo_max .eye{font-family:var(--font-mono);font-size:24px;letter-spacing:.22em;font-weight:700;text-transform:uppercase;display:flex;align-items:center;gap:18px;}
.poster.typo_max.ink   .eye{color:var(--moss);}
.poster.typo_max.paper .eye{color:var(--ink-2);}
.poster.typo_max.cream .eye{color:var(--gold-deep);}
.poster.typo_max .eye .sep{opacity:.5;}
.poster.typo_max .stage{flex:1;display:flex;flex-direction:column;justify-content:center;gap:18px;}
.poster.typo_max .hook{font-family:var(--font-display);font-style:italic;font-size:60px;line-height:1.05;letter-spacing:-.005em;opacity:.85;}
.poster.typo_max .hero{font-family:var(--font-display);font-style:italic;font-size:220px;line-height:.88;letter-spacing:-.015em;font-weight:400;}
.poster.typo_max .punch{font-family:var(--font-display);font-style:italic;font-size:118px;line-height:.92;letter-spacing:-.015em;}
.poster.typo_max.ink   .punch{color:var(--gold);}
.poster.typo_max.paper .punch{color:var(--accent);}
.poster.typo_max.cream .punch{color:var(--accent-2);}
.poster.typo_max .foot{display:flex;justify-content:space-between;align-items:flex-end;}
.poster.typo_max .foot .price{font-family:var(--font-sans);font-weight:900;font-size:44px;letter-spacing:-.005em;}
.poster.typo_max.ink   .foot .price{color:var(--gold);}
.poster.typo_max.paper .foot .price{color:var(--accent-2);}
.poster.typo_max.cream .foot .price{color:var(--accent-2);}
.poster.typo_max .foot .loc{font-family:var(--font-mono);font-size:22px;letter-spacing:.10em;font-weight:700;opacity:.85;margin-top:8px;}

/* ============ STICKER ============ */
.poster.sticker{background:var(--ink);}
.poster.sticker .ph{position:absolute;inset:0;}
.poster.sticker .ph img{width:100%;height:100%;object-fit:cover;filter:saturate(1.04);}
.poster.sticker .ph::after{content:"";position:absolute;inset:0;background:linear-gradient(180deg, oklch(0 0 0/.06) 0%, oklch(0 0 0/.42) 100%);}
.poster.sticker .corner-stamp{position:absolute;top:48px;left:-32px;color:var(--paper);font-family:var(--font-mono);font-weight:800;font-size:26px;letter-spacing:.18em;text-transform:uppercase;padding:14px 44px 14px 60px;transform:rotate(-3deg);box-shadow:0 12px 36px oklch(0 0 0/.30);z-index:3;}
.poster.sticker .corner-stamp.green{background:var(--accent);}
.poster.sticker .corner-stamp.red{background:var(--accent-2);}
.poster.sticker .corner-stamp.gold{background:var(--gold-deep);}
.poster.sticker .scan-tag{position:absolute;top:160px;right:48px;font-family:var(--font-mono);font-size:22px;letter-spacing:.12em;font-weight:700;text-transform:uppercase;color:var(--paper);background:oklch(0 0 0/.55);padding:10px 18px;border-radius:10px;z-index:3;display:flex;align-items:center;gap:14px;}
.poster.sticker .scan-tag::before{content:"";display:inline-block;width:18px;height:18px;border-radius:50%;background:var(--moss);box-shadow:0 0 0 6px oklch(0.55 0.08 145 / .35);}
.poster.sticker .badge{position:absolute;right:60px;bottom:160px;z-index:3;transform:rotate(4deg);}
.poster.sticker .badge-inner{background:var(--paper);border:10px solid var(--ink);border-radius:36px;padding:36px 46px 30px;text-align:center;min-width:520px;box-shadow:0 32px 64px oklch(0 0 0/.40);}
.poster.sticker .badge-zone{font-family:var(--font-display);font-style:italic;font-size:80px;color:var(--ink);line-height:1;letter-spacing:-.01em;}
.poster.sticker .badge-data{font-family:var(--font-mono);font-size:22px;font-weight:700;color:var(--ink-2);letter-spacing:.08em;margin-top:14px;text-transform:uppercase;}
.poster.sticker .badge-pulpo{display:flex;justify-content:center;margin-bottom:14px;}
.poster.sticker .id-stamp{position:absolute;bottom:48px;left:48px;font-family:var(--font-mono);font-size:24px;color:var(--paper);background:oklch(0 0 0/.60);padding:12px 22px;border-radius:14px;letter-spacing:.10em;z-index:3;font-weight:700;text-transform:uppercase;}

/* ============ POST_IT ============ */
.poster.post_it{background:var(--ink);}
.poster.post_it .ph{position:absolute;inset:0;}
.poster.post_it .ph img{width:100%;height:100%;object-fit:cover;filter:saturate(.92) contrast(1.04);}
.poster.post_it .ph::after{content:"";position:absolute;inset:0;background:oklch(0 0 0/.12);}
.poster.post_it .note{position:absolute;top:72px;right:60px;width:64%;background:var(--gold-soft);background-image:linear-gradient(180deg, oklch(0.84 0.13 80) 0%, oklch(0.70 0.13 75) 100%);padding:50px 50px 40px;font-family:var(--font-marker);color:var(--ink);font-size:64px;line-height:1.18;transform:rotate(-2.5deg);box-shadow:0 36px 60px oklch(0 0 0/.45);z-index:3;white-space:pre-line;}
.poster.post_it .note .fold{position:absolute;top:0;right:0;width:78px;height:78px;background:linear-gradient(225deg, oklch(0.66 0.12 75) 0%, oklch(0.66 0.12 75) 50%, transparent 50%);box-shadow:-4px 4px 10px oklch(0 0 0/.15);}
.poster.post_it .note .sig{font-family:var(--font-hand);font-weight:700;font-size:72px;margin-top:22px;text-align:right;color:var(--ink-deep);}
.poster.post_it .id-stamp{position:absolute;bottom:48px;left:48px;font-family:var(--font-mono);font-size:24px;color:var(--paper);background:oklch(0 0 0/.60);padding:12px 22px;border-radius:14px;letter-spacing:.10em;z-index:3;font-weight:700;text-transform:uppercase;}
.poster.post_it .alert-stripe{position:absolute;top:50px;left:-34px;font-family:var(--font-mono);font-weight:800;font-size:26px;letter-spacing:.18em;text-transform:uppercase;padding:14px 40px 14px 56px;transform:rotate(-3deg);background:var(--accent-2);color:var(--paper);box-shadow:0 12px 36px oklch(0 0 0/.30);z-index:4;}

/* ============ BIG_NUMBER ============ */
.poster.big_number{padding:64px;display:flex;flex-direction:column;justify-content:space-between;}
.poster.big_number.gold{background:var(--gold);color:var(--ink);}
.poster.big_number.ink {background:var(--ink);color:var(--paper);}
.poster.big_number.red {background:var(--accent-2);color:var(--paper);}
.poster.big_number .eye{font-family:var(--font-mono);font-size:26px;letter-spacing:.22em;text-transform:uppercase;font-weight:800;}
.poster.big_number.gold .eye{color:var(--ink-deep);}
.poster.big_number.ink  .eye{color:var(--gold);}
.poster.big_number.red  .eye{color:var(--gold-soft);}
.poster.big_number .stage{flex:1;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;}
.poster.big_number .num{font-family:var(--font-display);font-style:italic;font-size:440px;line-height:.82;letter-spacing:-.04em;font-weight:400;}
.poster.big_number .ctx{font-family:var(--font-display);font-style:italic;font-size:68px;line-height:1.1;margin-top:28px;opacity:.88;letter-spacing:-.005em;max-width:90%;}
.poster.big_number .foot{display:flex;justify-content:space-between;align-items:flex-end;}
.poster.big_number .foot .l{font-family:var(--font-mono);font-size:22px;letter-spacing:.10em;font-weight:700;text-transform:uppercase;line-height:1.5;}

/* ============ RECEIPT ============ */
.poster.receipt{background:var(--paper-cream);padding:0;}
.poster.receipt.ink{background:var(--ink);color:var(--paper);}
.poster.receipt .paper-bg{position:absolute;inset:0;background-image:repeating-linear-gradient(0deg, transparent 0, transparent 64px, oklch(0 0 0/.018) 64px, oklch(0 0 0/.018) 66px);}
.poster.receipt.ink .paper-bg{background-image:repeating-linear-gradient(0deg, transparent 0, transparent 64px, oklch(1 0 0/.04) 64px, oklch(1 0 0/.04) 66px);}
.poster.receipt .content{position:absolute;inset:0;padding:80px 88px 70px;font-family:var(--font-receipt);color:var(--ink);display:flex;flex-direction:column;}
.poster.receipt.ink .content{color:var(--paper);}
.poster.receipt .perf{border-top:4px dashed var(--ink);border-bottom:4px dashed var(--ink);height:0;margin:0;}
.poster.receipt.ink .perf{border-color:var(--gold);}
.poster.receipt .head{text-align:center;padding:0 0 28px;}
.poster.receipt .head .brand{font-family:var(--font-receipt);font-weight:700;font-size:30px;letter-spacing:.18em;text-transform:uppercase;}
.poster.receipt .head .title{font-family:var(--font-display);font-style:italic;font-weight:400;font-size:120px;line-height:1;margin-top:18px;letter-spacing:-.01em;}
.poster.receipt.ink .head .title{color:var(--gold);}
.poster.receipt .head .sub{font-family:var(--font-receipt);font-size:24px;letter-spacing:.10em;margin-top:18px;opacity:.7;text-transform:uppercase;}
.poster.receipt .items{flex:1;display:flex;flex-direction:column;justify-content:center;padding:30px 12px;gap:24px;}
.poster.receipt .item{display:grid;grid-template-columns:80px 1fr auto;gap:30px;font-family:var(--font-receipt);font-size:34px;line-height:1.2;align-items:baseline;}
.poster.receipt .item .n{font-weight:700;}
.poster.receipt .item .desc{letter-spacing:.02em;}
.poster.receipt .item .desc small{display:block;font-size:24px;opacity:.65;letter-spacing:.04em;margin-top:6px;}
.poster.receipt .item .pr{font-weight:700;font-size:36px;}
.poster.receipt.ink .item .pr{color:var(--gold);}
.poster.receipt .totals{padding:28px 12px 10px;font-family:var(--font-receipt);font-size:30px;letter-spacing:.06em;display:grid;grid-template-columns:1fr auto;gap:18px;}
.poster.receipt .totals .row{display:contents;}
.poster.receipt .totals .row b{font-weight:700;}
.poster.receipt .totals .total{font-weight:700;font-size:36px;letter-spacing:.08em;}
.poster.receipt .footer-r{text-align:center;padding-top:28px;font-family:var(--font-receipt);font-size:24px;letter-spacing:.10em;text-transform:uppercase;opacity:.75;}
.poster.receipt .footer-r .glyph{display:flex;justify-content:center;margin-top:14px;opacity:.7;}
.poster.receipt .tearline{font-family:var(--font-mono);text-align:center;font-size:24px;letter-spacing:.4em;opacity:.5;padding-top:18px;}

/* ============ MAP_MARK ============ */
.poster.map_mark{background:var(--paper-cream);padding:64px;display:flex;flex-direction:column;justify-content:space-between;color:var(--ink);position:relative;}
.poster.map_mark .eye{font-family:var(--font-mono);font-size:24px;letter-spacing:.22em;text-transform:uppercase;font-weight:700;color:var(--accent-2);}
.poster.map_mark .map-wrap{flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;position:relative;}
.poster.map_mark .map-wrap svg{width:78%;height:auto;max-width:820px;display:block;}
.poster.map_mark .zone-label{font-family:var(--font-display);font-style:italic;font-size:160px;line-height:.95;letter-spacing:-.015em;color:var(--accent-2);margin-top:18px;}
.poster.map_mark .foot{display:flex;justify-content:space-between;align-items:flex-end;}
.poster.map_mark .foot .info{font-family:var(--font-mono);font-size:24px;letter-spacing:.10em;text-transform:uppercase;color:var(--ink-2);font-weight:700;line-height:1.4;}
.poster.map_mark .foot .info b{color:var(--accent-2);}
""".strip()


# Google fonts <link>.  Listed at module scope so build_html() doesn't
# rebuild the string per render — and so tests can grep for the expected
# families with one source of truth.
_FONTS_LINK = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Instrument+Serif:ital@0;1&'
    'family=Inter:wght@400;700;800;900&'
    'family=JetBrains+Mono:wght@500;700;800&'
    'family=Permanent+Marker&'
    'family=Caveat:wght@600;700&'
    'family=Courier+Prime:wght@400;700&'
    'display=swap" rel="stylesheet">'
)


# ── helpers ────────────────────────────────────────────────────────────

def _listing_n(candidate: dict) -> str:
    """'LISTING N° 011' from candidate.rank.  Zero-padded 3 digits to
    keep the eyebrow width stable across the carousel."""
    rank = candidate.get("rank")
    if rank is None:
        return "LISTING N° ???"
    return f"LISTING N° {int(rank):03d}"


def _zone_label(candidate: dict) -> str:
    """Human zone for the loc strip.  Falls back to department."""
    return (candidate.get("zone") or candidate.get("department") or _active_country().name_en).upper()


def _encode_photo_as_data_url(photo_path: Path) -> str:
    """Read a local image and return a base64 data URL so the poster
    HTML stays self-contained (no file:// or relative paths) when
    Playwright loads it via ``set_content``."""
    raw = photo_path.read_bytes()
    suffix = photo_path.suffix.lstrip(".").lower()
    mime = "image/jpeg" if suffix in ("jpg", "jpeg") else f"image/{suffix}"
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _resolve_photo_url(
    candidate: dict,
    listing: dict,
    photo_url: Optional[str],
    photo_dir: Path,
) -> str:
    """Order of preference: explicit photo_url → local hero file → first
    photo_urls entry.  Returns a string usable in <img src>."""
    if photo_url:
        return photo_url
    src = candidate.get("source") or listing.get("source")
    sid = candidate.get("source_id") or listing.get("source_id")
    if src and sid:
        hero = photo_dir / f"{src}_{sid}.hero.jpg"
        if hero.exists():
            return _encode_photo_as_data_url(hero)
    urls = listing.get("photo_urls") or []
    if urls:
        return urls[0]
    return ""   # template falls back to the dark backdrop


def _html_escape(text: Any) -> str:
    """Minimal HTML escape — covers the four reserved characters that
    matter in attribute + text content.  Sufficient because all our
    inputs are scraped real-estate text, not arbitrary user content."""
    if text is None:
        return ""
    s = str(text)
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


# ── per-type HTML body builders ────────────────────────────────────────

def _body_typo_max(c: dict, listing: dict, palette: str, overrides: dict) -> str:
    eye = overrides.get("eyebrow") or f"PULPO · {_listing_n(c)}"
    hook = overrides.get("hook") or "Una hectárea cruda."
    hero = overrides.get("hero") or format_area_m2(c.get("area_m2"))
    punch = overrides.get("punch") or "vista al mar."
    price = overrides.get("price") or format_price_usd(c.get("price_usd"))
    loc = overrides.get("loc") or _zone_label(c)
    glyph_fill = "#ffffff" if palette == "ink" else "#1d2a26"

    return f'''
<div class="poster typo_max {palette}">
  <div class="eye">
    <span>PULPO</span>
    <span class="sep">·</span>
    <span>{_html_escape(eye.replace("PULPO · ", "")) if eye.startswith("PULPO · ") else _html_escape(eye)}</span>
  </div>
  <div class="stage">
    <div class="hook">{_html_escape(hook)}</div>
    <div class="hero">{_html_escape(hero)}</div>
    <div class="punch">{_html_escape(punch)}</div>
  </div>
  <div class="foot">
    <div>
      <div class="price">{_html_escape(price)}</div>
      <div class="loc">{_html_escape(loc)}</div>
    </div>
    {_pulpo_svg(glyph_fill, 72)}
  </div>
</div>
'''.strip()


def _body_sticker(c: dict, listing: dict, palette: str, overrides: dict) -> str:
    """palette only affects the corner stamp colour for this system."""
    photo_src = overrides.get("photo_src", "")
    stamp_colour = {"ink": "green", "paper": "red", "cream": "gold"}.get(palette, "green")
    stamp_label = overrides.get("stamp") or f"★ TOP RANK · #{int(c.get('rank') or 0)} ★"
    scan_tag = overrides.get("scan_tag") or f"TENTÁCULO · {_zone_label(c)}"
    badge_zone = overrides.get("badge_zone") or _zone_label(c)
    area_str = format_area_m2(c.get("area_m2"))
    price_str = format_price_usd(c.get("price_usd"))
    badge_data = overrides.get("badge_data") or f"{area_str} · {price_str}"
    id_stamp = overrides.get("id_stamp") or _listing_n(c)

    img_html = f'<img src="{_html_escape(photo_src)}"/>' if photo_src else ""
    return f'''
<div class="poster sticker">
  <div class="ph">{img_html}</div>
  <div class="corner-stamp {stamp_colour}">{_html_escape(stamp_label)}</div>
  <div class="scan-tag">{_html_escape(scan_tag)}</div>
  <div class="badge">
    <div class="badge-inner">
      <div class="badge-pulpo">{_pulpo_svg("#1d2a26", 76)}</div>
      <div class="badge-zone">{_html_escape(badge_zone)}</div>
      <div class="badge-data">{_html_escape(badge_data)}</div>
    </div>
  </div>
  <div class="id-stamp">{_html_escape(id_stamp)}</div>
</div>
'''.strip()


def _body_post_it(c: dict, listing: dict, palette: str, overrides: dict) -> str:
    photo_src = overrides.get("photo_src", "")
    alert = overrides.get("alert") or f"ALERTA · {format_zone_delta_pct(c.get('price_vs_zone_pct'))}"
    note = overrides.get("note") or (
        f"{format_area_m2(c.get('area_m2'))} en {_zone_label(c).title()}.\n\n"
        f"{format_zone_delta_pct(c.get('price_vs_zone_pct'))} por metro vs su zona."
    )
    sig = overrides.get("sig") or "— el pulpo"
    id_stamp = overrides.get("id_stamp") or f"{_listing_n(c)} · {_zone_label(c)}"

    img_html = f'<img src="{_html_escape(photo_src)}"/>' if photo_src else ""
    return f'''
<div class="poster post_it">
  <div class="ph">{img_html}</div>
  <div class="alert-stripe">{_html_escape(alert)}</div>
  <div class="note">
    <div class="fold"></div>
    <div>{_html_escape(note)}</div>
    <div class="sig">{_html_escape(sig)}</div>
  </div>
  <div class="id-stamp">{_html_escape(id_stamp)}</div>
</div>
'''.strip()


def _body_big_number(c: dict, listing: dict, palette: str, overrides: dict) -> str:
    eye = overrides.get("eyebrow") or f"PULPO · {_listing_n(c)}"
    num = overrides.get("number") or format_price_per_m2(c.get("price_per_m2"))
    ctx = overrides.get("context") or "por metro cuadrado."
    foot_l = overrides.get("foot_left") or (
        f"{_zone_label(c)} · {_listing_n(c)}<br>"
        f"{format_area_m2(c.get('area_m2'))} · {format_price_usd(c.get('price_usd'))}"
    )
    glyph_fill = "#1d2a26" if palette == "gold" else "#ffffff"

    return f'''
<div class="poster big_number {palette}">
  <div class="eye">{_html_escape(eye)}</div>
  <div class="stage">
    <div class="num">{_html_escape(num)}</div>
    <div class="ctx">{_html_escape(ctx)}</div>
  </div>
  <div class="foot">
    <div class="l">{foot_l}</div>
    {_pulpo_svg(glyph_fill, 72)}
  </div>
</div>
'''.strip()


def _body_receipt(c: dict, listing: dict, palette: str, overrides: dict) -> str:
    """Receipt mostly drives off `overrides` since it's a listicle (a
    receipt for a SET of listings, not a single one).  The queue builder
    in PR-3 will populate items[] explicitly; this builder just renders."""
    title = overrides.get("title") or "Top 5"
    sub = overrides.get("subtitle") or "5 TERRENOS · CURADOS POR RANKING"
    brand = overrides.get("brand") or "PULPO · TOP 5"
    items = overrides.get("items") or []   # [{n, desc, sub, price}, ...]
    totals = overrides.get("totals") or []  # [{label, value}, ...]
    footer = overrides.get("footer") or "pulpo.club"
    mode = "ink" if palette == "ink" else ""

    items_html = "\n".join(
        f'<div class="item">'
        f'<span class="n">{_html_escape(it.get("n", ""))}</span>'
        f'<span class="desc">{_html_escape(it.get("desc", ""))}'
        f'<small>{_html_escape(it.get("sub", ""))}</small></span>'
        f'<span class="pr">{_html_escape(it.get("price", ""))}</span>'
        f'</div>'
        for it in items
    )
    totals_rows = "\n".join(
        f'<div class="row"><b>{_html_escape(t.get("label",""))}</b>'
        f'<b>{_html_escape(t.get("value",""))}</b></div>'
        for t in totals
    )
    glyph_fill = "#ffffff" if palette == "ink" else "#1d2a26"

    return f'''
<div class="poster receipt {mode}">
  <div class="paper-bg"></div>
  <div class="content">
    <div class="head">
      <div class="brand">{_html_escape(brand)}</div>
      <div class="title">{_html_escape(title)}</div>
      <div class="sub">{_html_escape(sub)}</div>
    </div>
    <div class="perf"></div>
    <div class="items">{items_html}</div>
    <div class="perf"></div>
    <div class="totals">{totals_rows}</div>
    <div class="footer-r">
      {_html_escape(footer)}
      <div class="glyph">{_pulpo_svg(glyph_fill, 54)}</div>
    </div>
    <div class="tearline">· · · · · · · · · · · · · · · · · · · · · · · · · · · ·</div>
  </div>
</div>
'''.strip()


def _body_map_mark(c: dict, listing: dict, palette: str, overrides: dict) -> str:
    """Stylised El Salvador outline.  Coords match the v4 mockup so the
    feed-rendered poster keeps continuity with the design we approved."""
    eye = overrides.get("eyebrow") or f"PULPO · TENTÁCULO {_zone_label(c)}"
    label = overrides.get("zone_label") or _zone_label(c).title()
    info_html = overrides.get("info_html") or (
        f"{format_area_m2(c.get('area_m2'))} · "
        f"<b>{format_price_usd(c.get('price_usd'))}</b>"
    )
    region = overrides.get("region", "oriente").lower()
    region_paths = _MAP_REGIONS.get(region, _MAP_REGIONS["oriente"])

    return f'''
<div class="poster map_mark">
  <div class="eye">{_html_escape(eye)}</div>
  <div class="map-wrap">
    <svg viewBox="0 0 360 180" xmlns="http://www.w3.org/2000/svg">
      <path d="M 20 80 Q 28 60 50 58 Q 75 50 100 55 Q 130 48 160 56 Q 195 52 225 62 Q 260 60 290 70 Q 320 78 345 95 L 340 110 Q 320 120 295 125 Q 270 130 240 132 Q 210 138 180 138 Q 150 142 120 138 Q 90 138 65 130 Q 40 122 25 105 Z"
            fill="oklch(0.94 0.018 160)" stroke="oklch(0.50 0.025 165)" stroke-width="1.5"/>
      {region_paths}
    </svg>
    <div class="zone-label">{_html_escape(label)}.</div>
  </div>
  <div class="foot">
    <div class="info">{info_html}</div>
    {_pulpo_svg("#1d2a26", 72)}
  </div>
</div>
'''.strip()


# Stylised region overlays for MAP_MARK.  Each entry is the SVG fragment
# that highlights the corresponding region.  Coordinates match the v4
# mockup's drawing; new regions can be added without touching the body.
_MAP_REGIONS = {
    "oriente":
        '<path d="M 200 60 Q 230 60 260 68 Q 290 72 320 80 Q 340 90 345 100 L 340 112 '
        'Q 318 122 290 128 Q 260 132 230 134 Q 210 134 200 130 L 198 100 Z" '
        'fill="oklch(0.62 0.20 25)" opacity="0.86" stroke="oklch(0.40 0.18 25)" stroke-width="1.5"/>'
        '<g transform="translate(270 95)"><circle cx="0" cy="0" r="6" fill="oklch(0.22 0.04 165)"/>'
        '<circle cx="0" cy="0" r="2" fill="#fff"/></g>',
    "central":
        '<path d="M 100 70 Q 130 65 160 70 Q 195 70 215 80 L 215 115 Q 200 122 175 122 '
        'Q 145 125 120 120 Q 100 115 95 100 Z" '
        'fill="oklch(0.62 0.20 25)" opacity="0.86" stroke="oklch(0.40 0.18 25)" stroke-width="1.5"/>'
        '<g transform="translate(155 95)"><circle cx="0" cy="0" r="6" fill="oklch(0.22 0.04 165)"/>'
        '<circle cx="0" cy="0" r="2" fill="#fff"/></g>',
    "occidente":
        '<path d="M 20 80 Q 28 60 50 58 Q 75 50 100 55 Q 110 60 115 80 L 115 115 '
        'Q 100 120 75 118 Q 50 116 30 105 Q 20 95 20 80 Z" '
        'fill="oklch(0.62 0.20 25)" opacity="0.86" stroke="oklch(0.40 0.18 25)" stroke-width="1.5"/>'
        '<g transform="translate(70 92)"><circle cx="0" cy="0" r="6" fill="oklch(0.22 0.04 165)"/>'
        '<circle cx="0" cy="0" r="2" fill="#fff"/></g>',
}


_DISPATCH = {
    TYPO_MAX:   _body_typo_max,
    STICKER:    _body_sticker,
    POST_IT:    _body_post_it,
    BIG_NUMBER: _body_big_number,
    RECEIPT:    _body_receipt,
    MAP_MARK:   _body_map_mark,
}


# ── public API ─────────────────────────────────────────────────────────

def build_html(
    candidate: dict,
    listing: Optional[dict] = None,
    poster_type: str = TYPO_MAX,
    palette: str = "ink",
    *,
    photo_url: Optional[str] = None,
    overrides: Optional[dict] = None,
    photo_dir: Path = DEFAULT_PHOTO_DIR,
) -> str:
    """Build the full HTML document for one poster.  Pure function — no
    I/O except the photo base64-encode for sticker / post-it, which is
    bounded by the input photo path.

    `overrides` lets the caption writer (or the queue builder) inject
    arbitrary text.  E.g. for TYPO_MAX the writer can pass
    ``{"hook": "Catorce hallazgos.", "hero": "Drop 01"}`` to override
    the default headline derived from the listing fields."""
    if poster_type not in _DISPATCH:
        raise ValueError(f"unknown poster_type {poster_type!r}; valid: {POSTER_TYPES}")
    if palette not in PALETTES and poster_type not in (STICKER, BIG_NUMBER, RECEIPT):
        # STICKER ignores palette (uses photo); BIG_NUMBER accepts
        # gold/ink/red separately; RECEIPT only honours ink vs default.
        raise ValueError(f"unknown palette {palette!r}; valid: {PALETTES}")
    listing = listing or {}
    overrides = dict(overrides or {})

    # Resolve photo upfront for sticker / post_it.  Allows tests to
    # pass an explicit photo_url and skip filesystem entirely.
    if poster_type in (STICKER, POST_IT) and "photo_src" not in overrides:
        overrides["photo_src"] = _resolve_photo_url(candidate, listing, photo_url, photo_dir)

    body_builder = _DISPATCH[poster_type]
    body = body_builder(candidate, listing, palette, overrides)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
{_FONTS_LINK}
<style>{_BASE_CSS}</style>
</head>
<body>
{body}
</body>
</html>"""


def _render_via_playwright(
    html: str,
    output_path: Path,
    *,
    width: int = POSTER_W,
    height: int = POSTER_H,
) -> Path:
    """Render `html` to a PNG at `output_path` using headless Chromium.

    Lazy-imports playwright so module load doesn't require the package.
    Fails loudly if playwright is missing — the caller is expected to
    have ``pip install playwright && playwright install chromium`` done
    (the nightly workflow already does this; see pulpo-nightly.yml)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:                                      # pragma: no cover
        raise RuntimeError(
            "ig_poster.render_poster requires `playwright` + chromium. "
            "Install: pip install playwright==1.49.1 && playwright install chromium"
        ) from e

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,                       # 1080×1350 already HD enough
            )
            page = context.new_page()
            page.set_content(html, wait_until="networkidle")
            # Belt-and-suspenders: also wait for web fonts.  Without
            # this, headless screenshots sometimes capture the fallback
            # serif (Georgia) instead of Instrument Serif.
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(output_path), full_page=False, omit_background=False)
        finally:
            browser.close()
    return output_path


def render_poster(
    candidate: dict,
    listing: Optional[dict] = None,
    poster_type: str = TYPO_MAX,
    palette: str = "ink",
    output_path: Optional[Path] = None,
    *,
    photo_url: Optional[str] = None,
    overrides: Optional[dict] = None,
    photo_dir: Path = DEFAULT_PHOTO_DIR,
) -> Path:
    """Full render: build HTML, write through Playwright to a PNG.

    Default output_path resolves to ``web/data/ig_assets/{listing_id}/
    poster_{poster_type}_{palette}.png`` so the publisher can fetch by
    convention without an explicit lookup."""
    html = build_html(
        candidate, listing, poster_type, palette,
        photo_url=photo_url, overrides=overrides, photo_dir=photo_dir,
    )
    if output_path is None:
        lid = candidate.get("listing_id") or "unknown"
        output_path = (
            Path("web/data/ig_assets") / lid
            / f"poster_{poster_type}_{palette}.png"
        )
    return _render_via_playwright(html, output_path)


# ── CLI ────────────────────────────────────────────────────────────────

def _find_candidate(candidates_path: Path, candidate_id: str) -> dict:
    payload = json.loads(candidates_path.read_text(encoding="utf-8"))
    for c in payload.get("candidates", []):
        if c.get("listing_id") == candidate_id:
            return c
    raise SystemExit(f"candidate {candidate_id!r} not found in {candidates_path}")


def _find_listing(ranked_path: Path, candidate: dict) -> dict:
    """Look up the full listing record from ranked.json.  Used so the
    poster has access to fields outside the slim candidate (e.g.
    photo_urls)."""
    rows = json.loads(ranked_path.read_text(encoding="utf-8"))
    src, sid = candidate.get("source"), candidate.get("source_id")
    for li in rows:
        if li.get("source") == src and li.get("source_id") == sid:
            return li
    return {}


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render one IG poster to PNG (Direction A editorial)."
    )
    parser.add_argument(
        "--candidates", type=Path, default=Path("web/data/ig_candidates.json"),
    )
    parser.add_argument(
        "--ranked", type=Path, default=Path("web/data/ranked.json"),
    )
    parser.add_argument("--candidate-id", required=True, help="e.g. remax__001461165132")
    parser.add_argument(
        "--poster-type", default=TYPO_MAX, choices=POSTER_TYPES,
    )
    parser.add_argument(
        "--palette", default="ink", choices=("ink", "paper", "cream", "gold", "red"),
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output PNG path (default web/data/ig_assets/{id}/poster_{type}_{palette}.png)",
    )
    parser.add_argument(
        "--html-only", action="store_true",
        help="Skip the browser; emit the HTML next to --output (.html).",
    )
    args = parser.parse_args(argv)

    candidate = _find_candidate(args.candidates, args.candidate_id)
    listing = _find_listing(args.ranked, candidate)

    if args.html_only:
        html = build_html(candidate, listing, args.poster_type, args.palette)
        out = args.output or Path(f"/tmp/poster_{args.candidate_id}.html")
        if out.suffix != ".html":
            out = out.with_suffix(".html")
        atomic_write_text(out, html)
        print(f"[ig_poster] wrote HTML to {out}")
        return 0

    out = render_poster(
        candidate, listing, args.poster_type, args.palette, args.output,
    )
    print(f"[ig_poster] rendered {out}  ({_human_size(out)})")
    return 0


def _human_size(p: Path) -> str:
    if not p.exists():
        return "missing"
    size = p.stat().st_size
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


if __name__ == "__main__":
    raise SystemExit(main())


# Defensive: re-export the dispatch map so tests can monkeypatch it
# without poking into private state.  Plus a sanity assertion that every
# poster type has a builder registered — guards against typo regressions
# on future system additions.
assert set(_DISPATCH) == set(POSTER_TYPES), (
    "POSTER_TYPES and _DISPATCH have drifted"
)
