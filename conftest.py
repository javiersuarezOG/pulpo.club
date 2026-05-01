"""Root conftest — makes pulpo and automation importable from anywhere pytest runs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
