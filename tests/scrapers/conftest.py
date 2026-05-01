"""Pytest fixtures shared by all scraper tests."""
import pytest
from pathlib import Path

CALIBRATION_DIR = Path(__file__).resolve().parents[2] / "samples" / "calibration"


@pytest.fixture
def load_sample():
    """Return a callable load_sample(source, filename) -> str."""
    def _load(source: str, filename: str) -> str:
        return (CALIBRATION_DIR / source / filename).read_text(encoding="utf-8")
    return _load
