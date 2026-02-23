"""Tests for autogen.explorer.engine — ExplorerEngine with mocked LLM and context."""

from __future__ import annotations

import json

import pytest

from autogen.context.areas import AreaEntry
from autogen.context.entities import EntityEntry
from autogen.explorer.engine import ExplorerEngine
from autogen.llm.base import LLMBackend, LLMResponse


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(
    entity_id: str,
    name: str | None = None,
    area_id: str | None = None,
    disabled_by: str | None = None,
    hidden_by: str | None = None,
) -> EntityEntry:
    """Create an EntityEntry for testing."""
    return EntityEntry(
        entity_id=entity_id,
        name=name,
        platform="test",
        device_id=None,
        area_id=area_id,
        disabled_by=disabled_by,
        hidden_by=hidden_by,
        labels=[],
    )


def _area(area_id: str, name: str) -> AreaEntry:
    """Create an AreaEntry for testing."""
    return AreaEntry(
        area_id=area_id,
        name=name,
        aliases=[],
        floor_id=None,
        icon=None,
        labels=[],
        picture=None,
    )


# ---------------------------------------------------------------------------
# Mock classes
# ---------------------------------------------------------------------------

class MockLLM(LLMBackend):
    """A mock LLM backend for testing the explorer engine."""

    def __init__(self, content: str = "", should_fail: bool = False) -> None:
        self._model = "mock-model"
        self._content = content
        self._should_fail = should_fail

    async def generate(self, system_prompt: str, user_prompt: str, reasoning_model: str | None = None) -> LLMResponse:
        if self._should_fail:
            raise RuntimeError("LLM unavailable")
        return LLMResponse(
            content=self._content,
            model="mock-model",
            prompt_tokens=100,
            completion_tokens=50,
        )

    async def health_check(self) -> bool:
        return True


class MockContextEngine:
    """A mock ContextEngine that returns fixture data."""

    def __init__(
        self,
        entities: list[EntityEntry],
        areas: list[AreaEntry],
        automations: list[dict],
    ) -> None:
        self._entities = entities
        self._areas = areas
        self._automations = automations

    def get_active_entities(self) -> list[EntityEntry]:
        return self._entities

    @property
    def areas(self) -> list[AreaEntry]:
        return self._areas

    @property
    def automations(self) -> list[dict]:
        return self._automations


# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

def _make_context_engine() -> MockContextEngine:
    """Build a MockContextEngine with a realistic set of entities."""
    entities = [
        _entity("binary_sensor.motion_kitchen", "Kitchen Motion", area_id="kitchen"),
        _entity("light.kitchen_ceiling", "Kitchen Ceiling Light", area_id="kitchen"),
        _entity("sensor.temperature_kitchen", "Kitchen Temperature", area_id="kitchen"),
        _entity("light.living_room", "Living Room Light", area_id="living_room"),
        _entity("binary_sensor.motion_living_room", "Living Room Motion", area_id="living_room"),
        _entity("switch.porch_light", "Porch Light Switch", area_id="porch"),
        _entity("sensor.humidity_bathroom", "Bathroom Humidity", area_id="bathroom"),
        _entity("fan.bathroom_exhaust", "Bathroom Exhaust Fan", area_id="bathroom"),
    ]
    areas = [
        _area("kitchen", "Kitchen"),
        _area("living_room", "Living Room"),
        _area("porch", "Porch"),
        _area("bathroom", "Bathroom"),
    ]
    automations = [
        {
            "alias": "Kitchen Motion Light",
            "trigger": [{"platform": "state", "entity_id": "binary_sensor.motion_kitchen", "to": "on"}],
            "action": [{"service": "light.turn_on", "target": {"entity_id": "light.kitchen_ceiling"}}],
        },
    ]
    return MockContextEngine(entities, areas, automations)


def _make_valid_llm_suggestions() -> str:
    """Return a valid JSON response from the LLM with automation suggestions."""
    suggestions = [
        {
            "title": "Motion-activated living room lights",
            "description": "Turn on living room lights when motion is detected.",
            "entities_involved": [
                "binary_sensor.motion_living_room",
                "light.living_room",
            ],
            "area": "Living Room",
            "complexity": "simple",
            "category": "lighting",
            "example_yaml": "alias: Living Room Motion\ntrigger:\n  - platform: state\n    entity_id: binary_sensor.motion_living_room\n    to: 'on'\naction:\n  - service: light.turn_on\n    target:\n      entity_id: light.living_room",
        },
        {
            "title": "Porch light at sunset",
            "description": "Turn on the porch light switch at sunset.",
            "entities_involved": [
                "switch.porch_light",
            ],
            "area": "Porch",
            "complexity": "simple",
            "category": "lighting",
        },
    ]
    return f"Here are my suggestions:\n\n```json\n{json.dumps(suggestions, indent=2)}\n```"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestExplorerEngine:
    @pytest.mark.asyncio
    async def test_explore_with_mock_llm(self) -> None:
        """When the LLM returns valid JSON suggestions, they should appear in the result."""
        context_engine = _make_context_engine()
        llm = MockLLM(content=_make_valid_llm_suggestions())
        engine = ExplorerEngine(llm)

        result = await engine.explore(context_engine)

        # Should have suggestions from the LLM
        assert len(result.suggestions) >= 2
        titles = [s.title for s in result.suggestions]
        assert "Motion-activated living room lights" in titles
        assert "Porch light at sunset" in titles

        # Entity IDs in suggestions should only be valid ones
        for suggestion in result.suggestions:
            for eid in suggestion.entities_involved:
                assert eid in {
                    "binary_sensor.motion_kitchen",
                    "light.kitchen_ceiling",
                    "sensor.temperature_kitchen",
                    "light.living_room",
                    "binary_sensor.motion_living_room",
                    "switch.porch_light",
                    "sensor.humidity_bathroom",
                    "fan.bathroom_exhaust",
                }

        # Model metadata should be populated
        assert result.model == "mock-model"
        assert result.prompt_tokens == 100
        assert result.completion_tokens == 50

        # Summary should contain entity/area counts
        assert "8 entities" in result.summary
        assert "4 areas" in result.summary

    @pytest.mark.asyncio
    async def test_explore_llm_failure_fallback(self) -> None:
        """When the LLM fails, explorer should fall back to pattern-based suggestions."""
        context_engine = _make_context_engine()
        llm = MockLLM(should_fail=True)
        engine = ExplorerEngine(llm)

        result = await engine.explore(context_engine)

        # Should still return a result (not raise)
        assert result.total_entities == 8  # 8 active entities
        assert result.total_areas == 4

        # Suggestions should come from pattern matching (fallback)
        assert len(result.suggestions) > 0

        # Model should be empty since LLM failed
        assert result.model == ""
        assert result.prompt_tokens == 0
        assert result.completion_tokens == 0

        # There should be pattern-based suggestions for living_room
        # (binary_sensor.motion_living_room + light.living_room = motion-light pattern)
        living_room_suggestions = [
            s for s in result.suggestions if "Living Room" in s.area
        ]
        assert len(living_room_suggestions) >= 1

    @pytest.mark.asyncio
    async def test_explore_validates_entity_ids(self) -> None:
        """Suggestions with invalid entity IDs should have those IDs filtered out."""
        context_engine = _make_context_engine()

        # LLM returns suggestions with some fake entity IDs
        suggestions = [
            {
                "title": "Mixed entity suggestion",
                "description": "Some entities are valid, some are not.",
                "entities_involved": [
                    "light.living_room",                 # VALID
                    "light.nonexistent_room",             # INVALID
                    "binary_sensor.motion_living_room",   # VALID
                    "sensor.fake_sensor",                 # INVALID
                ],
                "area": "Living Room",
                "complexity": "simple",
                "category": "lighting",
            },
            {
                "title": "All invalid entities",
                "description": "None of these entities exist.",
                "entities_involved": [
                    "light.phantom_light",
                    "switch.ghost_switch",
                ],
                "area": "Phantom Zone",
                "complexity": "moderate",
                "category": "convenience",
            },
        ]
        content = f"```json\n{json.dumps(suggestions)}\n```"
        llm = MockLLM(content=content)
        engine = ExplorerEngine(llm)

        result = await engine.explore(context_engine)

        # Find the "Mixed entity suggestion"
        mixed = next(
            (s for s in result.suggestions if s.title == "Mixed entity suggestion"),
            None,
        )
        assert mixed is not None

        # Only valid entities should remain
        assert "light.living_room" in mixed.entities_involved
        assert "binary_sensor.motion_living_room" in mixed.entities_involved
        assert "light.nonexistent_room" not in mixed.entities_involved
        assert "sensor.fake_sensor" not in mixed.entities_involved

        # The "All invalid entities" suggestion should still exist but with empty entities
        all_invalid = next(
            (s for s in result.suggestions if s.title == "All invalid entities"),
            None,
        )
        assert all_invalid is not None
        assert all_invalid.entities_involved == []

    @pytest.mark.asyncio
    async def test_explore_llm_returns_malformed_json(self) -> None:
        """When the LLM returns unparseable JSON, should fall back to patterns."""
        context_engine = _make_context_engine()
        llm = MockLLM(content="```json\n{this is not valid json\n```")
        engine = ExplorerEngine(llm)

        result = await engine.explore(context_engine)

        # Should not raise, and should have fallback suggestions
        assert result.total_entities == 8
        assert len(result.suggestions) > 0  # Fallback pattern suggestions

    @pytest.mark.asyncio
    async def test_explore_llm_returns_no_code_fence(self) -> None:
        """When the LLM response has no code fence, should fall back to patterns."""
        context_engine = _make_context_engine()
        llm = MockLLM(content="I suggest you automate your lights. Here are some ideas...")
        engine = ExplorerEngine(llm)

        result = await engine.explore(context_engine)

        # Should not raise, and should have fallback suggestions
        assert result.total_entities == 8
        assert len(result.suggestions) > 0

    @pytest.mark.asyncio
    async def test_explore_with_focus_area(self) -> None:
        """Passing focus_area should still work (it is forwarded to the prompt builder)."""
        context_engine = _make_context_engine()
        llm = MockLLM(content=_make_valid_llm_suggestions())
        engine = ExplorerEngine(llm)

        result = await engine.explore(context_engine, focus_area="kitchen")

        # Should return a valid result (focus is only a prompt hint, not a filter on results)
        assert result.total_entities == 8
        assert len(result.suggestions) >= 1

    @pytest.mark.asyncio
    async def test_explore_area_highlights(self) -> None:
        """Area highlights should reflect areas with potential patterns."""
        context_engine = _make_context_engine()
        llm = MockLLM(content=_make_valid_llm_suggestions())
        engine = ExplorerEngine(llm)

        result = await engine.explore(context_engine)

        # area_highlights should only include areas with patterns
        highlight_ids = {h.area_id for h in result.area_highlights}

        # Living Room has binary_sensor + light -> should have a highlight
        # Kitchen entities are all automated, so no pattern -> may or may not appear
        # depending on coverage. Living Room definitely should appear.
        assert "living_room" in highlight_ids

        for highlight in result.area_highlights:
            assert highlight.total_entities > 0
            assert highlight.potential_patterns > 0
