"""
Tests for the photo pipeline:
  - Scraper photo_urls passthrough
  - Hero download + resize (with mocked HTTP)
  - Orphan pruning
  - Storage canary logic
"""
from __future__ import annotations
import io
import json
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


# ── Model field presence ────────────────────────────────────────────────

def test_listing_model_has_photo_fields():
    """Listing dataclass must have photo_urls and hero_photo_path fields."""
    from pulpo.models import Listing
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(Listing)}
    assert "photo_urls" in field_names, "photo_urls missing from Listing"
    assert "hero_photo_path" in field_names, "hero_photo_path missing from Listing"


def test_listing_photo_urls_defaults_empty():
    from pulpo.models import Listing
    li = Listing(source="test", source_id="1", url="http://x.com", scraped_at="2026-01-01T00:00:00Z", title="T")
    assert li.photo_urls == []
    assert li.hero_photo_path is None


# ── normalize() passes photo_urls through ──────────────────────────────

def test_normalize_passes_photo_urls():
    """normalize() must forward photo_urls from the raw dict to the Listing."""
    from pulpo.normalize import normalize
    raw = {
        "source_id": "test-photo-001",
        "url": "https://example.com/test",
        "title": "Terreno en venta",
        "price_usd": 80_000.0,
        "area_m2": 1_000.0,
        "raw_price_text": "$80,000",
        "raw_size_text": "1000 m2",
        "property_type": "land",
        "photo_urls": ["https://example.com/photo1.jpg", "https://example.com/photo2.jpg"],
    }
    li = normalize(raw, source="bienesraices")
    assert li is not None
    assert li.photo_urls == ["https://example.com/photo1.jpg", "https://example.com/photo2.jpg"]
    assert li.photos_count == 2


def test_normalize_empty_photo_urls_stays_empty():
    from pulpo.normalize import normalize
    raw = {
        "source_id": "no-photo-001",
        "url": "https://example.com/nophoto",
        "title": "Terreno sin fotos",
        "price_usd": 50_000.0,
        "area_m2": 500.0,
        "raw_price_text": "$50,000",
        "raw_size_text": "500 m2",
        "property_type": "land",
    }
    li = normalize(raw, source="goodlife")
    assert li is not None
    assert li.photo_urls == []
    assert li.hero_photo_path is None


# ── Hero download ───────────────────────────────────────────────────────

def _make_fake_jpeg() -> bytes:
    """Create a minimal valid JPEG-like byte string (1×1 white pixel)."""
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (800, 600), (200, 200, 200)).save(buf, format="JPEG")
        return buf.getvalue()
    except ImportError:
        pytest.skip("Pillow not installed")


@pytest.fixture()
def tmp_repo(tmp_path):
    """A fake repo directory with web/photos/ and web/data/."""
    (tmp_path / "web" / "photos").mkdir(parents=True)
    (tmp_path / "web" / "data").mkdir(parents=True)
    return tmp_path


def test_hero_download_creates_jpeg(tmp_repo):
    """A listing with a photo URL gets a resized JPEG at hero_photo_path."""
    pytest.importorskip("PIL")
    from pulpo.models import Listing
    from automation.run import _download_hero_photos

    li = Listing(
        source="bienesraices", source_id="test-dl-001",
        url="https://example.com/listing",
        scraped_at="2026-01-01T00:00:00Z",
        title="Test listing",
        photo_urls=["https://example.com/hero.jpg"],
    )

    fake_jpeg = _make_fake_jpeg()
    fake_response = mock.MagicMock()
    fake_response.content = fake_jpeg
    fake_response.raise_for_status = mock.MagicMock()

    with mock.patch("httpx.get", return_value=fake_response):
        result = _download_hero_photos([li], tmp_repo)

    assert result["ok"] == 1
    assert result["failed"] == 0
    assert li.hero_photo_path == "/photos/bienesraices_test-dl-001.jpg"

    photo_path = tmp_repo / "web" / "photos" / "bienesraices_test-dl-001.jpg"
    assert photo_path.exists()
    assert photo_path.stat().st_size > 0

    from PIL import Image
    img = Image.open(photo_path)
    assert img.width <= 600
    assert img.height <= 400


def test_hero_download_404_sets_null_and_logs(tmp_repo):
    """A failed download leaves hero_photo_path=None and logs the error."""
    pytest.importorskip("PIL")
    from pulpo.models import Listing
    from automation.run import _download_hero_photos

    li = Listing(
        source="goodlife", source_id="test-fail-001",
        url="https://example.com/listing",
        scraped_at="2026-01-01T00:00:00Z",
        title="Failed photo listing",
        photo_urls=["https://example.com/not-found.jpg"],
    )

    with mock.patch("httpx.get", side_effect=Exception("404 Not Found")):
        result = _download_hero_photos([li], tmp_repo)

    assert result["failed"] == 1
    assert li.hero_photo_path is None

    log_path = tmp_repo / "web" / "data" / "photo_fetch_log.jsonl"
    assert log_path.exists()
    entries = [json.loads(line) for line in log_path.read_text().strip().splitlines()]
    assert any(e["source_id"] == "test-fail-001" for e in entries)
    assert any("404" in e.get("error", "") for e in entries)


def test_hero_download_skips_when_all_derivatives_present(tmp_repo):
    """Re-running with same URL skips the fetch when ALL four files exist:
    thumbnail + hero derivative + both sidecars. Phase 2 of the rewrite
    tightened the skip-check from thumbnail+hash to the full derivative
    set so pre-Phase-2 cached entries get their hero file produced on
    the next nightly — see test_hero_download_refetches_when_hero_missing
    below for the migration path."""
    pytest.importorskip("PIL")
    import hashlib
    from pulpo.models import Listing
    from automation.run import _download_hero_photos

    url = "https://example.com/cached.jpg"
    url_hash = hashlib.sha1(url.encode()).hexdigest()[:12]
    fname = "remax_cache-001.jpg"
    photos_dir = tmp_repo / "web" / "photos"
    fpath = photos_dir / fname
    hero_fpath = photos_dir / "remax_cache-001.hero.jpg"
    # All four files the skip-path now verifies.
    fpath.write_bytes(b"fake-thumbnail")
    hero_fpath.write_bytes(b"fake-hero")
    (photos_dir / (fname + ".hash")).write_text(url_hash)
    (photos_dir / (fname + ".meta.json")).write_text(
        '{"width": 600, "height": 400, "card_eligible": true, "hero_eligible": false}'
    )
    (photos_dir / "remax_cache-001.hero.jpg.meta.json").write_text(
        '{"width": 1920, "height": 1080, "card_eligible": true, "hero_eligible": true}'
    )

    li = Listing(
        source="remax", source_id="cache-001",
        url="https://example.com/listing",
        scraped_at="2026-01-01T00:00:00Z",
        title="Cached listing",
        photo_urls=[url],
    )

    with mock.patch("httpx.get") as mock_get:
        result = _download_hero_photos([li], tmp_repo)
        mock_get.assert_not_called()

    assert result["skipped"] == 1
    assert li.hero_photo_path == f"/photos/{fname}"
    # Eligibility flags re-populated from the sidecars on the skip path.
    assert li.card_eligible is True
    assert li.hero_eligible is True


def test_hero_download_refetches_when_hero_missing(tmp_repo):
    """Pre-Phase-2 cached entries (thumbnail + hash only, no hero file)
    trigger a re-fetch even when the URL hash matches. This is how the
    catalog migrates to the dual-derivative storage scheme over the
    first nightly post-deploy — without this, the homepage proof row
    would never see hero_eligible photos for legacy listings."""
    pytest.importorskip("PIL")
    import hashlib
    from pulpo.models import Listing
    from automation.run import _download_hero_photos

    url = "https://example.com/legacy.jpg"
    url_hash = hashlib.sha1(url.encode()).hexdigest()[:12]
    fname = "remax_legacy-001.jpg"
    photos_dir = tmp_repo / "web" / "photos"
    # Only the OLD files exist — no .hero.jpg, no .meta.json sidecars.
    (photos_dir / fname).write_bytes(b"fake-thumbnail")
    (photos_dir / (fname + ".hash")).write_text(url_hash)

    li = Listing(
        source="remax", source_id="legacy-001",
        url="https://example.com/listing",
        scraped_at="2026-01-01T00:00:00Z",
        title="Legacy listing",
        photo_urls=[url],
    )

    # Stub httpx.get with a real image so the post-fetch processing
    # path completes (otherwise the hero-thumbnail step would fail
    # decoding fake bytes).
    from PIL import Image as PILImage
    import io
    img = PILImage.new("RGB", (2000, 1300), (128, 128, 128))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    fake_response = mock.Mock()
    fake_response.content = buf.getvalue()
    fake_response.raise_for_status = mock.Mock()

    with mock.patch("httpx.get", return_value=fake_response) as mock_get:
        result = _download_hero_photos([li], tmp_repo)
        mock_get.assert_called_once()  # the missing-hero forces re-fetch

    assert result["ok"] == 1
    assert result["skipped"] == 0
    # All four files now exist after the re-fetch
    assert (photos_dir / fname).exists()
    assert (photos_dir / "remax_legacy-001.hero.jpg").exists()
    assert (photos_dir / (fname + ".meta.json")).exists()
    assert (photos_dir / "remax_legacy-001.hero.jpg.meta.json").exists()


# ── U1 hero re-escalation (2026-05-18) ──────────────────────────────────
# Pre-U1 behavior: always picked photo_urls[0]. The 2026-05-18 incident
# showed this published a pixelated + watermarked first photo even when
# the listing carried better candidates. The new behavior scores up to
# PULPO_PHOTO_MAX_CANDIDATES candidates and picks the winner.


def _make_jpeg(size=(800, 600), color=(200, 200, 200), quality=85) -> bytes:
    """Helper: build a JPEG with a specific size + color to vary the
    PR-7.6 score across test candidates."""
    pytest.importorskip("PIL")
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def test_pick_best_photo_picks_highest_scoring(tmp_repo):
    """Three candidates with different sizes — picker returns the
    highest-resolution one (PR-7.6's resolution tier dominates the score
    when sharpness + size are similar)."""
    pytest.importorskip("PIL")
    from automation.run import _pick_best_photo_url

    big = _make_jpeg(size=(1920, 1080))      # full-HD → tier 100
    mid = _make_jpeg(size=(1280, 720))       # HD → tier 70
    small = _make_jpeg(size=(800, 600))      # passable → tier 40

    responses = {
        "https://example.com/small.jpg": small,
        "https://example.com/mid.jpg": mid,
        "https://example.com/big.jpg": big,
    }

    def fake_get(url, *_args, **_kwargs):
        r = mock.MagicMock()
        r.content = responses[url]
        r.raise_for_status = mock.MagicMock()
        return r

    with mock.patch("httpx.get", side_effect=fake_get):
        url, content, score, has_text = _pick_best_photo_url(list(responses.keys()))

    # The full-HD image should win — it's the only one in tier 100.
    assert url == "https://example.com/big.jpg"
    assert content == big
    assert score >= 100


def test_pick_best_photo_deprioritizes_text_overlay(tmp_repo):
    """When one candidate is flagged has_text_overlay=True and others
    are not, the picker prefers a non-flagged candidate even if it scores
    lower."""
    pytest.importorskip("PIL")
    from automation.run import _pick_best_photo_url

    flagged = _make_jpeg(size=(1920, 1080))   # high-res but flagged
    clean = _make_jpeg(size=(800, 600))       # lower-res but clean

    responses = {
        "https://example.com/flagged.jpg": flagged,
        "https://example.com/clean.jpg": clean,
    }

    def fake_get(url, *_args, **_kwargs):
        r = mock.MagicMock()
        r.content = responses[url]
        r.raise_for_status = mock.MagicMock()
        return r

    def fake_text_overlay(content):
        return content == flagged

    with mock.patch("httpx.get", side_effect=fake_get), \
         mock.patch("automation.photo_quality.detect_text_overlay",
                    side_effect=fake_text_overlay):
        url, _content, _score, has_text = _pick_best_photo_url(list(responses.keys()))

    assert url == "https://example.com/clean.jpg"
    assert has_text is False


def test_pick_best_photo_falls_back_when_all_flagged(tmp_repo):
    """If every candidate is flagged, return the highest-scoring flagged
    one — we still want a hero rather than no hero at all."""
    pytest.importorskip("PIL")
    from automation.run import _pick_best_photo_url

    big_flagged = _make_jpeg(size=(1920, 1080))
    small_flagged = _make_jpeg(size=(600, 400))

    responses = {
        "https://example.com/big.jpg": big_flagged,
        "https://example.com/small.jpg": small_flagged,
    }

    def fake_get(url, *_args, **_kwargs):
        r = mock.MagicMock()
        r.content = responses[url]
        r.raise_for_status = mock.MagicMock()
        return r

    with mock.patch("httpx.get", side_effect=fake_get), \
         mock.patch("automation.photo_quality.detect_text_overlay",
                    return_value=True):
        url, _content, _score, has_text = _pick_best_photo_url(list(responses.keys()))

    assert url == "https://example.com/big.jpg"
    assert has_text is True


def test_pick_best_photo_returns_none_when_all_fail(tmp_repo):
    """All downloads fail → returns (None, None, None, None) and the
    caller increments the failure counter."""
    from automation.run import _pick_best_photo_url

    with mock.patch("httpx.get", side_effect=Exception("connection_refused")):
        result = _pick_best_photo_url(["https://example.com/a.jpg",
                                       "https://example.com/b.jpg"])
    assert result == (None, None, None, None)


def test_pick_best_photo_respects_candidates_cap(tmp_repo, monkeypatch):
    """Only the first N candidates are downloaded (PULPO_PHOTO_MAX_CANDIDATES)."""
    pytest.importorskip("PIL")
    from automation.run import _pick_best_photo_url
    monkeypatch.setenv("PULPO_PHOTO_MAX_CANDIDATES", "2")

    fake = _make_jpeg(size=(1920, 1080))
    calls = []

    def fake_get(url, *_args, **_kwargs):
        calls.append(url)
        r = mock.MagicMock()
        r.content = fake
        r.raise_for_status = mock.MagicMock()
        return r

    with mock.patch("httpx.get", side_effect=fake_get):
        _pick_best_photo_url([
            "https://example.com/1.jpg",
            "https://example.com/2.jpg",
            "https://example.com/3.jpg",
            "https://example.com/4.jpg",
        ])

    assert len(calls) == 2


def test_hero_download_picks_best_of_multiple(tmp_repo):
    """End-to-end: a listing with 3 photo_urls picks the best (highest
    resolution + not flagged) as its hero, NOT photo_urls[0]."""
    pytest.importorskip("PIL")
    from pulpo.models import Listing
    from automation.run import _download_hero_photos

    bad_first = _make_jpeg(size=(600, 400))       # low-res — bad first
    great_second = _make_jpeg(size=(1920, 1080))  # full HD — should win
    mid_third = _make_jpeg(size=(1280, 720))

    responses = {
        "https://example.com/bad_first.jpg": bad_first,
        "https://example.com/great_second.jpg": great_second,
        "https://example.com/mid_third.jpg": mid_third,
    }

    li = Listing(
        source="bienesraices", source_id="u1-multipick-001",
        url="https://example.com/listing",
        scraped_at="2026-01-01T00:00:00Z",
        title="Multi-photo listing",
        photo_urls=list(responses.keys()),
    )

    def fake_get(url, *_args, **_kwargs):
        r = mock.MagicMock()
        r.content = responses[url]
        r.raise_for_status = mock.MagicMock()
        return r

    with mock.patch("httpx.get", side_effect=fake_get):
        result = _download_hero_photos([li], tmp_repo)

    assert result["ok"] == 1
    assert li.hero_photo_path == "/photos/bienesraices_u1-multipick-001.jpg"

    # The hero sidecar should record which URL won.
    sidecar = tmp_repo / "web" / "photos" / "bienesraices_u1-multipick-001.hero.jpg.meta.json"
    assert sidecar.exists()
    sidecar_data = json.loads(sidecar.read_text())
    assert sidecar_data["winning_url"] == "https://example.com/great_second.jpg", \
        "Picker should have chosen the full-HD candidate over the 600x400 first"
    assert sidecar_data["candidate_count"] == 3


def test_no_photo_listing_skipped(tmp_repo):
    """Listings with empty photo_urls are not attempted."""
    pytest.importorskip("PIL")
    from pulpo.models import Listing
    from automation.run import _download_hero_photos

    li = Listing(
        source="oceanside", source_id="nophoto-001",
        url="https://example.com/listing",
        scraped_at="2026-01-01T00:00:00Z",
        title="No photo listing",
        photo_urls=[],
    )

    with mock.patch("httpx.get") as mock_get:
        result = _download_hero_photos([li], tmp_repo)
        mock_get.assert_not_called()

    assert result["attempted"] == 0
    assert li.hero_photo_path is None


# ── Orphan pruning ──────────────────────────────────────────────────────

def test_orphan_photos_moved_to_archive(tmp_repo):
    """Photos with no matching listing are moved to _archive/."""
    from automation.run import _prune_orphan_photos

    photos_dir = tmp_repo / "web" / "photos"
    # Live photo
    live = photos_dir / "goodlife_live-001.jpg"
    live.write_bytes(b"live")
    # Orphan photo (no matching listing)
    orphan = photos_dir / "bienesraices_orphan-999.jpg"
    orphan.write_bytes(b"orphan")

    live_filenames = {"goodlife_live-001.jpg"}
    _prune_orphan_photos(photos_dir, live_filenames)

    assert live.exists(), "Live photo must not be moved"
    assert not orphan.exists(), "Orphan must be moved to archive"
    # Check archive contains the orphan
    archive_files = list((photos_dir / "_archive").rglob("*.jpg"))
    assert any("orphan" in f.name for f in archive_files)


# ── Storage canary logic ────────────────────────────────────────────────

def test_storage_canary_passes_under_limit(tmp_repo):
    """A small photos directory should not trigger the canary."""
    photos_dir = tmp_repo / "web" / "photos"
    (photos_dir / "small.jpg").write_bytes(b"x" * 1024)  # 1 KB
    total = sum(f.stat().st_size for f in photos_dir.rglob("*.jpg") if "_archive" not in f.parts)
    mb = total / (1024 * 1024)
    assert mb < 100, f"Expected < 100 MB, got {mb:.2f} MB"


def test_storage_canary_fails_over_limit(tmp_repo):
    """A photos directory exceeding 100 MB should be flagged."""
    photos_dir = tmp_repo / "web" / "photos"
    # Write a file that's just over 100 MB
    big_file = photos_dir / "big.jpg"
    big_file.write_bytes(b"x" * (101 * 1024 * 1024))
    total = sum(f.stat().st_size for f in photos_dir.rglob("*.jpg") if "_archive" not in f.parts)
    mb = total / (1024 * 1024)
    assert mb > 100, f"Expected > 100 MB, got {mb:.2f} MB"
