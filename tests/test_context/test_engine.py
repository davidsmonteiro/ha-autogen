"""Tests for the context engine."""

import pytest

from autogen.context.engine import ContextEngine
from autogen.context.entities import EntityEntry


@pytest.mark.asyncio
async def test_refresh_loads_fixtures() -> None:
    """Context engine loads fixture data in dev mode."""
    engine = ContextEngine()
    await engine.refresh()
    assert len(engine.entities) > 0
    assert len(engine.areas) > 0
    assert len(engine.devices) > 0


@pytest.mark.asyncio
async def test_get_active_entities_filters_disabled() -> None:
    """Disabled/hidden entities are excluded."""
    engine = ContextEngine()
    await engine.refresh()
    active = engine.get_active_entities()
    for entity in active:
        assert entity.disabled_by is None
        assert entity.hidden_by is None
    assert len(active) < len(engine.entities)


@pytest.mark.asyncio
async def test_filter_entities_by_request_relevance() -> None:
    """Entities matching the request keywords score higher."""
    engine = ContextEngine()
    await engine.refresh()

    # Use "light" domain which exists in any HA instance
    filtered = engine.filter_entities_by_request("turn on the light")
    entity_ids = [e.entity_id for e in filtered]
    domains = [e.domain for e in filtered]

    # Light entities should be prioritised
    assert "light" in domains
    # First result should be a light entity (domain boost = 3.0)
    assert filtered[0].domain == "light"


@pytest.mark.asyncio
async def test_filter_respects_max_entities() -> None:
    """Max entities limit is enforced."""
    engine = ContextEngine()
    await engine.refresh()
    filtered = engine.filter_entities_by_request("everything", max_entities=3)
    assert len(filtered) <= 3


def test_entity_domain_property() -> None:
    """EntityEntry.domain extracts domain from entity_id."""
    entity = EntityEntry(entity_id="light.living_room_main", name="Test")
    assert entity.domain == "light"

    entity2 = EntityEntry(entity_id="binary_sensor.motion", name="Motion")
    assert entity2.domain == "binary_sensor"


@pytest.mark.asyncio
async def test_device_area_resolution() -> None:
    """Entities with no area_id inherit it from their device."""
    engine = ContextEngine()
    await engine.refresh()

    # cover.brisa_escritorio has area_id=null in the entity registry,
    # but its device has area_id="office".
    # After resolution, the entity should have area_id set.
    brisa = next(
        (e for e in engine.entities if e.entity_id == "cover.brisa_escritorio"),
        None,
    )
    assert brisa is not None
    assert brisa.area_id == "office"

    # Same for light.office_led_desk -> device -> office
    led = next(
        (e for e in engine.entities if e.entity_id == "light.office_led_desk"),
        None,
    )
    assert led is not None
    assert led.area_id == "office"


@pytest.mark.asyncio
async def test_room_expansion() -> None:
    """When an entity matches, all sibling entities from the same room are included."""
    engine = ContextEngine()
    await engine.refresh()

    # "office lights" should directly match light.office_lights_l1.
    # That entity is in the "office" area (via device).
    # Room expansion should pull in cover.brisa_escritorio and
    # light.office_led_desk from the same room.
    filtered = engine.filter_entities_by_request("office lights")
    entity_ids = {e.entity_id for e in filtered}

    assert "light.office_lights_l1" in entity_ids
    assert "cover.brisa_escritorio" in entity_ids, (
        "Room expansion should include cover.brisa_escritorio from office area"
    )
    assert "light.office_led_desk" in entity_ids, (
        "Room expansion should include light.office_led_desk from office area"
    )
