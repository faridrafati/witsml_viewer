"""Shared pytest fixtures for the WITSML backend unit suite.

These tests run with ONLY lxml + pydantic + pydantic-settings installed — no
zeep, no DB, no network. Nothing here imports app.witsml.client or app.db.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the repo root importable so integration tests can `import mockstore`
# (the in-house WITSML mock store lives at <repo>/mockstore, a sibling of backend/).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    """Read an XML fixture file from tests/fixtures/ as text."""
    path = FIXTURE_DIR / name
    return path.read_text(encoding="utf-8")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURE_DIR


@pytest.fixture
def xml() -> "callable[[str], str]":
    """Callable fixture: ``xml("wells.xml")`` -> file contents as a string."""
    return load_fixture
