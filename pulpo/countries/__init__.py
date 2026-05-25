"""Country manifests — single source of truth for what a country "is" in Pulpo.

Pulpo's pipeline + UI is single-country per deployment (one Vercel domain
serves one country). Adding a country = adding a JSON manifest in this
directory + flipping ``PULPO_ACTIVE_COUNTRY`` on the new deployment.

Layout
------
- ``pulpo/countries/<cc>.json``  — per-country reference data. ``<cc>`` is
  the lowercased ISO-3166-1 alpha-2 code (e.g. ``sv.json``).
- Each JSON file MUST validate against the schema enforced by
  ``CountryManifest.from_dict`` below (raises ``ValueError`` on missing
  required fields).
- A matching TS copy lives at ``web/app/config/countries/<cc>.json`` for
  the frontend bundle. Same content; keep both in sync. (CI guardrail
  added in a follow-up PR.)

Public API
----------
``load(cc)``    — load a single manifest by alpha-2 code.
``loaded()``    — every manifest discoverable in this directory.
``active()``    — the manifest selected by ``PULPO_ACTIVE_COUNTRY``
                  (default ``"SV"``). The pipeline + tests use this to
                  scope per-country runs.

Why JSON, not Python
--------------------
The TS frontend imports the same files. JSON is the lingua franca.
Python's slight ergonomic loss (dict access vs. dataclass) is paid back
by zero codegen + one source of truth across both stacks.
"""
from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_MANIFEST_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class CountryManifest:
    """Frozen view onto a single ``<cc>.json`` manifest.

    The ``raw`` dict is preserved so consumers that need a field this
    dataclass doesn't yet expose can read it directly without forcing a
    schema bump. Keep additions to required dataclass fields rare — most
    new data should land in ``raw`` first and only be promoted to a
    typed field once it has settled.
    """
    code: str               # ISO-3166-1 alpha-2 (uppercase: "SV", "GT")
    name_en: str
    name_es: str
    locale_es: str          # e.g. "es-SV" — Intl.NumberFormat seed for Spanish
    locale_en: str          # e.g. "en-US"
    currency: str           # ISO-4217 (e.g. "USD")
    centroid_lat: float
    centroid_lng: float
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    _REQUIRED: tuple[str, ...] = (
        "code", "name_en", "name_es", "locale_es", "locale_en",
        "currency", "centroid_lat", "centroid_lng",
    )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CountryManifest":
        missing = [k for k in cls._REQUIRED if k not in d]
        if missing:
            raise ValueError(
                f"CountryManifest missing required field(s): {missing!r}; "
                f"got keys {sorted(d.keys())!r}"
            )
        code = d["code"]
        if not isinstance(code, str) or len(code) != 2 or not code.isalpha():
            raise ValueError(
                f"CountryManifest.code must be ISO-3166-1 alpha-2; got {code!r}"
            )
        return cls(
            code=code.upper(),
            name_en=d["name_en"],
            name_es=d["name_es"],
            locale_es=d["locale_es"],
            locale_en=d["locale_en"],
            currency=d["currency"],
            centroid_lat=float(d["centroid_lat"]),
            centroid_lng=float(d["centroid_lng"]),
            raw=dict(d),
        )

    # ── Typed accessors over `raw` (PR-MC-1b) ────────────────────────
    # Each accessor returns an empty / safe-default container when the
    # manifest doesn't carry that section. Consumers can therefore drop
    # in a partial manifest for a new country (e.g. only `code` + names)
    # without crashing the pipeline — they'll simply get zero zones,
    # zero beaches, etc., until the manifest is filled in.

    def departments(self) -> dict[str, str]:
        """Normalized-name → canonical-name map for the country's
        first-level administrative subdivisions.

        SV uses 'departamentos' (e.g. 'la libertad' → 'La Libertad');
        other countries use 'provincias', 'cantones', etc. — the
        canonical-name string carries whatever casing/accent the country
        is comfortable rendering in UI.
        """
        v = self.raw.get("departments") or {}
        return dict(v) if isinstance(v, dict) else {}

    def zone_tier(self) -> dict[str, str]:
        """Canonical zone-slug → tier letter ('A'/'B'/'C').

        Consumed by ``pulpo/ranker_legs/location.py`` to base-score a
        listing's location. Unknown zones (slug absent here) fall
        through to the leg's UNKNOWN_TIER_BASE.
        """
        v = self.raw.get("zone_tier") or {}
        return dict(v) if isinstance(v, dict) else {}

    def vacation_zones(self) -> frozenset[str]:
        """Set of canonical zone slugs where house/condo listings are
        considered in-scope.

        Inland house/condo listings (zone slug absent here) are dropped
        at scraper parse time unless the title/description carries a
        WATERFRONT_KEYWORD. Land has no such gate — every land listing
        is in-scope regardless of zone.
        """
        v = self.raw.get("vacation_zones") or []
        return frozenset(v) if isinstance(v, (list, tuple, set, frozenset)) else frozenset()

    def coastal_zones(self) -> frozenset[str]:
        """Set of zone slugs on the actual ocean coast (strict subset
        of vacation_zones — excludes lakes).

        Used by the ``validation_bounds`` rule that flags
        suspiciously-large parcels in supply-limited beach areas. Lakes
        are excluded because lake parcels can legitimately be large
        (frontage on a lake doesn't compress lot sizes the way a
        beachfront strip does).
        """
        v = self.raw.get("coastal_zones") or []
        return frozenset(v) if isinstance(v, (list, tuple, set, frozenset)) else frozenset()

    def airports(self) -> dict[str, dict[str, Any]]:
        """Airport code → {name, lat, lng, operational} dict.

        Consumed by ``automation/distance_fields.py`` to compute the
        nearest-airport haversine for listings with lat/lng populated,
        and by ``pulpo/ranker_legs/location.py`` via the per-zone
        lookup in ``airport_distances_km`` for listings without coords.
        """
        v = self.raw.get("airports") or {}
        return dict(v) if isinstance(v, dict) else {}

    def airport_distances_km(self) -> dict[str, dict[str, float]]:
        """Zone slug → {airport_code → distance in km}.

        The static lookup that powers the location-leg's "near airport"
        bonus when the listing has no lat/lng. With coords, the live
        haversine in ``distance_fields.py`` is preferred.
        """
        v = self.raw.get("airport_distances_km") or {}
        return dict(v) if isinstance(v, dict) else {}

    def named_beaches(self) -> tuple[tuple[str, float, float], ...]:
        """Authoritative (name, lat, lng) triples for known beaches.

        Single source of truth for both (a) the dist_beach_km haversine
        reference set in ``automation/distance_fields.py``, and (b) the
        AUTHORITATIVE BEACH COORDINATES table injected into the LLM
        enrichment system prompt. Adding a beach here propagates to
        both — no per-call cost (the prompt is byte-cached at module
        import).
        """
        v = self.raw.get("named_beaches") or []
        out: list[tuple[str, float, float]] = []
        if isinstance(v, (list, tuple)):
            for entry in v:
                if (isinstance(entry, (list, tuple)) and len(entry) == 3
                        and isinstance(entry[0], str)):
                    out.append((entry[0], float(entry[1]), float(entry[2])))
        return tuple(out)

    def validation_bounds(self) -> dict[str, dict[str, tuple[float, float, float, float]]]:
        """Per-property-type validation bounds.

        Shape:  {ptype: {field: (drop_min, drop_max, flag_min, flag_max)}}

        Drives the type-bounds rule in ``automation/validation.py``:
        a record whose field falls outside the drop range is rejected;
        a record outside the flag range is kept with
        ``validation_status='flagged'``.
        """
        v = self.raw.get("validation_bounds") or {}
        if not isinstance(v, dict):
            return {}
        out: dict[str, dict[str, tuple[float, float, float, float]]] = {}
        for ptype, fields in v.items():
            if not isinstance(fields, dict):
                continue
            out[ptype] = {}
            for field_name, bounds in fields.items():
                if (isinstance(bounds, (list, tuple)) and len(bounds) == 4):
                    out[ptype][field_name] = tuple(float(x) for x in bounds)  # type: ignore[assignment]
        return out


def _manifest_path(cc: str) -> Path:
    return _MANIFEST_DIR / f"{cc.lower()}.json"


def load(cc: str) -> CountryManifest:
    """Load the manifest for ``cc`` (case-insensitive alpha-2)."""
    p = _manifest_path(cc)
    if not p.is_file():
        raise FileNotFoundError(
            f"No country manifest at {p}. Add it or check PULPO_ACTIVE_COUNTRY."
        )
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return CountryManifest.from_dict(data)


def loaded() -> list[CountryManifest]:
    """Every ``<cc>.json`` in this directory, sorted by code."""
    out: list[CountryManifest] = []
    for p in sorted(_MANIFEST_DIR.glob("*.json")):
        with p.open("r", encoding="utf-8") as f:
            data = json.load(f)
        out.append(CountryManifest.from_dict(data))
    return out


def active() -> CountryManifest:
    """The manifest selected by the ``PULPO_ACTIVE_COUNTRY`` env var.

    Defaults to ``"SV"`` so existing call sites that don't set the var
    keep working bit-identically. A missing manifest raises — better to
    fail loud than silently mis-resolve.
    """
    cc = os.environ.get("PULPO_ACTIVE_COUNTRY", "SV")
    return load(cc)
