"""Tests for the dashboard deploy engine (multi-dashboard support)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from autogen.deployer.dashboard_engine import (
    DashboardDeployEngine,
    _get_output_dir,
    _sanitize_url_path,
)


# -- Unit tests for _sanitize_url_path --

def test_sanitize_basic_title() -> None:
    assert _sanitize_url_path("Climate Controls") == "climate-controls"


def test_sanitize_adds_hyphen_when_missing() -> None:
    result = _sanitize_url_path("dashboard")
    assert "-" in result
    assert result == "autogen-dashboard"


def test_sanitize_empty_string() -> None:
    result = _sanitize_url_path("")
    assert result == "autogen-dashboard"


def test_sanitize_special_chars() -> None:
    result = _sanitize_url_path("My Dashboard!!! @2024")
    assert result == "my-dashboard-2024"


def test_sanitize_truncates_long() -> None:
    result = _sanitize_url_path("a" * 100)
    assert len(result) <= 64


def test_sanitize_already_has_hyphen() -> None:
    result = _sanitize_url_path("climate-dashboard")
    assert result == "climate-dashboard"


# -- Dashboard deploy engine tests --

@pytest.mark.asyncio
async def test_list_dashboards_dev_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()
    dashboards = await engine.list_dashboards()

    # Should always have at least the default dashboard
    assert len(dashboards) >= 1
    assert dashboards[0]["url_path"] is None
    assert dashboards[0]["title"] == "Default Dashboard"


@pytest.mark.asyncio
async def test_list_dashboards_with_created(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()

    # Create a dashboard first
    await engine.create_dashboard("my-dash", "My Dashboard")

    dashboards = await engine.list_dashboards()
    assert len(dashboards) == 2  # default + new one
    assert dashboards[1]["url_path"] == "my-dash"
    assert dashboards[1]["title"] == "My Dashboard"


@pytest.mark.asyncio
async def test_create_dashboard_dev_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()
    entry = await engine.create_dashboard(
        url_path="test-dash",
        title="Test Dashboard",
        icon="mdi:robot",
    )

    assert entry["url_path"] == "test-dash"
    assert entry["title"] == "Test Dashboard"
    assert entry["icon"] == "mdi:robot"

    # Verify registry was saved
    registry = json.loads((tmp_path / "dashboards_registry.json").read_text())
    assert len(registry) == 1
    assert registry[0]["url_path"] == "test-dash"


@pytest.mark.asyncio
async def test_deploy_to_default_dev_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()
    config = {"views": [{"title": "Home", "cards": []}]}

    result = await engine.deploy(config, url_path=None, backup_enabled=False)

    assert result["views_count"] == 1
    assert result["url_path"] is None

    # Should be saved to the default file
    saved = json.loads((tmp_path / "lovelace_config.json").read_text())
    assert saved["views"][0]["title"] == "Home"


@pytest.mark.asyncio
async def test_deploy_to_specific_dashboard_dev_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()
    config = {"views": [{"title": "Climate", "cards": []}]}

    result = await engine.deploy(config, url_path="climate-dash", backup_enabled=False)

    assert result["views_count"] == 1
    assert result["url_path"] == "climate-dash"

    # Should be saved to a url_path-specific file
    saved = json.loads((tmp_path / "lovelace_climate-dash.json").read_text())
    assert saved["views"][0]["title"] == "Climate"


@pytest.mark.asyncio
async def test_deploy_with_backup_dev_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()

    # Deploy initial config
    initial = {"views": [{"title": "v1"}]}
    await engine.deploy(initial, url_path="test-dash", backup_enabled=False)

    # Deploy new config with backup
    updated = {"views": [{"title": "v2"}]}
    result = await engine.deploy(updated, url_path="test-dash", backup_enabled=True)

    assert result["backup_json"] is not None
    backup_data = json.loads(result["backup_json"])
    assert backup_data["views"][0]["title"] == "v1"

    # Backup file should exist
    assert (tmp_path / "lovelace_test-dash_backup.json").exists()


@pytest.mark.asyncio
async def test_deploy_missing_views_raises(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()

    with pytest.raises(ValueError, match="views"):
        await engine.deploy({"title": "No views"}, backup_enabled=False)


@pytest.mark.asyncio
async def test_get_current_config_dev_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()

    # No config yet
    assert await engine.get_current_config() == {}
    assert await engine.get_current_config("my-dash") == {}

    # Write a config for a specific dashboard
    config = {"views": [{"title": "Test"}]}
    (tmp_path / "lovelace_my-dash.json").write_text(json.dumps(config))

    result = await engine.get_current_config("my-dash")
    assert result["views"][0]["title"] == "Test"


@pytest.mark.asyncio
async def test_create_dashboard_no_duplicate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("AUTOGEN_DEV_MODE", "true")
    monkeypatch.setattr(
        "autogen.deployer.dashboard_engine._get_output_dir", lambda: tmp_path
    )

    engine = DashboardDeployEngine()

    await engine.create_dashboard("my-dash", "First")
    await engine.create_dashboard("my-dash", "Updated")

    registry = json.loads((tmp_path / "dashboards_registry.json").read_text())
    assert len(registry) == 1
    assert registry[0]["title"] == "Updated"


# -- Dev mode filename helper tests --

def test_dev_config_filename_default() -> None:
    assert DashboardDeployEngine._dev_config_filename(None) == "lovelace_config.json"


def test_dev_config_filename_custom() -> None:
    assert DashboardDeployEngine._dev_config_filename("my-dash") == "lovelace_my-dash.json"


def test_dev_backup_filename_default() -> None:
    assert DashboardDeployEngine._dev_backup_filename(None) == "lovelace_backup.json"


def test_dev_backup_filename_custom() -> None:
    assert DashboardDeployEngine._dev_backup_filename("my-dash") == "lovelace_my-dash_backup.json"
