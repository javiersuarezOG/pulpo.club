"""Tests for the pure-function URL drift classifier (PR-D1).

The classifier is intentionally network-free — every test below
constructs ProbeResult + Baseline objects directly and asserts on the
ClassifiedProbe output. Network probing is exercised separately by
``scripts/check_source_urls.py`` against the live registry.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from automation.url_drift_sentinel import (
    Baseline,
    KNOWN_DRIFT_STATES,
    ProbeResult,
    SIZE_DRIFT_THRESHOLD,
    classify,
    load_baseline,
    refresh_baseline,
    state_path_for,
    write_state,
    _normalize_url,
)


# ---------- Helpers ----------

def _probe(
    source: str = "src",
    url: str = "https://example.com/listings",
    status: int | None = 200,
    final: str | None = None,
    size: int | None = 10_000,
    error: str | None = None,
) -> ProbeResult:
    return ProbeResult(
        source=source,
        probed_url=url,
        status_code=status,
        final_url=final or (url if status and 200 <= status < 400 else None),
        response_size_bytes=size,
        duration_ms=42,
        error=error,
    )


def _baseline(
    source: str = "src",
    url: str = "https://example.com/listings",
    final: str | None = None,
    status: int = 200,
    size: int | None = 10_000,
) -> Baseline:
    return Baseline(
        source=source,
        probed_url=url,
        final_url=final or url,
        status_code=status,
        response_size_bytes=size,
        last_ok_at="2026-06-04T00:00:00+00:00",
    )


# ---------- Contract: known states ----------

def test_known_states_contract():
    """The closed-set of drift states. Consumers (watchdog Slack
    formatter, operator dashboard tile) rely on this set being
    exhaustive — adding a state without consumer updates is forbidden
    per CLAUDE.md producer-consumer rule (post-2026-06-02)."""
    assert KNOWN_DRIFT_STATES == frozenset({
        "ok",
        "unreachable",
        "redirect_drift",
        "size_drift",
        "status_drift",
    })


# ---------- First probe (no baseline) ----------

def test_first_probe_reachable_seeds_baseline_as_ok():
    """No prior baseline + a reachable probe → ok (caller refreshes
    baseline from this probe)."""
    result = classify(_probe(), baseline=None)
    assert result.drift_state == "ok"
    assert result.reason == "first_probe_seeds_baseline"
    assert result.baseline is None  # there was no prior baseline


def test_first_probe_unreachable_is_unreachable():
    """If the very first probe fails, we still alert immediately — the
    source is broken from day one and nothing has been seen working."""
    result = classify(_probe(status=503), baseline=None)
    assert result.drift_state == "unreachable"
    assert "503" in result.reason


# ---------- Unreachable beats everything ----------

def test_unreachable_status_404():
    result = classify(_probe(status=404), _baseline())
    assert result.drift_state == "unreachable"
    assert "404" in result.reason


def test_unreachable_status_503():
    result = classify(_probe(status=503), _baseline())
    assert result.drift_state == "unreachable"


def test_unreachable_http_error_exception():
    """httpx.ConnectError → error field set → unreachable."""
    result = classify(
        _probe(status=None, error="ConnectError: connection refused"),
        _baseline(),
    )
    assert result.drift_state == "unreachable"
    assert "ConnectError" in result.reason


def test_unreachable_status_below_200():
    """1xx (e.g. 100 Continue) is never a valid landing page."""
    result = classify(_probe(status=100), _baseline())
    assert result.drift_state == "unreachable"


# ---------- Redirect drift ----------

def test_redirect_drift_path_change():
    """artis-style: ``/agenda`` → ``/nl/agenda``. The previous baseline
    knows about ``/agenda`` so the move is detectable even though both
    return 200."""
    probe = _probe(
        url="https://artis.example.com/agenda",
        final="https://artis.example.com/nl/agenda",
    )
    base = _baseline(
        url="https://artis.example.com/agenda",
        final="https://artis.example.com/agenda",
    )
    result = classify(probe, base)
    assert result.drift_state == "redirect_drift"
    assert "/agenda" in result.reason and "/nl/agenda" in result.reason


def test_redirect_drift_host_change():
    """festileaks-style: redirects to a different host (e.g. a parked
    domain). Detect the host change even on 200."""
    probe = _probe(
        url="https://festileaks.example.com",
        final="https://blog.example.com/festileaks-archive",
    )
    base = _baseline(
        url="https://festileaks.example.com",
        final="https://festileaks.example.com",
    )
    result = classify(probe, base)
    assert result.drift_state == "redirect_drift"


def test_no_redirect_drift_on_trailing_slash():
    """Trailing-slash normalization: ``https://x.com`` ~= ``https://x.com/``.
    Without this, baseline ``https://oceansideelsalvador.com/`` vs a
    probe response final_url of ``https://oceansideelsalvador.com``
    would false-positive every run."""
    probe = _probe(
        url="https://x.com/",
        final="https://x.com",
    )
    base = _baseline(
        url="https://x.com",
        final="https://x.com/",
    )
    result = classify(probe, base)
    assert result.drift_state == "ok"


def test_no_redirect_drift_on_case_in_host():
    """Hostname case-insensitivity per RFC 3986."""
    probe = _probe(final="https://EXAMPLE.com/listings")
    base = _baseline(final="https://example.com/listings")
    result = classify(probe, base)
    assert result.drift_state == "ok"


# ---------- Size drift ----------

def test_size_drift_above_threshold_triggers():
    """A 60% size drop typically means the page got replaced with a
    minimal error template (e.g. Cloudflare challenge HTML)."""
    probe = _probe(size=3_000)  # baseline=10000 → 70% drop
    base = _baseline(size=10_000)
    result = classify(probe, base)
    assert result.drift_state == "size_drift"
    assert "10000" in result.reason
    assert "3000" in result.reason


def test_size_drift_below_threshold_is_ok():
    """Promo banner refresh, dynamic content — small swings are normal."""
    probe = _probe(size=11_500)  # 15% larger
    base = _baseline(size=10_000)
    result = classify(probe, base)
    assert result.drift_state == "ok"


def test_size_drift_exactly_at_threshold_is_ok():
    """The threshold is strictly > 50%. Exactly 50% should NOT trip."""
    probe = _probe(size=15_000)  # exactly 50% larger
    base = _baseline(size=10_000)
    result = classify(probe, base)
    # 50.0% delta, ratio == 0.5, not > 0.5 → still ok
    assert result.drift_state == "ok"


def test_size_drift_no_baseline_size_is_ok():
    """Some HEAD responses don't carry Content-Length. Without a known
    baseline size we can't compute drift — skip the check."""
    probe = _probe(size=10)
    base = _baseline(size=None)
    result = classify(probe, base)
    assert result.drift_state == "ok"


def test_size_drift_no_probe_size_is_ok():
    """Probe didn't get a Content-Length back — skip the size check."""
    probe = _probe(size=None)
    base = _baseline(size=10_000)
    result = classify(probe, base)
    assert result.drift_state == "ok"


def test_size_drift_threshold_constant():
    """Anchor the constant — changing this is a deliberate calibration,
    so the test fails if someone tunes it without thinking."""
    assert SIZE_DRIFT_THRESHOLD == 0.5


# ---------- Status drift ----------

def test_status_drift_200_to_204():
    """Both 2xx but the page started returning No Content — likely a
    template rewrite that broke the listings render."""
    probe = _probe(status=204)
    base = _baseline(status=200)
    result = classify(probe, base)
    assert result.drift_state == "status_drift"
    assert "200" in result.reason and "204" in result.reason


def test_status_drift_201_to_200_is_status_drift():
    """Any 2xx-to-2xx code change."""
    probe = _probe(status=200)
    base = _baseline(status=201)
    result = classify(probe, base)
    assert result.drift_state == "status_drift"


# ---------- Ok (happy path) ----------

def test_ok_matches_baseline():
    """Same URL, same status, same size → ok."""
    probe = _probe()
    base = _baseline()
    result = classify(probe, base)
    assert result.drift_state == "ok"
    assert result.reason == "matches_baseline"


# ---------- Priority order (unreachable beats redirect, etc.) ----------

def test_unreachable_beats_redirect():
    """A 404 from a NEW URL → unreachable (NOT redirect_drift). The
    site is broken; the URL change is secondary."""
    probe = _probe(status=404, final="https://example.com/different")
    base = _baseline(final="https://example.com/listings")
    result = classify(probe, base)
    assert result.drift_state == "unreachable"


def test_redirect_beats_size_drift():
    """If URL moved AND size changed, redirect is the more actionable
    signal — the URL move explains the size change."""
    probe = _probe(
        size=1_000,
        final="https://example.com/blog/archive",
    )
    base = _baseline(final="https://example.com/listings", size=10_000)
    result = classify(probe, base)
    assert result.drift_state == "redirect_drift"


def test_redirect_beats_status_drift():
    probe = _probe(status=200, final="https://example.com/elsewhere")
    base = _baseline(status=201, final="https://example.com/listings")
    result = classify(probe, base)
    assert result.drift_state == "redirect_drift"


# ---------- URL normalization ----------

def test_normalize_url_lowercases_host():
    assert _normalize_url("HTTPS://Example.COM/path") == "https://example.com/path"


def test_normalize_url_strips_root_trailing_slash():
    assert _normalize_url("https://x.com/") == _normalize_url("https://x.com")


def test_normalize_url_preserves_subpath_trailing_slash():
    """``/listings/`` and ``/listings`` are NOT the same — only the
    root ``/`` is normalized away (otherwise we'd miss real moves)."""
    assert _normalize_url("https://x.com/listings/") != _normalize_url(
        "https://x.com/listings"
    )


def test_normalize_url_strips_default_https_port():
    assert _normalize_url("https://x.com:443/y") == "https://x.com/y"


def test_normalize_url_strips_default_http_port():
    assert _normalize_url("http://x.com:80/y") == "http://x.com/y"


def test_normalize_url_drops_fragment():
    assert _normalize_url("https://x.com/p#frag") == "https://x.com/p"


def test_normalize_url_preserves_query():
    """Query string is meaningful (e.g. ?q=keyword.lago for encuentra24
    lake probe). Must NOT be stripped."""
    assert "q=lake" in _normalize_url("https://x.com/p?q=lake")


# ---------- Refresh baseline ----------

def test_refresh_baseline_captures_current_probe():
    probe = _probe(
        status=200,
        url="https://x.com",
        final="https://x.com/listings",
        size=12_345,
    )
    new = refresh_baseline(probe)
    assert new.source == "src"
    assert new.probed_url == "https://x.com"
    assert new.final_url == "https://x.com/listings"
    assert new.status_code == 200
    assert new.response_size_bytes == 12_345
    # last_ok_at is ISO-formatted current UTC.
    parsed = dt.datetime.fromisoformat(new.last_ok_at)
    assert parsed.tzinfo is not None


def test_refresh_baseline_falls_back_to_probed_url_when_final_missing():
    """If httpx didn't surface a final URL, use the originally probed
    URL — better a baseline pointing at the right place than no
    baseline."""
    probe = _probe(final=None, url="https://x.com")
    probe.final_url = None
    new = refresh_baseline(probe)
    assert new.final_url == "https://x.com"


# ---------- State path safety ----------

def test_state_path_sanitizes_source_slug(tmp_path: Path):
    """Defense in depth — even though sources come from a closed
    registry, never let a slug escape the drift_dir."""
    p = state_path_for("../evil", tmp_path)
    assert p.parent == tmp_path
    # ../ collapsed to _
    assert "evil" in p.name
    assert "../" not in str(p)


def test_state_path_lowercases(tmp_path: Path):
    p = state_path_for("BienesRaices", tmp_path)
    assert p.name == "bienesraices.json"


# ---------- Persistence round-trip ----------

def test_write_state_ok_refreshes_baseline_on_disk(tmp_path: Path):
    """The classifier returns ``ok`` with the OLD baseline still
    attached; write_state is where the baseline refresh happens."""
    old_base = _baseline(size=10_000, status=200)
    probe = _probe(size=10_500, status=200)
    classified = classify(probe, old_base)
    assert classified.drift_state == "ok"

    write_state(classified, tmp_path)

    # Round-trip — load_baseline should return the REFRESHED baseline.
    loaded = load_baseline("src", tmp_path)
    assert loaded is not None
    # New size — proves the baseline was refreshed.
    assert loaded.response_size_bytes == 10_500


def test_write_state_drift_keeps_baseline_intact(tmp_path: Path):
    """On non-ok states, baseline must NOT be refreshed — that's the
    self-healing property. A persistent 502 must not pollute the
    comparison anchor with a non-2xx baseline."""
    base = _baseline(size=10_000)
    write_state(
        # Seed the file with a known good baseline first.
        classify(_probe(size=10_000), None),
        tmp_path,
    )
    # Manually overwrite the file to include the explicit baseline
    # (first-probe seed has baseline=None).
    p = state_path_for("src", tmp_path)
    data = json.loads(p.read_text())
    data["baseline"] = base.to_dict()
    p.write_text(json.dumps(data, indent=2))

    # Now classify an unreachable probe.
    probe = _probe(status=503)
    classified = classify(probe, base)
    write_state(classified, tmp_path)

    # Reload — baseline should still be the original size=10_000.
    loaded = load_baseline("src", tmp_path)
    assert loaded is not None
    assert loaded.response_size_bytes == 10_000
    assert loaded.status_code == 200  # NOT 503


def test_load_baseline_returns_none_for_missing_file(tmp_path: Path):
    assert load_baseline("unknown_source", tmp_path) is None


def test_load_baseline_returns_none_for_malformed_file(tmp_path: Path):
    """Defensive: bad JSON shouldn't crash the sentinel."""
    p = state_path_for("src", tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json {")
    assert load_baseline("src", tmp_path) is None


# ---------- to_state_record shape stability ----------

def test_to_state_record_includes_all_consumed_fields():
    """The operator dashboard (PR-S7) reads the record. Lock the shape
    so a refactor doesn't silently drop a field consumers depend on."""
    classified = classify(_probe(), _baseline())
    record = classified.to_state_record()
    assert set(record.keys()) >= {
        "source", "drift_state", "reason", "probed_at", "last_probe", "baseline"
    }
    assert set(record["last_probe"].keys()) >= {
        "probed_url", "status_code", "final_url",
        "response_size_bytes", "duration_ms", "error",
    }
