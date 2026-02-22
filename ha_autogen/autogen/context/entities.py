"""Entity registry access via HA WebSocket API."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import aiohttp
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


class EntityEntry(BaseModel):
    """A single entity from the HA entity registry."""

    model_config = ConfigDict(extra="ignore")

    entity_id: str
    name: str | None = None
    platform: str = ""
    device_id: str | None = None
    area_id: str | None = None
    disabled_by: str | None = None
    hidden_by: str | None = None
    labels: list[str] = Field(default_factory=list)

    @property
    def domain(self) -> str:
        """Extract domain from entity_id (e.g., 'light' from 'light.living_room')."""
        return self.entity_id.split(".", 1)[0]


async def fetch_entities(
    ws: aiohttp.ClientWebSocketResponse,
    msg_id: int,
) -> list[EntityEntry]:
    """Send config/entity_registry/list over an authenticated WS and parse response."""
    await ws.send_json({"id": msg_id, "type": "config/entity_registry/list"})
    resp = await ws.receive_json()
    if not resp.get("success"):
        raise RuntimeError(f"Entity registry fetch failed: {resp}")
    return [EntityEntry.model_validate(e) for e in resp["result"]]


def load_entities_from_fixture(fixture_path: Path) -> list[EntityEntry]:
    """Load entity data from a JSON fixture file (dev mode)."""
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    return [EntityEntry.model_validate(e) for e in data]
