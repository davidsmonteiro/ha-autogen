"""Tests for PlannerEngine."""

from __future__ import annotations

import json

import pytest

from autogen.context.entities import EntityEntry
from autogen.llm.base import LLMBackend, LLMResponse
from autogen.planner.engine import PlannerEngine
from autogen.planner.models import ApprovedPlan, EntitySelection


class MockLLM(LLMBackend):
    """Controllable mock LLM backend."""

    def __init__(self, content: str = "", fail: bool = False) -> None:
        self._content = content
        self._fail = fail

    async def generate(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        if self._fail:
            raise RuntimeError("LLM failure")
        return LLMResponse(
            content=self._content,
            model="mock-model",
            prompt_tokens=100,
            completion_tokens=50,
        )

    async def health_check(self) -> bool:
        return not self._fail


def _entity(entity_id: str, name: str = "") -> EntityEntry:
    return EntityEntry(entity_id=entity_id, name=name or entity_id, domain=entity_id.split(".")[0])


def _plan_json(**overrides) -> str:
    data = {
        "entities_selected": [
            {"entity_id": "light.living_room", "friendly_name": "Living Room Light", "role": "action", "alternatives": []}
        ],
        "trigger_outline": "When motion detected",
        "conditions_outline": "After sunset",
        "actions_outline": "Turn on light",
        "assumptions": ["Assumed 80% brightness"],
        "questions": ["Should it turn off?"],
        "suggestions": ["Add lux condition"],
    }
    data.update(overrides)
    return "```json\n" + json.dumps(data) + "\n```"


class TestParsePlan:
    def test_parse_valid_json(self) -> None:
        engine = PlannerEngine(MockLLM())
        entities = [_entity("light.living_room", "Living Room Light")]
        plan = engine._parse_plan(_plan_json(), entities)
        assert len(plan.entities_selected) == 1
        assert plan.entities_selected[0].entity_id == "light.living_room"
        assert plan.trigger_outline == "When motion detected"
        assert plan.assumptions == ["Assumed 80% brightness"]
        assert plan.questions == ["Should it turn off?"]
        assert plan.suggestions == ["Add lux condition"]

    def test_parse_enriches_entity_names(self) -> None:
        engine = PlannerEngine(MockLLM())
        # LLM omits friendly_name, engine should fill from known entities
        content = '```json\n{"entities_selected":[{"entity_id":"light.living_room","role":"action"}]}\n```'
        entities = [_entity("light.living_room", "My Living Room")]
        plan = engine._parse_plan(content, entities)
        assert plan.entities_selected[0].friendly_name == "My Living Room"

    def test_parse_no_code_fence(self) -> None:
        engine = PlannerEngine(MockLLM())
        raw_json = json.dumps({"trigger_outline": "sunset", "entities_selected": []})
        plan = engine._parse_plan(raw_json, [])
        assert plan.trigger_outline == "sunset"

    def test_parse_invalid_json(self) -> None:
        engine = PlannerEngine(MockLLM())
        plan = engine._parse_plan("not json at all", [])
        assert plan.entities_selected == []
        assert plan.trigger_outline == ""

    def test_parse_non_dict_json(self) -> None:
        engine = PlannerEngine(MockLLM())
        plan = engine._parse_plan('```json\n["a","b"]\n```', [])
        assert plan.entities_selected == []

    def test_parse_dashboard_mode(self) -> None:
        engine = PlannerEngine(MockLLM())
        content = _plan_json(
            layout_outline="View 1: Living Room gauges",
            trigger_outline="",
        )
        plan = engine._parse_plan(content, [])
        assert plan.layout_outline == "View 1: Living Room gauges"


class TestCreatePlan:
    @pytest.mark.asyncio
    async def test_create_plan_automation(self) -> None:
        llm = MockLLM(content=_plan_json())
        engine = PlannerEngine(llm)
        entities = [_entity("light.living_room")]

        plan, llm_resp = await engine.create_plan(
            "Turn on lights", "automation", "## Entities\nlight.living_room", entities,
        )
        assert plan.trigger_outline == "When motion detected"
        assert llm_resp.model == "mock-model"
        assert llm_resp.prompt_tokens == 100

    @pytest.mark.asyncio
    async def test_create_plan_dashboard(self) -> None:
        content = _plan_json(layout_outline="Gauge cards", trigger_outline="")
        llm = MockLLM(content=content)
        engine = PlannerEngine(llm)

        plan, _ = await engine.create_plan(
            "Temp dashboard", "dashboard", "## Entities\nsensor.temp", [],
        )
        assert plan.layout_outline == "Gauge cards"


class TestRefinePlan:
    @pytest.mark.asyncio
    async def test_refine_plan(self) -> None:
        refined_json = _plan_json(
            trigger_outline="At sunset every day",
            assumptions=["Changed to time-based"],
        )
        llm = MockLLM(content=refined_json)
        engine = PlannerEngine(llm)
        prev = ApprovedPlan(
            entities_selected=[EntitySelection(entity_id="light.living_room", role="action")],
            trigger_outline="When motion detected",
        )

        plan, _ = await engine.refine_plan(
            "Motion lights", "automation", "ctx", prev, "Use time-based trigger", [],
        )
        assert plan.trigger_outline == "At sunset every day"
        assert plan.assumptions == ["Changed to time-based"]


class TestGenerateFromPlan:
    @pytest.mark.asyncio
    async def test_generate_from_plan(self) -> None:
        yaml_content = "```yaml\nautomation:\n  trigger:\n    platform: sun\n```"
        llm = MockLLM(content=yaml_content)
        engine = PlannerEngine(llm)
        approved = ApprovedPlan(
            entities_selected=[EntitySelection(entity_id="light.living_room")],
            trigger_outline="At sunset",
            actions_outline="Turn on light",
        )

        resp = await engine.generate_from_plan(
            approved, "Sunset lights", "automation", "You are HA AutoGen...",
        )
        assert "automation:" in resp.content
        assert resp.model == "mock-model"
