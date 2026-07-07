"""
Tests for scripts/check_bilingual_coverage.py — the bilingual-coverage
canary that alerts (never blocks) on monolingual / untranslated listing
copy.

Deterministic + synthetic ONLY: these tests build their own record lists
and never read web/data/*.json. That keeps them from becoming a
data-driven CI blocker (a nightly that commits a bad ranked.json must not
turn every unrelated PR red — the anti-pattern documented for the
social-floor test). The live-data scan is the canary's job at runtime,
where a failure Slack-pages instead of blocking.

Coverage:
- a fully bilingual dataset passes
- a monolingual title/description/USP string is flagged
- a one-sided {en}/{es} dict is flagged (mono)
- an identical-across-locales description is flagged (untranslated)
- a short identical title is NOT flagged (language-neutral titles are ok)
- --strict exit code contract (fail=1, ok=0); default never blocks (0)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_bilingual_coverage as cov  # noqa: E402


def _write(tmp_path: Path, rows: list) -> Path:
    (tmp_path / "ranked.list.json").write_text(json.dumps(rows), encoding="utf-8")
    return tmp_path


_GOOD = {
    "title_canonical": {"en": "Ocean-view lot", "es": "Terreno con vista al mar"},
    "short_description_canonical": {
        "en": "Flat 500 m2 residential lot near Playa El Tunco, with paved access.",
        "es": "Terreno residencial plano de 500 m2 cerca de Playa El Tunco, con acceso pavimentado.",
    },
    "reasons_to_buy": [
        {"en": "Ocean views", "es": "Vistas al mar"},
        {"en": "Paved access", "es": "Acceso pavimentado"},
    ],
}


def test_fully_bilingual_passes(tmp_path):
    rep = cov.audit_file(_write(tmp_path, [_GOOD, dict(_GOOD)]) / "ranked.list.json")
    assert not cov.failing(rep, 99.0, 98.0)
    assert rep["pct"]["title"] == 100.0
    assert rep["identical_desc"] == 0


def test_monolingual_title_string_flagged(tmp_path):
    bad = dict(_GOOD, title_canonical="Raw Land · 500 m² · El Tunco")
    rep = cov.audit_file(_write(tmp_path, [bad]) / "ranked.list.json")
    fails = cov.failing(rep, 99.0, 98.0)
    assert any("title" in f for f in fails)
    assert rep["stats"]["title"]["mono"] == 1


def test_one_sided_dict_flagged(tmp_path):
    bad = dict(_GOOD, short_description_canonical={"en": "English only, no es side here."})
    rep = cov.audit_file(_write(tmp_path, [bad]) / "ranked.list.json")
    fails = cov.failing(rep, 99.0, 98.0)
    assert any("description" in f for f in fails)


def test_monolingual_usp_string_flagged(tmp_path):
    bad = dict(_GOOD, reasons_to_buy=["📉 Price reduced — negotiate from strength"])
    rep = cov.audit_file(_write(tmp_path, [bad]) / "ranked.list.json")
    assert any("usps" in f for f in cov.failing(rep, 99.0, 98.0))


def test_identical_description_flagged_as_untranslated(tmp_path):
    same = "Flat 500 m2 residential lot near Playa El Tunco with paved road access."
    bad = dict(_GOOD, short_description_canonical={"en": same, "es": same})
    rep = cov.audit_file(_write(tmp_path, [bad]) / "ranked.list.json")
    assert rep["identical_desc"] == 1
    assert any("identical" in f for f in cov.failing(rep, 99.0, 98.0))


def test_swapped_language_description_flagged(tmp_path):
    # en slot holds Spanish prose, es slot holds English prose → swapped.
    bad = dict(_GOOD, short_description_canonical={
        "en": "Terreno residencial plano de 500 metros cuadrados cerca de la playa con acceso.",
        "es": "Flat residential lot of 500 square meters near the beach with paved road access.",
    })
    rep = cov.audit_file(_write(tmp_path, [bad]) / "ranked.list.json")
    assert rep["swapped_desc"] == 1
    assert any("swapped" in f for f in cov.failing(rep, 99.0, 98.0))


def test_correct_language_description_not_swapped(tmp_path):
    rep = cov.audit_file(_write(tmp_path, [_GOOD]) / "ranked.list.json")
    assert rep["swapped_desc"] == 0


def test_short_identical_title_not_flagged(tmp_path):
    # A short language-neutral title matching across locales is legitimate.
    ok = dict(_GOOD, title_canonical={"en": "Villa 500", "es": "Villa 500"})
    rep = cov.audit_file(_write(tmp_path, [ok]) / "ranked.list.json")
    # title identical is fine (only descriptions are checked for identity)
    assert rep["identical_desc"] == 0
    assert not cov.failing(rep, 99.0, 98.0)


def test_strict_exit_codes(tmp_path):
    _write(tmp_path, [dict(_GOOD, title_canonical="mono string")])
    # default: never blocks
    assert cov.main(["--data-dir", str(tmp_path)]) == 0
    # strict: fails on a known-bad input
    assert cov.main(["--data-dir", str(tmp_path), "--strict"]) == 1
    # strict on a healthy dataset: passes
    _write(tmp_path, [_GOOD])
    assert cov.main(["--data-dir", str(tmp_path), "--strict"]) == 0
