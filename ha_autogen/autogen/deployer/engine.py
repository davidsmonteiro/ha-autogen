"""Deploy engine -- write automations and trigger HA reload."""

from __future__ import annotations

import logging
import os
import re
from io import StringIO
from pathlib import Path
from uuid import uuid4

import httpx
from ruamel.yaml import YAML

from autogen.deployer.backup import create_backup

logger = logging.getLogger(__name__)


def _get_config_dir() -> Path:
    """Return the HA config directory path."""
    if os.environ.get("AUTOGEN_DEV_MODE", "").lower() == "true":
        output_dir = (
            Path(__file__).resolve().parent.parent.parent.parent / "tests" / "output"
        )
        output_dir.mkdir(exist_ok=True)
        return output_dir
    return Path("/config")


def _slugify(text: str) -> str:
    """Convert a string to a slug suitable for automation IDs."""
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    slug = slug.strip("_")
    return slug[:64] or "autogen_automation"


def _ensure_automation_id(automation: dict) -> str:
    """Ensure the automation dict has an 'id' field. Return the id."""
    if "id" not in automation or not automation["id"]:
        alias = automation.get("alias", "autogen_automation")
        automation["id"] = _slugify(alias) + "_" + uuid4().hex[:8]
    return automation["id"]


class DeployEngine:
    """Manages writing automation YAML and triggering HA reloads."""

    def __init__(self) -> None:
        self._config_dir = _get_config_dir()
        self._dev_mode = os.environ.get("AUTOGEN_DEV_MODE", "").lower() == "true"
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.default_flow_style = False

    @property
    def automations_path(self) -> Path:
        return self._config_dir / "automations.yaml"

    def read_current_automations(self) -> list[dict]:
        """Read and parse the current automations.yaml."""
        if not self.automations_path.exists():
            return []
        content = self.automations_path.read_text(encoding="utf-8")
        if not content.strip():
            return []
        parsed = self._yaml.load(StringIO(content))
        if parsed is None:
            return []
        if isinstance(parsed, list):
            return list(parsed)
        return [parsed]

    async def deploy(
        self,
        yaml_str: str,
        backup_enabled: bool = True,
    ) -> dict:
        """Deploy an automation to automations.yaml.

        Returns dict with keys: automation_id, backup_path, replaced.
        """
        new_automation = self._yaml.load(StringIO(yaml_str))
        if new_automation is None:
            raise ValueError("Cannot deploy empty YAML")

        automation_id = _ensure_automation_id(new_automation)

        # Backup current file
        backup_path = None
        if backup_enabled and self.automations_path.exists():
            backup_path = create_backup(self.automations_path)

        # Read current automations
        current = self.read_current_automations()

        # Check if automation with same id exists (update vs append)
        replaced = False
        for i, existing in enumerate(current):
            if isinstance(existing, dict) and existing.get("id") == automation_id:
                current[i] = new_automation
                replaced = True
                break

        if not replaced:
            current.append(new_automation)

        # Write back
        buf = StringIO()
        self._yaml.dump(current, buf)
        self.automations_path.write_text(buf.getvalue(), encoding="utf-8")

        # Trigger HA reload (skip in dev mode)
        if not self._dev_mode:
            await self._trigger_reload()

        return {
            "automation_id": automation_id,
            "backup_path": str(backup_path) if backup_path else None,
            "replaced": replaced,
        }

    async def _trigger_reload(self) -> None:
        """Call the HA REST API to reload automations."""
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise RuntimeError("SUPERVISOR_TOKEN not set")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "http://supervisor/core/api/services/automation/reload",
                headers={"Authorization": f"Bearer {token}"},
            )
            resp.raise_for_status()
            logger.info("Automation reload triggered successfully")
