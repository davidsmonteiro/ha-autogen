"""Tests for dashboard context loading and engine integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autogen.context.dashboards import load_dashboards_from_fixture


FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "sample_lovelace.json"


def test_load_fixture_returns_dict() -> None:
    result = load_dashboards_from_fixture(FIXTURE_PATH)
    assert isinstance(result, dict)
    assert "views" in result


def test_fixture_has_expected_views() -> None:
    result = load_dashboards_from_fixture(FIXTURE_PATH)
    views = result["views"]
    assert len(views) == 3
    titles = {v["title"] for v in views}
    assert "Living Room" in titles
    assert "Kitchen" in titles


def test_fixture_views_have_cards() -> None:
    result = load_dashboards_from_fixture(FIXTURE_PATH)
    for view in result["views"]:
        assert "cards" in view
        assert len(view["cards"]) > 0


def test_load_missing_file_returns_empty() -> None:
    result = load_dashboards_from_fixture(Path("/nonexistent/file.json"))
    assert result == {}


@pytest.mark.asyncio
async def test_engine_has_dashboards_property() -> None:
    """ContextEngine should expose dashboards after loading fixtures."""
    from autogen.context.engine import ContextEngine

    engine = ContextEngine()
    await engine._load_fixtures()
    assert isinstance(engine.dashboards, dict)
    assert "views" in engine.dashboards


@pytest.mark.asyncio
async def test_engine_dashboard_view_count() -> None:
    from autogen.context.engine import ContextEngine

    engine = ContextEngine()
    await engine._load_fixtures()
    assert len(engine.dashboards["views"]) == 3
