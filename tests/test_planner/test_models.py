"""Tests for planner data models."""

from __future__ import annotations

from autogen.planner.models import ApprovedPlan, EntitySelection, PlanResponse


class TestEntitySelection:
    def test_defaults(self) -> None:
        e = EntitySelection(entity_id="light.living_room")
        assert e.entity_id == "light.living_room"
        assert e.friendly_name == ""
        assert e.role == ""
        assert e.alternatives == []

    def test_full_fields(self) -> None:
        e = EntitySelection(
            entity_id="light.living_room",
            friendly_name="Living Room Light",
            role="action",
            alternatives=["light.living_room_dimmer"],
        )
        assert e.friendly_name == "Living Room Light"
        assert e.role == "action"
        assert e.alternatives == ["light.living_room_dimmer"]


class TestPlanResponse:
    def test_defaults(self) -> None:
        p = PlanResponse()
        assert p.entities_selected == []
        assert p.trigger_outline == ""
        assert p.conditions_outline is None
        assert p.actions_outline == ""
        assert p.layout_outline is None
        assert p.assumptions == []
        assert p.questions == []
        assert p.suggestions == []

    def test_automation_mode_fields(self) -> None:
        p = PlanResponse(
            entities_selected=[EntitySelection(entity_id="sensor.motion")],
            trigger_outline="When motion detected",
            conditions_outline="After sunset",
            actions_outline="Turn on light",
            assumptions=["Assumed 80% brightness"],
            questions=["Should it turn off automatically?"],
            suggestions=["Add lux sensor condition"],
        )
        assert len(p.entities_selected) == 1
        assert p.trigger_outline == "When motion detected"
        assert p.conditions_outline == "After sunset"
        assert p.layout_outline is None

    def test_dashboard_mode_fields(self) -> None:
        p = PlanResponse(
            entities_selected=[EntitySelection(entity_id="sensor.temp", role="display")],
            layout_outline="View 1: Living Room with gauge cards",
        )
        assert p.layout_outline == "View 1: Living Room with gauge cards"
        assert p.trigger_outline == ""

    def test_serialization_roundtrip(self) -> None:
        p = PlanResponse(
            entities_selected=[
                EntitySelection(entity_id="light.x", role="action", alternatives=["light.y"]),
            ],
            trigger_outline="motion",
            assumptions=["one", "two"],
        )
        data = p.model_dump()
        p2 = PlanResponse.model_validate(data)
        assert p2.entities_selected[0].entity_id == "light.x"
        assert p2.assumptions == ["one", "two"]


class TestApprovedPlan:
    def test_defaults(self) -> None:
        ap = ApprovedPlan()
        assert ap.plan_id == ""
        assert ap.entities_selected == []
        assert ap.answered_questions == {}
        assert ap.user_notes == ""

    def test_with_answered_questions(self) -> None:
        ap = ApprovedPlan(
            plan_id="abc123",
            entities_selected=[EntitySelection(entity_id="light.x")],
            trigger_outline="sunset",
            answered_questions={"Timeout?": "30 min"},
            user_notes="Also add notification",
        )
        assert ap.answered_questions["Timeout?"] == "30 min"
        assert ap.user_notes == "Also add notification"
