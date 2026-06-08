from __future__ import annotations

import json
from pathlib import Path

import automation.scraper_failures as sf


class _Response:
    status_code = 403
    headers = {
        "Set-Cookie": "session=secret",
        "Authorization": "Bearer response-secret",
        "X-Trace": "ok",
    }
    text = "blocked"


def test_failure_snapshot_redacts_sensitive_headers(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(sf, "FAILURES_DIR", tmp_path)

    failure_id = sf.write_failure_snapshot(
        "source",
        kind="exception",
        response=_Response(),
        request_url="https://example.test",
        request_headers={
            "Authorization": "Bearer request-secret",
            "Cookie": "a=b",
            "User-Agent": "pytest",
        },
        ts="2026-06-08T00:00:00+00:00",
    )

    assert failure_id
    path = next(tmp_path.glob("source_*.json"))
    payload = json.loads(path.read_text())
    assert payload["request"]["headers"]["Authorization"] == "<redacted>"
    assert payload["request"]["headers"]["Cookie"] == "<redacted>"
    assert payload["request"]["headers"]["User-Agent"] == "pytest"
    assert payload["response"]["headers"]["Set-Cookie"] == "<redacted>"
    assert payload["response"]["headers"]["Authorization"] == "<redacted>"
    assert payload["response"]["headers"]["X-Trace"] == "ok"
