"""Test configuration: make ``src`` importable and expose the fixture universe."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd
import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

# Keep config deterministic regardless of any ambient .env.
os.environ.setdefault("SCAN_MODE", "tight")

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def universe() -> pd.DataFrame:
    """Hand-crafted base universe where each row targets a known strategy outcome."""
    rows = json.loads((FIXTURES / "universe.json").read_text())
    return pd.DataFrame(rows)
