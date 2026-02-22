"""Shared test fixtures and configuration."""

import os
import sys
from pathlib import Path

# Add ha_autogen/ to Python path so `from autogen.xxx` imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ha_autogen"))

import pytest

os.environ["AUTOGEN_DEV_MODE"] = "true"

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def entity_fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "entity_registry.json"


@pytest.fixture
def area_fixture_path(fixtures_dir: Path) -> Path:
    return fixtures_dir / "area_registry.json"
