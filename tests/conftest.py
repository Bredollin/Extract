"""Shared fixtures: recorded PowerShell output samples."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from extract.core.powershell import FakePowerShell

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def fake_ps_factory():
    """Build a FakePowerShell from a {script substring: response} mapping."""
    return FakePowerShell


def pytest_collection_modifyitems(config, items):
    if sys.platform == "win32":
        return
    skip = pytest.mark.skip(reason="needs Windows")
    for item in items:
        if "windows" in item.keywords:
            item.add_marker(skip)
