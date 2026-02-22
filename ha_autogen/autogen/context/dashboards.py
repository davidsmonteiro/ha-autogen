"""Existing Lovelace dashboard config access via HA WebSocket API."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)


async def fetch_dashboards(
    ws: aiohttp.ClientWebSocketResponse,
    msg_id: int,
) -> dict[str, Any]:
    """Fetch the default Lovelace dashboard config via WS."""
    await ws.send_json({"id": msg_id, "type": "lovelace/config"})
    resp = await ws.receive_json()
    if not resp.get("success"):
        logger.warning("Dashboard config fetch failed: %s", resp)
        return {}
    return resp.get("result", {})


def load_dashboards_from_fixture(fixture_path: Path) -> dict[str, Any]:
    """Load Lovelace dashboard config from a JSON fixture file (dev mode)."""
    if not fixture_path.exists():
        return {}
    content = fixture_path.read_text(encoding="utf-8")
    if not content.strip():
        return {}
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        logger.warning("Failed to parse dashboard fixture: %s", fixture_path)
        return {}
    if not isinstance(parsed, dict):
        return {}
    return parsed
