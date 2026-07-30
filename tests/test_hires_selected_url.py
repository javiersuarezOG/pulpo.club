"""PR-I (image/nightly audit 2026-07-29): the hires pipeline must fetch
the picker's WINNING photo (li.selected_photo_url), not blindly
photo_urls[0]. Otherwise the retained native-resolution original can be a
different image than the served hero.

Drives _download_hires_photos with a mocked httpx and asserts which URL
was requested.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _make_jpeg(size=(1600, 1200), color=(120, 130, 140)) -> bytes:
    pytest.importorskip("PIL")
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture()
def tmp_repo(tmp_path):
    (tmp_path / "web" / "photos-hires").mkdir(parents=True)
    (tmp_path / "web" / "data").mkdir(parents=True)
    return tmp_path


def _hires_env(monkeypatch):
    monkeypatch.setenv("PULPO_HIRES_ENABLED", "1")
    monkeypatch.setenv("PULPO_HIRES_SOURCES", "remax")
    # bienesraices/goodlife/encuentra24 have real transforms; remax is an
    # identity-transform source so the fetched URL == the chosen URL.


def test_hires_fetches_selected_photo_url_not_first(tmp_repo, monkeypatch):
    pytest.importorskip("PIL")
    _hires_env(monkeypatch)
    from pulpo.models import Listing
    from automation.run import _download_hires_photos

    winner = "https://cdn.example.com/photo-3-the-winner.jpg"
    first = "https://cdn.example.com/photo-1-first.jpg"

    li = Listing(
        source="remax", source_id="sel-001",
        url="https://example.com/listing",
        scraped_at="2026-01-01T00:00:00Z",
        title="Listing",
        photo_urls=[first, "https://cdn.example.com/photo-2.jpg", winner],
    )
    li.selected_photo_url = winner  # the hero picker chose photo 3
    li.rank_score = 10.0

    requested: list[str] = []

    def fake_get(url, *_a, **_k):
        requested.append(url)
        r = mock.MagicMock()
        r.content = _make_jpeg()
        r.raise_for_status = mock.MagicMock()
        return r

    with mock.patch("httpx.get", side_effect=fake_get):
        _download_hires_photos([li], tmp_repo)

    assert requested, "expected a hires fetch"
    # It must have fetched the WINNER, never the gallery's first photo.
    assert requested[0] == winner
    assert first not in requested


def test_hires_falls_back_to_first_when_no_selected(tmp_repo, monkeypatch):
    """No selected_photo_url recorded → fall back to photo_urls[0] (prior
    behavior), so a listing that never went through the picker still gets
    a hires attempt."""
    pytest.importorskip("PIL")
    _hires_env(monkeypatch)
    from pulpo.models import Listing
    from automation.run import _download_hires_photos

    first = "https://cdn.example.com/only.jpg"
    li = Listing(
        source="remax", source_id="sel-002",
        url="https://example.com/listing",
        scraped_at="2026-01-01T00:00:00Z",
        title="Listing",
        photo_urls=[first],
    )
    li.selected_photo_url = None
    li.rank_score = 5.0

    requested: list[str] = []

    def fake_get(url, *_a, **_k):
        requested.append(url)
        r = mock.MagicMock()
        r.content = _make_jpeg()
        r.raise_for_status = mock.MagicMock()
        return r

    with mock.patch("httpx.get", side_effect=fake_get):
        _download_hires_photos([li], tmp_repo)

    assert requested and requested[0] == first
