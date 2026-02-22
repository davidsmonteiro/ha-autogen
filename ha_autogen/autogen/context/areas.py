"""Area registry access via HA WebSocket API."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class AreaEntry(BaseModel):
    """A single area from the HA area registry."""

    model_config = ConfigDict(extra="ignore")

    area_id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    floor_id: str | None = None
    icon: str | None = None
    labels: list[str] = Field(default_factory=list)
    picture: str | None = None


async def fetch_areas(
    ws: aiohttp.ClientWebSocketResponse,
    msg_id: int,
) -> list[AreaEntry]:
    """Send config/area_registry/list over an authenticated WS and parse response."""
    await ws.send_json({"id": msg_id, "type": "config/area_registry/list"})
    resp = await ws.receive_json()
    if not resp.get("success"):
        raise RuntimeError(f"Area registry fetch failed: {resp}")
    return [AreaEntry.model_validate(a) for a in resp["result"]]


def load_areas_from_fixture(fixture_path: Path) -> list[AreaEntry]:
    """Load area data from a JSON fixture file (dev mode)."""
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [AreaEntry.model_validate(a) for a in data]
