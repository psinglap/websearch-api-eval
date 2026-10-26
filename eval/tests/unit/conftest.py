"""Unit tests run fully offline on FAKE fixtures (tests/fixtures/)."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EVAL))
sys.path.insert(0, str(EVAL / "asserts"))
sys.path.insert(0, str(EVAL / "analysis"))
FIX = EVAL / "tests" / "fixtures"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAL_OUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("EVAL_NO_FRICTION_AUTOLOG", "1")
    monkeypatch.setenv("FRICTION_LOG", str(tmp_path / "friction.csv"))
    for k in ("YDC_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY", "PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "LINKUP_API_KEY"):
        monkeypatch.setenv(k, "FIXTURE-NOT-A-KEY")  # HTTP is mocked in these tests
    yield


def load_module(rel: str, name: str | None = None):
    p = EVAL / rel
    spec = importlib.util.spec_from_file_location(name or p.stem, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m
