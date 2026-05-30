"""Tests for pulpo/scrapers/_scrape_cache.py.

The cache fallback is load-bearing for the post-2026-05-30
realty + elagente revival path: the GCP self-hosted runner writes
records to web/data/scrape_cache/<slug>.json daily, and the main
nightly's crawl() consumes them when the on-Azure live fetch
would 403. These tests cover every branch of load_fresh_cache so a
regression in the fallback (or a subtle freshness-math bug) doesn't
silently shove the scrapers back into the WAF-blocked live path.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from pulpo.scrapers._scrape_cache import _parse_ts, load_fresh_cache  # noqa: E402


def _write_envelope(
    tmp: Path, slug: str, *, ts: str, records: list[dict] | None = None,
) -> Path:
    """Write a cache envelope at tmp/<slug>.json. Returns the path."""
    if records is None:
        records = [{"source_id": "1", "title": "t"}]
    path = tmp / f"{slug}.json"
    path.write_text(json.dumps({
        "ts":      ts,
        "source":  slug,
        "count":   len(records),
        "records": records,
    }))
    return path


# ── _parse_ts ─────────────────────────────────────────────────────────


def test_parse_ts_accepts_z_suffix():
    dt = _parse_ts("2026-05-30T01:34:12Z")
    assert dt is not None
    assert dt.tzinfo is timezone.utc
    assert dt.year == 2026 and dt.month == 5 and dt.day == 30


def test_parse_ts_accepts_iso_offset():
    dt = _parse_ts("2026-05-30T01:34:12+00:00")
    assert dt is not None
    assert dt.tzinfo is not None


def test_parse_ts_assumes_utc_for_naive_iso():
    # A future writer might forget the offset. The reader should
    # treat naive timestamps as UTC rather than crashing.
    dt = _parse_ts("2026-05-30T01:34:12")
    assert dt is not None
    assert dt.tzinfo is timezone.utc


def test_parse_ts_returns_none_for_garbage():
    assert _parse_ts("not a date") is None
    assert _parse_ts("") is None
    assert _parse_ts(None) is None  # type: ignore[arg-type]


# ── load_fresh_cache happy path ───────────────────────────────────────


def test_returns_records_when_fresh(tmp_path):
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    _write_envelope(tmp_path, "realtyelsalvador",
                    ts=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    records=[{"source_id": "1"}, {"source_id": "2"}])
    out = load_fresh_cache("realtyelsalvador", base_dir=tmp_path, now=now)
    assert out is not None
    assert len(out) == 2
    assert out[0]["source_id"] == "1"


def test_returns_records_at_exactly_freshness_window(tmp_path):
    """Boundary check: a cache exactly at the freshness ceiling is
    still considered fresh. Reduces the chance of a flaky cron-vs-
    nightly race where the shim's commit is 25h ± 30s old."""
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    _write_envelope(tmp_path, "elagente",
                    ts=(now - timedelta(hours=25)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    out = load_fresh_cache("elagente", base_dir=tmp_path, now=now,
                           freshness_hours=25)
    assert out is not None


# ── load_fresh_cache rejection paths ──────────────────────────────────


def test_returns_none_when_cache_missing(tmp_path):
    assert load_fresh_cache("realtyelsalvador", base_dir=tmp_path) is None


def test_returns_none_when_cache_unparseable(tmp_path, capsys):
    (tmp_path / "realtyelsalvador.json").write_text("{not valid json")
    out = load_fresh_cache("realtyelsalvador", base_dir=tmp_path)
    assert out is None
    # Diagnostic must surface so a corrupted cache is debuggable.
    err = capsys.readouterr().out
    assert "parse failed" in err


def test_returns_none_when_envelope_is_not_a_dict(tmp_path, capsys):
    (tmp_path / "realtyelsalvador.json").write_text(json.dumps(["a", "b"]))
    out = load_fresh_cache("realtyelsalvador", base_dir=tmp_path)
    assert out is None
    assert "not a dict" in capsys.readouterr().out


def test_returns_none_when_ts_missing(tmp_path, capsys):
    (tmp_path / "realtyelsalvador.json").write_text(
        json.dumps({"source": "realtyelsalvador", "records": [{"source_id": "1"}]})
    )
    out = load_fresh_cache("realtyelsalvador", base_dir=tmp_path)
    assert out is None
    assert "no usable ts" in capsys.readouterr().out


def test_returns_none_when_cache_is_stale(tmp_path, capsys):
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    _write_envelope(tmp_path, "realtyelsalvador",
                    ts=(now - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    out = load_fresh_cache("realtyelsalvador", base_dir=tmp_path, now=now)
    assert out is None
    err = capsys.readouterr().out
    assert "48.0h old" in err  # diagnostic includes the actual age


def test_returns_none_when_records_field_missing(tmp_path, capsys):
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    (tmp_path / "realtyelsalvador.json").write_text(json.dumps({
        "ts":     now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "realtyelsalvador",
        # no "records" key
    }))
    out = load_fresh_cache("realtyelsalvador", base_dir=tmp_path, now=now)
    assert out is None
    assert "no records" in capsys.readouterr().out


def test_returns_none_when_records_is_empty_list(tmp_path, capsys):
    """An empty-records envelope MUST be rejected — yielding [] would
    mask the scraper failure the main nightly is supposed to detect
    (it'd look like 'live fetch succeeded with 0 records' instead of
    'WAF blocked, cache empty')."""
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    _write_envelope(tmp_path, "realtyelsalvador",
                    ts=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    records=[])
    out = load_fresh_cache("realtyelsalvador", base_dir=tmp_path, now=now)
    assert out is None
    assert "no records" in capsys.readouterr().out


# ── freshness_hours override paths ────────────────────────────────────


def test_explicit_freshness_overrides_default(tmp_path):
    """A caller can request a tighter freshness window for ops
    experiments. Tighter window → same envelope rejected as stale."""
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    _write_envelope(tmp_path, "realtyelsalvador",
                    ts=(now - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    # 10h-old cache is fine under the 25h default…
    assert load_fresh_cache("realtyelsalvador", base_dir=tmp_path, now=now) is not None
    # …but stale under a 6h window.
    assert load_fresh_cache(
        "realtyelsalvador", base_dir=tmp_path, now=now, freshness_hours=6,
    ) is None


def test_env_var_freshness_override(tmp_path, monkeypatch):
    """The freshness window can also be overridden via env var so an
    operator can experiment without code changes."""
    monkeypatch.setenv("PULPO_SCRAPE_CACHE_FRESHNESS_HOURS", "1")
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    _write_envelope(tmp_path, "realtyelsalvador",
                    ts=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert load_fresh_cache("realtyelsalvador", base_dir=tmp_path, now=now) is None


def test_env_var_freshness_garbage_falls_back_to_default(tmp_path, monkeypatch):
    """A misconfigured env var must not crash the scraper. Garbage →
    default of 25h, and the cache is accepted."""
    monkeypatch.setenv("PULPO_SCRAPE_CACHE_FRESHNESS_HOURS", "not a number")
    now = datetime(2026, 5, 30, 12, 0, 0, tzinfo=timezone.utc)
    _write_envelope(tmp_path, "realtyelsalvador",
                    ts=(now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    out = load_fresh_cache("realtyelsalvador", base_dir=tmp_path, now=now)
    assert out is not None
