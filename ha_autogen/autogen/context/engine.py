"""Context engine -- orchestrates registry data for prompt construction."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import aiohttp

from typing import Any

from autogen.context.areas import (
    AreaEntry,
    fetch_areas,
    load_areas_from_fixture,
)
from autogen.context.automations import (
    fetch_automations,
    load_automations_from_fixture,
)
from autogen.context.dashboards import (
    fetch_dashboards,
    load_dashboards_from_fixture,
)
from autogen.context.devices import (
    DeviceEntry,
    fetch_devices,
    load_devices_from_fixture,
)
from autogen.context.entities import (
    EntityEntry,
    fetch_entities,
    load_entities_from_fixture,
)

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "tests" / "fixtures"


class ContextEngine:
    """Pulls and caches HA registry data, provides filtered context for prompts."""

    def __init__(self) -> None:
        self._entities: list[EntityEntry] = []
        self._areas: list[AreaEntry] = []
        self._devices: list[DeviceEntry] = []
        self._automations: list[dict[str, Any]] = []
        self._dashboards: dict[str, Any] = {}
        self._dev_mode: bool = os.environ.get("AUTOGEN_DEV_MODE", "").lower() == "true"

    @property
    def entities(self) -> list[EntityEntry]:
        return self._entities

    @property
    def areas(self) -> list[AreaEntry]:
        return self._areas

    @property
    def devices(self) -> list[DeviceEntry]:
        return self._devices

    @property
    def automations(self) -> list[dict[str, Any]]:
        return self._automations

    @property
    def dashboards(self) -> dict[str, Any]:
        return self._dashboards

    async def refresh(self) -> None:
        """Pull fresh registry data from HA or load fixtures in dev mode."""
        if self._dev_mode:
            await self._load_fixtures()
        else:
            await self._fetch_from_ha()

        self._resolve_entity_areas()

        dashboard_views = len(self._dashboards.get("views", []))
        logger.info(
            "Context refreshed: %d entities, %d devices, %d areas, %d automations, %d dashboard views",
            len(self._entities),
            len(self._devices),
            len(self._areas),
            len(self._automations),
            dashboard_views,
        )

    def _resolve_entity_areas(self) -> None:
        """Fill in entity area_id from the device registry when the entity has none.

        Many HA entities have area_id=null but belong to a device that has an
        area assigned. This resolves entity -> device -> area so that area-based
        filtering works correctly.
        """
        device_area_map = {d.id: d.area_id for d in self._devices if d.area_id}
        resolved = 0

        for entity in self._entities:
            if entity.area_id is None and entity.device_id:
                device_area = device_area_map.get(entity.device_id)
                if device_area:
                    entity.area_id = device_area
                    resolved += 1

        if resolved:
            logger.info("Resolved area_id for %d entities via device registry", resolved)

    async def _load_fixtures(self) -> None:
        """Load mock data from test fixtures."""
        self._entities = load_entities_from_fixture(
            FIXTURES_DIR / "entity_registry.json"
        )
        self._areas = load_areas_from_fixture(FIXTURES_DIR / "area_registry.json")

        device_fixture = FIXTURES_DIR / "device_registry.json"
        if device_fixture.exists():
            self._devices = load_devices_from_fixture(device_fixture)

        automations_fixture = FIXTURES_DIR / "sample_automations.yaml"
        self._automations = load_automations_from_fixture(automations_fixture)

        dashboard_fixture = FIXTURES_DIR / "sample_lovelace.json"
        self._dashboards = load_dashboards_from_fixture(dashboard_fixture)

    async def _fetch_from_ha(self) -> None:
        """Connect to HA WebSocket API and pull registries."""
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            raise RuntimeError("SUPERVISOR_TOKEN not set; cannot connect to HA")

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(
                "ws://supervisor/core/websocket",
            ) as ws:
                # Auth handshake
                auth_msg = await ws.receive_json()
                if auth_msg.get("type") != "auth_required":
                    raise RuntimeError(f"Unexpected WS message: {auth_msg}")
                await ws.send_json({"type": "auth", "access_token": token})
                auth_resp = await ws.receive_json()
                if auth_resp.get("type") != "auth_ok":
                    raise RuntimeError(f"WS auth failed: {auth_resp}")

                # Pull registries
                msg_id = 1
                self._entities = await fetch_entities(ws, msg_id)
                msg_id += 1
                self._areas = await fetch_areas(ws, msg_id)
                msg_id += 1
                self._devices = await fetch_devices(ws, msg_id)
                msg_id += 1
                self._automations = await fetch_automations(ws, msg_id)
                msg_id += 1
                self._dashboards = await fetch_dashboards(ws, msg_id)

    def get_active_entities(self) -> list[EntityEntry]:
        """Return only entities that are not disabled or hidden."""
        return [
            e
            for e in self._entities
            if e.disabled_by is None and e.hidden_by is None
        ]

    def get_entity_area_map(self) -> dict[str, str | None]:
        """Return a mapping of entity_id → area_id for all entities."""
        return {e.entity_id: e.area_id for e in self._entities}

    def filter_entities_by_request(
        self,
        request: str,
        max_entities: int = 200,
    ) -> list[EntityEntry]:
        """Filter entities by relevance to the user's request.

        Scoring: domain match (3.0) > entity_id overlap (2.0) > name overlap (1.5) > area overlap (1.0).
        After scoring, expands results to include all entities from rooms where
        at least one entity had a keyword match (entity_id, name, or area — not
        just domain). This prevents a bare domain mention like "light" from
        expanding every room in the house.
        """
        active = self.get_active_entities()
        request_lower = request.lower()
        keywords = set(request_lower.split())

        area_names = {a.area_id: a.name.lower() for a in self._areas}

        # scored entries: (total_score, keyword_score, entity)
        # keyword_score tracks non-domain matches used for room expansion
        scored: list[tuple[float, float, EntityEntry]] = []
        for entity in active:
            score = 0.0
            keyword_score = 0.0

            # Match against entity_id parts
            id_parts = set(
                entity.entity_id.replace(".", " ").replace("_", " ").lower().split()
            )
            id_match = len(keywords & id_parts) * 2.0
            score += id_match
            keyword_score += id_match

            # Match against entity name
            if entity.name:
                name_parts = set(entity.name.lower().split())
                name_match = len(keywords & name_parts) * 1.5
                score += name_match
                keyword_score += name_match

            # Match against area name
            if entity.area_id and entity.area_id in area_names:
                area_parts = set(area_names[entity.area_id].replace("_", " ").split())
                area_match = len(keywords & area_parts) * 1.0
                score += area_match
                keyword_score += area_match

            # Domain relevance boost (does NOT count toward keyword_score)
            if entity.domain in request_lower:
                score += 3.0

            scored.append((score, keyword_score, entity))

        scored.sort(key=lambda x: (-x[0], x[2].entity_id))

        if not any(s > 0 for s, _, _ in scored):
            return [e for _, _, e in scored[:max_entities]]

        # Room expansion: collect areas from entities that matched on multiple
        # keywords (score > 2.0 = more than one keyword hit). This prevents a
        # single common word like "lights" from expanding every room.
        keyword_matched_areas = {
            e.area_id for _, ks, e in scored if ks > 2.0 and e.area_id
        }

        # Build result in priority order:
        # 1. Keyword-matched entities (sorted by total score)
        # 2. Room siblings from keyword-matched areas
        # 3. Domain-only matches (fill remaining)
        result: list[EntityEntry] = []
        seen: set[str] = set()

        # Priority 1: entities with keyword matches
        for s, ks, e in scored:
            if s > 0 and ks > 0 and e.entity_id not in seen:
                result.append(e)
                seen.add(e.entity_id)

        # Priority 2: room siblings from keyword-matched areas
        if keyword_matched_areas:
            for e in active:
                if e.area_id in keyword_matched_areas and e.entity_id not in seen:
                    result.append(e)
                    seen.add(e.entity_id)

        # Priority 3: domain-only matches
        for s, ks, e in scored:
            if s > 0 and ks == 0 and e.entity_id not in seen:
                result.append(e)
                seen.add(e.entity_id)

        return result[:max_entities]
