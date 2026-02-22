"""Dashboard deploy engine -- deploy Lovelace configs via HA Storage API."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)


def _get_output_dir() -> Path:
    """Return the output directory for dev mode dashboard writes."""
    output_dir = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "output"
    output_dir.mkdir(exist_ok=True)
    return output_dir


class DashboardDeployEngine:
    """Manages deploying Lovelace dashboard configs to Home Assistant."""

    def __init__(self) -> None:
        self._dev_mode = os.environ.get("AUTOGEN_DEV_MODE", "").lower() == "true"

    async def get_current_config(self) -> dict:
        """Get the current Lovelace dashboard config from HA."""
        if self._dev_mode:
            path = _get_output_dir() / "lovelace_config.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
            return {}

        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise RuntimeError("SUPERVISOR_TOKEN not set")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                "http://supervisor/core/api/lovelace/config",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            return resp.json()

    async def deploy(self, config: dict, backup_enabled: bool = True) -> dict:
        """Deploy a Lovelace dashboard config.

        Args:
            config: The Lovelace config dict (must have a "views" key).
            backup_enabled: Whether to back up the current config first.

        Returns:
            Dict with keys: backup_json (str or None), views_count (int).
        """
        if "views" not in config:
            raise ValueError("Dashboard config must contain a 'views' key")

        # Backup current config
        backup_json = None
        if backup_enabled:
            try:
                current = await self.get_current_config()
                if current:
                    backup_json = json.dumps(current, indent=2)
                    if self._dev_mode:
                        backup_path = _get_output_dir() / "lovelace_backup.json"
                        backup_path.write_text(backup_json, encoding="utf-8")
            except Exception as e:
                logger.warning("Could not backup current dashboard: %s", e)

        if self._dev_mode:
            # Write to local file
            output_path = _get_output_dir() / "lovelace_config.json"
            output_path.write_text(
                json.dumps(config, indent=2), encoding="utf-8"
            )
            logger.info("Dashboard config written to %s", output_path)
        else:
            # POST to HA Lovelace storage API
            token = os.environ.get("SUPERVISOR_TOKEN", "")
            if not token:
                raise RuntimeError("SUPERVISOR_TOKEN not set")

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    "http://supervisor/core/api/lovelace/config",
                    headers={"Authorization": f"Bearer {token}"},
                    json=config,
                )
                resp.raise_for_status()
                logger.info("Dashboard config deployed via Lovelace API")

        views_count = len(config.get("views", []))
        return {
            "backup_json": backup_json,
            "views_count": views_count,
        }
