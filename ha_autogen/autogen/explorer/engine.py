"""Explorer engine — inventory analysis + LLM-powered suggestions."""

from __future__ import annotations

import json
import logging
import re

from autogen.context.engine import ContextEngine
from autogen.explorer.analysis import analyze_inventory
from autogen.explorer.models import (
    AreaHighlight,
    AutomationSuggestion,
    ExplorationResult,
)
from autogen.llm.base import LLMBackend
from autogen.llm.prompts.explore import EXPLORE_SYSTEM_PROMPT, build_explore_user_prompt

logger = logging.getLogger(__name__)


class ExplorerEngine:
    """Combines deterministic inventory analysis with LLM suggestions."""

    def __init__(self, llm_backend: LLMBackend) -> None:
        self._llm = llm_backend

    async def explore(
        self,
        context_engine: ContextEngine,
        focus_area: str | None = None,
        focus_domain: str | None = None,
    ) -> ExplorationResult:
        """Run exploration: inventory analysis + LLM suggestions.

        Gracefully degrades to deterministic-only if the LLM fails.
        """
        entities = context_engine.get_active_entities()
        areas = context_engine.areas
        automations = context_engine.automations
        known_entity_ids = {e.entity_id for e in entities}

        # Phase 1: deterministic analysis
        analysis = analyze_inventory(entities, areas, automations)

        # Build area highlights
        area_highlights = [
            AreaHighlight(
                area_id=p.area_id,
                area_name=p.area_name,
                total_entities=p.total_entities,
                automated_entities=p.automated_count,
                coverage_percent=p.coverage_percent,
                potential_patterns=len(p.potential_patterns),
            )
            for p in analysis.area_profiles
            if p.potential_patterns
        ]

        # Phase 2: LLM suggestions
        suggestions: list[AutomationSuggestion] = []
        model = ""
        prompt_tokens = 0
        completion_tokens = 0

        try:
            user_prompt = build_explore_user_prompt(
                analysis, focus_area, focus_domain,
            )
            llm_response = await self._llm.generate(
                EXPLORE_SYSTEM_PROMPT, user_prompt,
            )
            model = llm_response.model
            prompt_tokens = llm_response.prompt_tokens
            completion_tokens = llm_response.completion_tokens

            suggestions = self._parse_suggestions(
                llm_response.content, known_entity_ids,
            )
            logger.info("Explorer LLM produced %d suggestions", len(suggestions))
        except Exception:
            logger.exception("Explorer LLM failed, returning deterministic analysis only")

        # If LLM didn't produce results, generate from patterns
        if not suggestions:
            suggestions = self._suggestions_from_patterns(analysis)

        summary = (
            f"Analyzed {analysis.total_entities} entities across "
            f"{analysis.total_areas} areas. "
            f"{analysis.coverage_percent:.0f}% automation coverage. "
            f"Found {len(suggestions)} suggestion(s) and "
            f"{len(analysis.matched_patterns)} pattern match(es)."
        )

        return ExplorationResult(
            summary=summary,
            total_entities=analysis.total_entities,
            total_areas=analysis.total_areas,
            total_automations=analysis.total_automations,
            coverage_percent=analysis.coverage_percent,
            suggestions=suggestions,
            area_highlights=area_highlights,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _parse_suggestions(
        self,
        content: str,
        known_entity_ids: set[str],
    ) -> list[AutomationSuggestion]:
        """Parse LLM response into AutomationSuggestion objects."""
        match = re.search(r"```(?:json)?\s*\n(.*?)```", content, re.DOTALL)
        if not match:
            logger.warning("No JSON code fence in explorer LLM response")
            return []

        try:
            raw = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            logger.warning("Failed to parse explorer JSON")
            return []

        if not isinstance(raw, list):
            raw = [raw]

        suggestions: list[AutomationSuggestion] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                # Validate entity IDs
                entities = item.get("entities_involved", [])
                valid_entities = [e for e in entities if e in known_entity_ids]

                suggestion = AutomationSuggestion(
                    title=item.get("title", "Untitled"),
                    description=item.get("description", ""),
                    entities_involved=valid_entities,
                    area=item.get("area", ""),
                    complexity=item.get("complexity", "simple"),
                    category=item.get("category", "convenience"),
                    example_yaml=item.get("example_yaml", ""),
                )
                suggestions.append(suggestion)
            except (ValueError, KeyError) as e:
                logger.warning("Skipping invalid suggestion: %s", e)

        return suggestions

    @staticmethod
    def _suggestions_from_patterns(
        analysis,
    ) -> list[AutomationSuggestion]:
        """Generate basic suggestions from deterministic pattern matches."""
        suggestions: list[AutomationSuggestion] = []

        for pattern in analysis.matched_patterns[:10]:
            trigger_str = ", ".join(pattern.trigger_entities[:2])
            target_str = ", ".join(pattern.target_entities[:2])

            suggestions.append(
                AutomationSuggestion(
                    title=f"{pattern.title} in {pattern.area_name}",
                    description=(
                        f"Use {pattern.trigger_domain} sensors to control "
                        f"{pattern.target_domain} devices in {pattern.area_name}."
                    ),
                    entities_involved=pattern.trigger_entities + pattern.target_entities,
                    area=pattern.area_name,
                    complexity="simple",
                    category=pattern.category,
                )
            )

        return suggestions
