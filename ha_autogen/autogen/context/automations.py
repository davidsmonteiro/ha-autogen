"""Existing automation config access via HA WebSocket API."""

from __future__ import annotations

import logging
from io import StringIO
from pathlib import Path
from typing import Any

import aiohttp
from ruamel.yaml import YAML

logger = logging.getLogger(__name__)

_yaml = YAML()
_yaml.preserve_quotes = True


async def fetch_automations(
    ws: aiohttp.ClientWebSocketResponse,
    msg_id: int,
) -> list[dict[str, Any]]:
    """Fetch automation configs via WS config/automation/config/list."""
    await ws.send_json({"id": msg_id, "type": "config/automation/config/list"})
    resp = await ws.receive_json()
    if not resp.get("success"):
        raise RuntimeError(f"Automation config fetch failed: {resp}")
    return resp["result"]


def load_automations_from_fixture(fixture_path: Path) -> list[dict[str, Any]]:
    """Load automation configs from a YAML fixture file (dev mode)."""
    if not fixture_path.exists():
        return []
    content = fixture_path.read_text(encoding="utf-8")
    if not content.strip():
        return []
    parsed = _yaml.load(StringIO(content))
    if parsed is None:
        return []
    if isinstance(parsed, list):
        return [dict(a) if hasattr(a, "items") else a for a in parsed]
    return [dict(parsed) if hasattr(parsed, "items") else parsed]
