"""Dashboard deploy engine -- deploy Lovelace configs via HA WebSocket API."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


def _get_output_dir() -> Path:
    """Return the output directory for dev mode dashboard writes."""
    output_dir = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "output"
    output_dir.mkdir(exist_ok=True)
    return output_dir


def _sanitize_url_path(title: str) -> str:
    """Generate a valid HA dashboard url_path from a title.

    HA requires url_path to contain a hyphen and be lowercase alphanumeric+hyphens.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = "autogen-dashboard"
    # HA requires at least one hyphen in url_path
    if "-" not in slug:
        slug = f"autogen-{slug}"
    return slug[:64]


async def _ws_call(token: str, msg_type: str, **kwargs) -> dict:
    """Open a short-lived WS connection and send a single command."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect("ws://supervisor/core/websocket") as ws:
            auth_msg = await ws.receive_json()
            if auth_msg.get("type") != "auth_required":
                raise RuntimeError(f"Unexpected WS message: {auth_msg}")
            await ws.send_json({"type": "auth", "access_token": token})
            auth_resp = await ws.receive_json()
            if auth_resp.get("type") != "auth_ok":
                raise RuntimeError(f"WS auth failed: {auth_resp}")

            payload = {"id": 1, "type": msg_type, **kwargs}
            await ws.send_json(payload)
            resp = await ws.receive_json()
            return resp


class DashboardDeployEngine:
    """Manages deploying Lovelace dashboard configs to Home Assistant."""

    def __init__(self) -> None:
        self._dev_mode = os.environ.get("AUTOGEN_DEV_MODE", "").lower() == "true"

    async def list_dashboards(self) -> list[dict[str, Any]]:
        """List all storage-mode dashboards.

        Returns a list of dicts with keys: url_path, title, icon,
        show_in_sidebar, require_admin, mode.
        The default dashboard is always prepended as a virtual entry.
        """
        default_entry = {
            "url_path": None,
            "title": "Default Dashboard",
            "icon": "mdi:view-dashboard",
            "mode": "storage",
        }

        if self._dev_mode:
            dev_dashboards = self._load_dev_dashboards()
            return [default_entry] + dev_dashboards

        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise RuntimeError("SUPERVISOR_TOKEN not set")

        resp = await _ws_call(token, "lovelace/dashboards/list")
        if not resp.get("success"):
            logger.warning("Failed to list dashboards: %s", resp.get("error"))
            return [default_entry]

        dashboards = resp.get("result", [])
        return [default_entry] + dashboards

    async def create_dashboard(
        self,
        url_path: str,
        title: str,
        icon: str = "mdi:view-dashboard",
        show_in_sidebar: bool = True,
    ) -> dict[str, Any]:
        """Create a new storage-mode dashboard.

        Args:
            url_path: URL path for the dashboard (must contain a hyphen).
            title: Display title.
            icon: MDI icon for sidebar.
            show_in_sidebar: Whether to show in the sidebar.

        Returns:
            The created dashboard entry dict.
        """
        if self._dev_mode:
            entry = {
                "url_path": url_path,
                "title": title,
                "icon": icon,
                "show_in_sidebar": show_in_sidebar,
                "mode": "storage",
            }
            self._save_dev_dashboard(entry)
            return entry

        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise RuntimeError("SUPERVISOR_TOKEN not set")

        resp = await _ws_call(
            token,
            "lovelace/dashboards/create",
            url_path=url_path,
            title=title,
            icon=icon,
            show_in_sidebar=show_in_sidebar,
            mode="storage",
        )
        if not resp.get("success"):
            error = resp.get("error", {})
            raise RuntimeError(
                f"Dashboard creation failed: {error.get('message', resp)}"
            )
        return resp.get("result", {})

    async def get_current_config(self, url_path: str | None = None) -> dict:
        """Get the Lovelace dashboard config from HA.

        Args:
            url_path: Dashboard url_path, or None for the default dashboard.
        """
        if self._dev_mode:
            filename = self._dev_config_filename(url_path)
            path = _get_output_dir() / filename
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            return {}

        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise RuntimeError("SUPERVISOR_TOKEN not set")

        kwargs: dict[str, Any] = {}
        if url_path is not None:
            kwargs["url_path"] = url_path

        resp = await _ws_call(token, "lovelace/config", **kwargs)
        if not resp.get("success"):
            logger.warning("Failed to get Lovelace config: %s", resp.get("error"))
            return {}
        return resp.get("result", {})

    async def deploy(
        self,
        config: dict,
        url_path: str | None = None,
        backup_enabled: bool = True,
    ) -> dict:
        """Deploy a Lovelace dashboard config.

        Args:
            config: The Lovelace config dict (must have a "views" key).
            url_path: Target dashboard url_path, or None for default.
            backup_enabled: Whether to back up the current config first.

        Returns:
            Dict with keys: backup_json (str or None), views_count (int),
            url_path (str or None).
        """
        if "views" not in config:
            raise ValueError("Dashboard config must contain a 'views' key")

        # Backup current config
        backup_json = None
        if backup_enabled:
            try:
                current = await self.get_current_config(url_path)
                if current:
                    backup_json = json.dumps(current, indent=2)
                    if self._dev_mode:
                        backup_name = self._dev_backup_filename(url_path)
                        backup_path = _get_output_dir() / backup_name
                        backup_path.write_text(backup_json, encoding="utf-8")
            except Exception as e:
                logger.warning("Could not backup current dashboard: %s", e)

        if self._dev_mode:
            filename = self._dev_config_filename(url_path)
            output_path = _get_output_dir() / filename
            output_path.write_text(
                json.dumps(config, indent=2), encoding="utf-8"
            )
            logger.info("Dashboard config written to %s", output_path)
        else:
            token = os.environ.get("SUPERVISOR_TOKEN", "")
            if not token:
                raise RuntimeError("SUPERVISOR_TOKEN not set")

            kwargs: dict[str, Any] = {"config": config}
            if url_path is not None:
                kwargs["url_path"] = url_path

            resp = await _ws_call(token, "lovelace/config/save", **kwargs)
            if not resp.get("success"):
                error = resp.get("error", {})
                raise RuntimeError(
                    f"Lovelace save failed: {error.get('message', resp)}"
                )
            logger.info(
                "Dashboard config deployed via Lovelace WS API (url_path=%s)",
                url_path,
            )

        views_count = len(config.get("views", []))
        return {
            "backup_json": backup_json,
            "views_count": views_count,
            "url_path": url_path,
        }

    # -- Dev mode helpers --

    @staticmethod
    def _dev_config_filename(url_path: str | None) -> str:
        if url_path:
            return f"lovelace_{url_path}.json"
        return "lovelace_config.json"

    @staticmethod
    def _dev_backup_filename(url_path: str | None) -> str:
        if url_path:
            return f"lovelace_{url_path}_backup.json"
        return "lovelace_backup.json"

    def _load_dev_dashboards(self) -> list[dict[str, Any]]:
        """Load the dev-mode dashboard registry."""
        registry_path = _get_output_dir() / "dashboards_registry.json"
        if registry_path.exists():
            try:
                return json.loads(registry_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                return []
        return []

    def _save_dev_dashboard(self, entry: dict[str, Any]) -> None:
        """Append a dashboard to the dev-mode registry."""
        dashboards = self._load_dev_dashboards()
        # Don't duplicate
        existing = [d for d in dashboards if d.get("url_path") != entry["url_path"]]
        existing.append(entry)
        registry_path = _get_output_dir() / "dashboards_registry.json"
        registry_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
