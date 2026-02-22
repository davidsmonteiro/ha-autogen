"""Plan engine — iterative plan-then-generate LLM flow."""

from __future__ import annotations

import json
import logging
import re

from autogen.context.areas import AreaEntry
from autogen.context.entities import EntityEntry
from autogen.llm.base import LLMBackend, LLMResponse
from autogen.planner.models import ApprovedPlan, EntitySelection, PlanResponse
from autogen.planner.prompts import (
    PLAN_SYSTEM_PROMPT_AUTOMATION,
    PLAN_SYSTEM_PROMPT_DASHBOARD,
    build_generate_from_plan_user_prompt,
    build_plan_user_prompt,
    build_refinement_user_prompt,
)

logger = logging.getLogger(__name__)


class PlannerEngine:
    """Orchestrates the iterative plan → refine → generate flow."""

    def __init__(self, llm_backend: LLMBackend) -> None:
        self._llm = llm_backend

    async def create_plan(
        self,
        request: str,
        mode: str,
        context_block: str,
        known_entities: list[EntityEntry],
    ) -> tuple[PlanResponse, LLMResponse]:
        """Create a structured plan from a user request (initial call).

        Returns the parsed PlanResponse and raw LLMResponse for token tracking.
        """
        plan_system = (
            PLAN_SYSTEM_PROMPT_DASHBOARD
            if mode == "dashboard"
            else PLAN_SYSTEM_PROMPT_AUTOMATION
        )
        full_system = f"{plan_system}\n\n{context_block}"
        user_prompt = build_plan_user_prompt(request, mode)

        llm_response = await self._llm.generate(full_system, user_prompt)
        plan = self._parse_plan(llm_response.content, known_entities)
        return plan, llm_response

    async def refine_plan(
        self,
        original_request: str,
        mode: str,
        context_block: str,
        previous_plan: ApprovedPlan,
        refinement_notes: str,
        known_entities: list[EntityEntry],
    ) -> tuple[PlanResponse, LLMResponse]:
        """Refine an existing plan based on user edits and instructions.

        Returns the updated PlanResponse and raw LLMResponse.
        """
        plan_system = (
            PLAN_SYSTEM_PROMPT_DASHBOARD
            if mode == "dashboard"
            else PLAN_SYSTEM_PROMPT_AUTOMATION
        )
        full_system = f"{plan_system}\n\n{context_block}"
        user_prompt = build_refinement_user_prompt(
            original_request, previous_plan, refinement_notes, mode,
        )

        llm_response = await self._llm.generate(full_system, user_prompt)
        plan = self._parse_plan(llm_response.content, known_entities)
        return plan, llm_response

    async def generate_from_plan(
        self,
        approved_plan: ApprovedPlan,
        original_request: str,
        mode: str,
        system_prompt: str,
    ) -> LLMResponse:
        """Generate YAML from an approved plan.

        Uses the standard generation system prompt (not the plan prompt).
        The approved plan is injected into the user prompt.
        """
        user_prompt = build_generate_from_plan_user_prompt(
            original_request, approved_plan, mode,
        )
        return await self._llm.generate(system_prompt, user_prompt)

    def _parse_plan(
        self,
        content: str,
        known_entities: list[EntityEntry],
    ) -> PlanResponse:
        """Parse LLM plan response (JSON in code fences) into PlanResponse."""
        match = re.search(r"```(?:json)?\s*\n(.*?)```", content, re.DOTALL)
        if match:
            raw_json = match.group(1).strip()
        else:
            logger.warning(
                "No JSON code fence in plan response, attempting raw parse"
            )
            raw_json = content.strip()

        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            logger.error("Failed to parse plan JSON, returning empty plan")
            return PlanResponse()

        if not isinstance(data, dict):
            return PlanResponse()

        # Parse entity selections, enriching with known entity names
        known_map = {e.entity_id: e for e in known_entities}
        entities_selected: list[EntitySelection] = []
        for item in data.get("entities_selected", []):
            if not isinstance(item, dict):
                continue
            eid = item.get("entity_id", "")
            known = known_map.get(eid)
            entities_selected.append(
                EntitySelection(
                    entity_id=eid,
                    friendly_name=item.get(
                        "friendly_name",
                        known.name if known else eid,
                    ),
                    role=item.get("role", ""),
                    alternatives=item.get("alternatives") or [],
                )
            )

        return PlanResponse(
            entities_selected=entities_selected,
            trigger_outline=data.get("trigger_outline", ""),
            conditions_outline=data.get("conditions_outline"),
            actions_outline=data.get("actions_outline", ""),
            layout_outline=data.get("layout_outline"),
            assumptions=data.get("assumptions") or [],
            questions=data.get("questions") or [],
            suggestions=data.get("suggestions") or [],
        )
