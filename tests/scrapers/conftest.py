from pathlib import Path
import pytest

CALIBRATION_DIR = Path(__file__).resolve().parents[2] / "samples" / "calibration"

def load_sample(source: str, filename: str) -> str:
    return (CALIBRATION_DIR / source / filename).read_text(encoding="utf-8")
