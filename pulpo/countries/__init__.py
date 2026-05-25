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
