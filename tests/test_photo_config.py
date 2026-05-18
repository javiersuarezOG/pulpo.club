"""Validate pulpo/scrapers/photo_config.json against its schema.

Also enforces a drift guard: every configured `sources.<name>` must
match an actual scraper module in pulpo/scrapers/. This prevents typos
from silently shipping a no-op upgrade (the helper falls through to
defaults on unknown source names).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

SCRAPERS_DIR = REPO / "pulpo" / "scrapers"
CONFIG_PATH = SCRAPERS_DIR / "photo_config.json"
SCHEMA_PATH = SCRAPERS_DIR / "photo_config.schema.json"


def _scraper_module_names() -> set[str]:
    """Discover the 8 scraper module names by listing pulpo/scrapers/."""
    out: set[str] = set()
    for p in SCRAPERS_DIR.glob("*.py"):
        name = p.stem
        if name.startswith("_") or name == "__init__":
            continue
        out.add(name)
    return out


def test_photo_config_validates_against_schema():
    import jsonschema

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    jsonschema.validate(config, schema)


def test_every_configured_source_is_a_real_scraper():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    scrapers = _scraper_module_names()
    configured = set((config.get("sources") or {}).keys())
    unknown = configured - scrapers
    assert not unknown, (
        f"photo_config.json names sources that don't exist as scraper "
        f"modules: {sorted(unknown)} (known: {sorted(scrapers)})"
    )


def test_every_scraper_is_configured():
    """Reverse drift guard: a new scraper added without a config entry
    silently runs at `defaults`. Fail loudly so the operator is forced
    to declare per-site intent (even if that's just `noop`)."""
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    scrapers = _scraper_module_names()
    configured = set((config.get("sources") or {}).keys())
    missing = scrapers - configured
    assert not missing, (
        f"scrapers without a photo_config.json entry: {sorted(missing)}. "
        "Add a `noop` block at minimum so per-site intent is explicit."
    )
