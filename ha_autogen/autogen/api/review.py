"""Review API endpoint."""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from autogen.context.engine import ContextEngine
from autogen.db.database import Database
from autogen.deps import get_context_engine, get_database, get_review_engine, get_template_store
from autogen.llm.prompts.templates import TemplateStore, apply_templates
from autogen.reviewer.engine import ReviewEngine
from autogen.reviewer.models import ReviewFinding, ReviewResult
from autogen.reviewer.scoping import (
    filter_automations_by_area,
    filter_dashboard_view_by_path,
    filter_dashboard_views_by_area,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["review"])


class ReviewRequest(BaseModel):
    scope: str = Field(
        "all",
        description="Review scope: 'all', 'single', or 'area'",
    )
    automation_id: str | None = Field(
        None, description="Automation ID to review (required when scope='single')"
    )
    target: Literal["automations", "dashboards", "all"] = Field(
        "automations", description="What to review: automations, dashboards, or all"
    )
    area_id: str | None = Field(
        None, description="Area ID to scope review (required when scope='area')"
    )
    dashboard_view_path: str | None = Field(
        None, description="Dashboard view path to review (for single-view review)"
    )


class ReviewResponse(BaseModel):
    review_id: str = ""
    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str = ""
    automations_reviewed: int = 0
    dashboards_reviewed: int = 0
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0


@router.post("/review", response_model=ReviewResponse)
async def review_configurations(
    body: ReviewRequest,
    context_engine: ContextEngine = Depends(get_context_engine),
    review_engine: ReviewEngine = Depends(get_review_engine),
    db: Database = Depends(get_database),
    template_store: TemplateStore = Depends(get_template_store),
) -> ReviewResponse:
    """Review existing automations and/or dashboards for issues."""
    # Build entity summary for context
    active_entities = context_engine.get_active_entities()
    entity_summary = "\n".join(
        f"- {e.entity_id} ({e.name or ''})" for e in active_entities[:200]
    )
    known_entity_ids = {e.entity_id for e in active_entities}

    # Load review templates for extra instructions
    review_templates = await template_store.get_active_templates("review")
    extra_instructions = apply_templates("", review_templates).strip() if review_templates else None

    # Scoping helpers
    entity_area_map = context_engine.get_entity_area_map()
    area_names = {a.area_id: a.name for a in context_engine.areas}

    result: ReviewResult | None = None

    if body.target == "automations":
        automations = context_engine.automations
        if not automations:
            raise HTTPException(
                status_code=404,
                detail="No automations found. Load automations first.",
            )

        if body.scope == "single":
            if not body.automation_id:
                raise HTTPException(
                    status_code=400,
                    detail="automation_id is required when scope='single'",
                )
            automations = [
                a for a in automations if a.get("id") == body.automation_id
            ]
            if not automations:
                raise HTTPException(
                    status_code=404,
                    detail=f"Automation '{body.automation_id}' not found",
                )
        elif body.scope == "area":
            if not body.area_id:
                raise HTTPException(
                    status_code=400,
                    detail="area_id is required when scope='area'",
                )
            automations = filter_automations_by_area(
                automations, body.area_id, entity_area_map,
            )
            if not automations:
                raise HTTPException(
                    status_code=404,
                    detail=f"No automations found for area '{area_names.get(body.area_id, body.area_id)}'",
                )

        try:
            result = await review_engine.review_automations(
                automations, entity_summary=entity_summary,
                extra_instructions=extra_instructions,
            )
        except Exception as e:
            logger.error("Automation review failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    elif body.target == "dashboards":
        dashboard = context_engine.dashboards
        if not dashboard:
            raise HTTPException(
                status_code=404,
                detail="No dashboard config found. Load dashboards first.",
            )

        # Apply scoping
        if body.scope == "area" and body.area_id:
            dashboard = filter_dashboard_views_by_area(
                dashboard, body.area_id, entity_area_map, area_names,
            )
            if not dashboard.get("views"):
                raise HTTPException(
                    status_code=404,
                    detail=f"No dashboard views found for area '{area_names.get(body.area_id, body.area_id)}'",
                )
        elif body.scope == "single" and body.dashboard_view_path:
            dashboard = filter_dashboard_view_by_path(
                dashboard, body.dashboard_view_path,
            )
            if not dashboard.get("views"):
                raise HTTPException(
                    status_code=404,
                    detail=f"Dashboard view '{body.dashboard_view_path}' not found",
                )

        try:
            result = await review_engine.review_dashboards(
                dashboard,
                known_entity_ids=known_entity_ids,
                areas=context_engine.areas,
                entity_summary=entity_summary,
                extra_instructions=extra_instructions,
            )
        except Exception as e:
            logger.error("Dashboard review failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    else:  # target == "all"
        automations = context_engine.automations
        dashboard = context_engine.dashboards

        # Apply area scoping to both if requested
        if body.scope == "area" and body.area_id:
            automations = filter_automations_by_area(
                automations, body.area_id, entity_area_map,
            )
            if dashboard:
                dashboard = filter_dashboard_views_by_area(
                    dashboard, body.area_id, entity_area_map, area_names,
                )

        if not automations and not dashboard:
            raise HTTPException(
                status_code=404,
                detail="No automations or dashboard config found.",
            )

        try:
            if automations and dashboard:
                result = await review_engine.review_full(
                    automations,
                    dashboard,
                    known_entity_ids=known_entity_ids,
                    areas=context_engine.areas,
                    entity_summary=entity_summary,
                    extra_instructions=extra_instructions,
                )
            elif automations:
                result = await review_engine.review_automations(
                    automations, entity_summary=entity_summary,
                    extra_instructions=extra_instructions,
                )
            else:
                result = await review_engine.review_dashboards(
                    dashboard,
                    known_entity_ids=known_entity_ids,
                    areas=context_engine.areas,
                    entity_summary=entity_summary,
                    extra_instructions=extra_instructions,
                )
        except Exception as e:
            logger.error("Full review failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    assert result is not None

    # Save to DB
    review_id = uuid.uuid4().hex
    findings_json = "[" + ",".join(f.model_dump_json() for f in result.findings) + "]"
    await db.conn.execute(
        """INSERT INTO reviews
           (id, scope, target_id, findings_json, summary, model,
            prompt_tokens, completion_tokens, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            review_id,
            body.target,
            body.automation_id or "",
            findings_json,
            result.summary,
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
        ),
    )
    await db.conn.commit()

    return ReviewResponse(
        review_id=review_id,
        findings=result.findings,
        summary=result.summary,
        automations_reviewed=result.automations_reviewed,
        dashboards_reviewed=result.dashboards_reviewed,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
    )
