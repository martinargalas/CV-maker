"""Shared test setup.

The app rate-limits by caller, and a test run is one caller making hundreds of
requests. Without this the limit trips partway through the suite and later
tests fail for a reason that has nothing to do with what they check.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def reset_limits():
    """Start each test with a fresh request budget."""
    for module_name, table in (("app", "_hits"), ("auth", "_attempts")):
        module = sys.modules.get(module_name)
        if module is not None:
            getattr(module, table).clear()
    yield
