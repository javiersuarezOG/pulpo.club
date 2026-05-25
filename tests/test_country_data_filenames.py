"""PR-MC-3 — per-country output filename contract tests.

The pipeline now dual-writes every public-facing JSON output: the
legacy unified filename (e.g. ``ranked.json``) AND a per-country
variant (``ranked.SV.json``). PR-MC-4 will switch the frontend to
read the per-country file; PR-MC-5 will retire the legacy unified
file once nothing reads it.

These tests pin the filename rule (``data_filename``) and verify
that ``phase_write_outputs`` produces both filename forms with
byte-identical content.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pulpo.countries import data_filename


# ── data_filename helper ─────────────────────────────────────────────


def test_data_filename_basic_extension():
    assert data_filename("ranked.json", "SV") == "ranked.SV.json"


def test_data_filename_multi_dot_stem():
    """Filenames like ranked.list.json keep their compound stem; the
    country code is inserted before the LAST dot only.
    """
    assert data_filename("ranked.list.json", "SV") == "ranked.list.SV.json"


def test_data_filename_uppercases_country():
    """Lower-cased country code is normalized to upper for on-disk
    sorting consistency.
    """
    assert data_filename("ranked.json", "sv") == "ranked.SV.json"
    assert data_filename("ranked.json", "gT") == "ranked.GT.json"


def test_data_filename_legacy_when_cc_empty():
    """Empty or None cc returns the filename unchanged — single source
    of truth path for callers that don't yet know about the per-country
    variant (or for the legacy unified file).
    """
    assert data_filename("ranked.json", None) == "ranked.json"
    assert data_filename("ranked.json", "") == "ranked.json"


def test_data_filename_no_extension_appends_suffix():
    """Filenames without an extension (rare — e.g. a name that's all
    stem) still get the country code, appended as a dot-suffix.
    """
    assert data_filename("ranked", "SV") == "ranked.SV"


def test_data_filename_idempotent_keys():
    """Filenames containing the country letter sequence elsewhere don't
    confuse the helper — only the literal split position matters.
    """
    assert data_filename("preview.json", "SV") == "preview.SV.json"
    # Already-CC-suffixed filename gets a second suffix (caller's bug
    # to call us twice, but we behave deterministically)
    assert data_filename("ranked.SV.json", "SV") == "ranked.SV.SV.json"


# ── phase_write_outputs produces both filenames ──────────────────────


def _run_phase(tmp_path: Path):
    from automation.pipeline_steps import phase_write_outputs

    started = datetime.now(timezone.utc)
    web_data_dir = tmp_path / "web" / "data"
    samples_path = tmp_path / "samples" / "ranked.csv"

    phase_write_outputs(
        ranked=[],
        web_data_dir=web_data_dir,
        samples_path=samples_path,
        sources=[],
        per_source_count={},
        source_errors={},
        source_meta={},
        errors=[],
        started=started,
        finished=datetime.now(timezone.utc),
        offline=True,
        fixture_fallback_active=False,
        dropped=0,
        validation_by_type=None,
    )
    return web_data_dir


def test_phase_write_outputs_writes_legacy_and_per_country(tmp_path: Path):
    """Phase write should produce identical content under both the
    legacy ``ranked.json`` and the per-country ``ranked.SV.json``
    filename so PR-MC-4 can switch the FE to the per-country file
    without a data refresh.
    """
    web_data_dir = _run_phase(tmp_path)

    legacy = web_data_dir / "ranked.json"
    per_cc = web_data_dir / "ranked.SV.json"
    assert legacy.is_file(), "Legacy ranked.json must still be produced"
    assert per_cc.is_file(), "Per-country ranked.SV.json must be produced"
    assert legacy.read_bytes() == per_cc.read_bytes(), (
        "Per-country file must carry byte-identical content to the legacy "
        "file when the active country is SV (the only configured country)."
    )

    legacy_list = web_data_dir / "ranked.list.json"
    per_cc_list = web_data_dir / "ranked.list.SV.json"
    assert legacy_list.is_file()
    assert per_cc_list.is_file()
    assert legacy_list.read_bytes() == per_cc_list.read_bytes()

    legacy_lu = web_data_dir / "last_updated.json"
    per_cc_lu = web_data_dir / "last_updated.SV.json"
    assert legacy_lu.is_file()
    assert per_cc_lu.is_file()
    assert legacy_lu.read_bytes() == per_cc_lu.read_bytes()
    # Sanity: the file is well-formed JSON
    json.loads(legacy_lu.read_text(encoding="utf-8"))


def test_phase_write_outputs_keeps_run_history_unified(tmp_path: Path):
    """``run_history.json`` stays single-file across countries — it's
    an append-only audit log that spans the whole pipeline run, not a
    per-country snapshot. PR-MC-5 will add a ``country`` field to each
    row so it's filterable.
    """
    web_data_dir = _run_phase(tmp_path)

    assert (web_data_dir / "run_history.json").is_file()
    assert not (web_data_dir / "run_history.SV.json").exists(), (
        "run_history.json must stay unified — adding a per-country "
        "history file would split the audit log into N pieces and "
        "break the existing watchdog. Each row gets a country field "
        "in a follow-up PR instead."
    )
