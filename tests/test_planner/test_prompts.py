"""Tests for planner prompt builders."""

from __future__ import annotations

from autogen.planner.models import ApprovedPlan, EntitySelection
from autogen.planner.prompts import (
    PLAN_SYSTEM_PROMPT_AUTOMATION,
    PLAN_SYSTEM_PROMPT_DASHBOARD,
    build_generate_from_plan_user_prompt,
    build_plan_user_prompt,
    build_refinement_user_prompt,
)


class TestSystemPrompts:
    def test_automation_system_prompt_mentions_plan(self) -> None:
        assert "plan" in PLAN_SYSTEM_PROMPT_AUTOMATION.lower()
        assert "YAML" in PLAN_SYSTEM_PROMPT_AUTOMATION  # says NOT to generate YAML

    def test_dashboard_system_prompt_mentions_lovelace(self) -> None:
        assert "lovelace" in PLAN_SYSTEM_PROMPT_DASHBOARD.lower() or "dashboard" in PLAN_SYSTEM_PROMPT_DASHBOARD.lower()

    def test_automation_system_prompt_has_json_format(self) -> None:
        assert "```json" in PLAN_SYSTEM_PROMPT_AUTOMATION

    def test_dashboard_system_prompt_has_json_format(self) -> None:
        assert "```json" in PLAN_SYSTEM_PROMPT_DASHBOARD


class TestBuildPlanUserPrompt:
    def test_automation_prompt(self) -> None:
        result = build_plan_user_prompt("Turn on lights at sunset", "automation")
        assert "Turn on lights at sunset" in result
        assert "automation" in result
        assert "Do NOT generate YAML" in result

    def test_dashboard_prompt(self) -> None:
        result = build_plan_user_prompt("Create a living room dashboard", "dashboard")
        assert "Create a living room dashboard" in result
        assert "dashboard" in result


class TestBuildRefinementUserPrompt:
    def test_includes_previous_plan(self) -> None:
        prev = ApprovedPlan(
            entities_selected=[
                EntitySelection(entity_id="light.living_room", role="action"),
            ],
            trigger_outline="When motion detected",
            conditions_outline="After sunset",
            actions_outline="Turn on light at 80%",
            assumptions=["Assumed 80% brightness"],
            answered_questions={"Timeout?": "5 min"},
        )
        result = build_refinement_user_prompt(
            "Turn on lights with motion", prev, "Change to time-based trigger", "automation",
        )
        assert "light.living_room" in result
        assert "When motion detected" in result
        assert "Change to time-based trigger" in result
        assert "Timeout?" in result
        assert "5 min" in result

    def test_dashboard_mode(self) -> None:
        prev = ApprovedPlan(
            layout_outline="Two views: Living Room and Kitchen",
        )
        result = build_refinement_user_prompt(
            "Dashboard for all rooms", prev, "Add bedroom", "dashboard",
        )
        assert "Two views: Living Room and Kitchen" in result
        assert "Add bedroom" in result
        assert "dashboard" in result

    def test_empty_previous_plan(self) -> None:
        prev = ApprovedPlan()
        result = build_refinement_user_prompt("Request", prev, "notes", "automation")
        assert "Request" in result
        assert "notes" in result


class TestBuildGenerateFromPlanUserPrompt:
    def test_includes_all_plan_sections(self) -> None:
        plan = ApprovedPlan(
            entities_selected=[
                EntitySelection(entity_id="sensor.motion", role="trigger"),
                EntitySelection(entity_id="light.living", role="action", alternatives=["light.dimmer"]),
            ],
            trigger_outline="binary_sensor motion state on",
            conditions_outline="After sunset",
            actions_outline="Turn on living room light",
            assumptions=["Using 80% brightness"],
            answered_questions={"Timeout?": "10 min"},
            user_notes="Also flash light briefly",
        )
        result = build_generate_from_plan_user_prompt("Motion lights", plan, "automation")
        assert "sensor.motion" in result
        assert "light.living" in result
        assert "light.dimmer" in result  # alternatives
        assert "binary_sensor motion state on" in result
        assert "After sunset" in result
        assert "Turn on living room light" in result
        assert "Using 80% brightness" in result
        assert "Timeout?" in result
        assert "10 min" in result
        assert "Also flash light briefly" in result
        assert "automation" in result.lower()

    def test_dashboard_mode(self) -> None:
        plan = ApprovedPlan(
            layout_outline="One view with gauge cards",
        )
        result = build_generate_from_plan_user_prompt("Temp dashboard", plan, "dashboard")
        assert "One view with gauge cards" in result
        assert "dashboard" in result.lower()
