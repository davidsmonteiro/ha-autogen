"""Explore API — discover automation opportunities."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from autogen.context.engine import ContextEngine
from autogen.deps import get_context_engine, get_explorer_engine
from autogen.explorer.engine import ExplorerEngine
from autogen.explorer.models import AreaHighlight, AutomationSuggestion, ExplorationResult

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["explore"])


class ExploreRequest(BaseModel):
    focus_area: str | None = Field(
        None, description="Optional area name/ID to focus exploration on"
    )
    focus_domain: str | None = Field(
        None, description="Optional entity domain to focus on (e.g. 'light', 'sensor')"
    )


class ExploreResponse(BaseModel):
    summary: str = ""
    total_entities: int = 0
    total_areas: int = 0
    total_automations: int = 0
    coverage_percent: float = 0.0
    suggestions: list[AutomationSuggestion] = Field(default_factory=list)
    area_highlights: list[AreaHighlight] = Field(default_factory=list)
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


@router.post("/explore", response_model=ExploreResponse)
async def explore_automations(
    body: ExploreRequest,
    context_engine: ContextEngine = Depends(get_context_engine),
    explorer_engine: ExplorerEngine = Depends(get_explorer_engine),
) -> ExploreResponse:
    """Analyze the HA inventory and suggest automation opportunities."""
    try:
        result = await explorer_engine.explore(
            context_engine,
            focus_area=body.focus_area,
            focus_domain=body.focus_domain,
        )
    except Exception as e:
        logger.error("Exploration failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    return ExploreResponse(
        summary=result.summary,
        total_entities=result.total_entities,
        total_areas=result.total_areas,
        total_automations=result.total_automations,
        coverage_percent=result.coverage_percent,
        suggestions=result.suggestions,
        area_highlights=result.area_highlights,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
