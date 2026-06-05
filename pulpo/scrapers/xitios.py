"""Xitios scraper — PRD C1.

Site: https://www.xitios.com.sv/propiedades/buscar?categoria%5B%5D=VEN&tipo%5B%5D=RAN

Calibration notes (2026-06-05):

- Catalog URL preserves the VEN (venta = for-sale) + RAN (range — all
  categories) URL-encoded filters across pagination. The default
  ``?page=N`` shape rebuilds them correctly via paginate()'s base-URL
  preservation.
- Detail-page URLs follow ``/propiedad/detalles/<slug>``. The catalog
  HTML repeats each href multiple times (photo / title / view-details
  links); the helper's in-page dedup pass folds them.
- **No JSON-LD anywhere.** Xitios renders neither catalog-level nor
  detail-level Schema.org. ``extract_strategy="detail_og_meta"`` pulls
  title / description / image from og: meta tags and applies per-source
  regex over og:description for price + area.
- Area unit conversion: xitios reports area as "varas cuadradas"
  (Salvadoran vara² ≈ 0.6987 m²) on many listings. ``og_area_unit_factor``
  applies the conversion only when the "varas cuadradas" pattern
  matched; the plain "m²" pattern stays at 1.0 — encoded by listing
  both patterns and applying the factor only when the varas pattern
  was the matching one. Implemented inline rather than per-pattern to
  keep the helper signature simple.
- ``force_vacation_gate=False`` — the catalog filter ``tipo=RAN``
  (range = all categories) makes xitios a BROAD SV source; the gate
  would over-trim. Aligns with the bundle's posture for similarly
  broad sources (vivolatam, citymax_sc, agentiz, realestate_au_sv).
"""
from __future__ import annotations

import re
from typing import Optional

from pulpo.agents import SOURCES, register
from pulpo.scrapers._skeleton_helper import (
    SkeletonConfig,
    SkeletonScraper,
    _parse_number as _to_float,
)
from pulpo.scrapers.lib import extract_og


_VARAS_RE = re.compile(r"([\d.,]+)\s*varas?\s*cuadradas?", re.IGNORECASE)
_M2_RE = re.compile(r"([\d.,]+)\s*(?:m\s*[²2]|metros\s*cuadrados)", re.IGNORECASE)
_VARA_TO_M2 = 0.698896  # Salvadoran vara² ≈ 0.6989 m²


class XitiosScraper(SkeletonScraper):
    CONFIG = SkeletonConfig(
        slug="xitios",
        base_url="https://www.xitios.com.sv",
        list_url=(
            "https://www.xitios.com.sv/propiedades/buscar"
            "?categoria%5B%5D=VEN&tipo%5B%5D=RAN"
        ),
        page_param="page",
        url_pattern=None,
        detail_url_pattern=(
            r'href="((?:https?://www\.xitios\.com\.sv)?'
            r'/propiedad/detalles/[a-z0-9\-]+)"'
        ),
        extract_strategy="detail_og_meta",
        og_price_patterns=(
            r"US\$\s*([\d.,]+)",
            r"\$\s*([\d.,]+)",
        ),
        og_area_patterns=(
            r"([\d.,]+)\s*(?:m\s*[²2]|metros\s*cuadrados)",
            r"([\d.,]+)\s*varas?\s*cuadradas?",
        ),
        target_discovery_patterns=(
            r"(\d[\d,.]*)\s+propiedades?",
            r"(\d[\d,.]*)\s+inmuebles?",
            r"(\d[\d,.]*)\s+resultados?",
            r"Mostrando\s+(\d[\d,.]*)",
        ),
        max_pages=100,
        force_vacation_gate=False,
    )

    def _extract_detail(self, body: str, url: str, *, strategy: str) -> Optional[dict]:
        """Override: pull og: meta + apply varas→m² conversion when the
        area capture matched the varas-cuadradas pattern.
        """
        og = extract_og(body) or {}
        if not og:
            return None
        description = og.get("description") or ""
        title = og.get("title") or ""
        text = f"{title}\n{description}"
        price_match = None
        for pat in self.CONFIG.og_price_patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                price_match = m
                break
        area_m2: Optional[float] = None
        raw_size_text: Optional[str] = None
        m_m2 = _M2_RE.search(text)
        if m_m2:
            area_m2 = _to_float(m_m2.group(1))
            raw_size_text = m_m2.group(0)
        else:
            m_vr = _VARAS_RE.search(text)
            if m_vr:
                v = _to_float(m_vr.group(1))
                if v is not None:
                    area_m2 = round(v * _VARA_TO_M2, 2)
                    raw_size_text = m_vr.group(0)
        photos = og.get("image") or []
        if isinstance(photos, str):
            photos = [photos]
        return {
            "source": self.CONFIG.slug,
            "source_id": url.rstrip("/").rsplit("/", 1)[-1] or "unknown",
            "url": url,
            "title": title,
            "description": description,
            "price_usd": _to_float(price_match.group(1)) if price_match else None,
            "area_m2": area_m2,
            "photo_urls": photos,
            "raw_size_text": raw_size_text,
            "property_type": None,
            "location_text": "",
        }


register(SOURCES, "xitios", XitiosScraper())


def crawl(limit: int = 30, offline: Optional[bool] = None) -> list[dict]:
    return XitiosScraper(offline=offline).crawl(limit)
