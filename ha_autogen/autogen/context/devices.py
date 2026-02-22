"""Device registry access via HA WebSocket API."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class DeviceEntry(BaseModel):
    """A single device from the HA device registry."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str | None = None
    name_by_user: str | None = None
    area_id: str | None = None
    disabled_by: str | None = None
    manufacturer: str | None = None
    model: str | None = None


async def fetch_devices(
    ws: aiohttp.ClientWebSocketResponse,
    msg_id: int,
) -> list[DeviceEntry]:
    """Send config/device_registry/list over an authenticated WS and parse response."""
    await ws.send_json({"id": msg_id, "type": "config/device_registry/list"})
    resp = await ws.receive_json()
    if not resp.get("success"):
        raise RuntimeError(f"Device registry fetch failed: {resp}")
    return [DeviceEntry.model_validate(d) for d in resp["result"]]


def load_devices_from_fixture(fixture_path: Path) -> list[DeviceEntry]:
    """Load device data from a JSON fixture file (dev mode)."""
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [DeviceEntry.model_validate(d) for d in data]
