"""Review API endpoint with Quick Fix support."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from autogen.context.engine import ContextEngine
from autogen.db.database import Database
from autogen.deps import get_context_engine, get_database, get_reasoning_model, get_review_engine, get_template_store
from autogen.llm.prompts.templates import TemplateStore, apply_templates
from autogen.quickfix.classifier import (
    EnrichedFinding,
    FixClassification,
    classify_findings,
)
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


class EnrichedFindingResponse(BaseModel):
    """A finding enriched with Quick Fix classification."""

    finding_id: str = ""
    severity: str
    category: str
    automation_id: str = ""
    automation_alias: str = ""
    title: str
    description: str
    current_yaml: str | None = None
    suggested_yaml: str | None = None
    fix_type: str = "guided"
    fix_yaml: str | None = None
    requires_confirmation: bool = False
    fix_description: str = ""


class ReviewResponse(BaseModel):
    review_id: str = ""
    findings: list[EnrichedFindingResponse] = Field(default_factory=list)
    summary: str = ""
    quick_fix_count: int = 0
    guided_fix_count: int = 0
    automations_reviewed: int = 0
    dashboards_reviewed: int = 0
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0


class ApplyFixRequest(BaseModel):
    review_id: str
    finding_id: str
    confirmed: bool = False


class ApplyFixResponse(BaseModel):
    success: bool
    message: str = ""


class ApplyAllQuickFixesRequest(BaseModel):
    review_id: str
    confirmed_sensitive: list[str] = Field(
        default_factory=list,
        description="finding_ids the user explicitly confirmed for sensitive fixes",
    )


class ApplyAllQuickFixesResponse(BaseModel):
    success: bool
    total: int = 0
    applied: int = 0
    failed: int = 0
    message: str = ""


def _enrich_to_response(ef: EnrichedFinding) -> EnrichedFindingResponse:
    """Convert an EnrichedFinding to the API response model."""
    return EnrichedFindingResponse(
        finding_id=ef.finding.finding_id,
        severity=ef.finding.severity.value,
        category=ef.finding.category.value,
        automation_id=ef.finding.automation_id,
        automation_alias=ef.finding.automation_alias,
        title=ef.finding.title,
        description=ef.finding.description,
        current_yaml=ef.finding.current_yaml,
        suggested_yaml=ef.finding.suggested_yaml,
        fix_type=ef.fix_type.value,
        fix_yaml=ef.fix_yaml,
        requires_confirmation=ef.requires_confirmation,
        fix_description=ef.fix_description,
    )


@router.post("/review", response_model=ReviewResponse)
async def review_configurations(
    body: ReviewRequest,
    context_engine: ContextEngine = Depends(get_context_engine),
    review_engine: ReviewEngine = Depends(get_review_engine),
    db: Database = Depends(get_database),
    template_store: TemplateStore = Depends(get_template_store),
    reasoning_model: str | None = Depends(get_reasoning_model),
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
    automations_for_classify: list[dict] | None = None

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

        automations_for_classify = automations

        try:
            result = await review_engine.review_automations(
                automations, entity_summary=entity_summary,
                extra_instructions=extra_instructions,
                reasoning_model=reasoning_model,
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
                reasoning_model=reasoning_model,
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

        automations_for_classify = automations

        try:
            if automations and dashboard:
                result = await review_engine.review_full(
                    automations,
                    dashboard,
                    known_entity_ids=known_entity_ids,
                    areas=context_engine.areas,
                    entity_summary=entity_summary,
                    extra_instructions=extra_instructions,
                    reasoning_model=reasoning_model,
                )
            elif automations:
                result = await review_engine.review_automations(
                    automations, entity_summary=entity_summary,
                    extra_instructions=extra_instructions,
                    reasoning_model=reasoning_model,
                )
            else:
                result = await review_engine.review_dashboards(
                    dashboard,
                    known_entity_ids=known_entity_ids,
                    areas=context_engine.areas,
                    entity_summary=entity_summary,
                    extra_instructions=extra_instructions,
                    reasoning_model=reasoning_model,
                )
        except Exception as e:
            logger.error("Full review failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    assert result is not None

    # Classify findings for Quick Fix
    enriched = classify_findings(result.findings, automations_for_classify)
    enriched_responses = [_enrich_to_response(ef) for ef in enriched]
    quick_count = sum(1 for ef in enriched if ef.fix_type == FixClassification.QUICK and ef.fix_yaml)
    guided_count = sum(1 for ef in enriched if ef.fix_type == FixClassification.GUIDED)

    # Save to DB (store enriched findings)
    review_id = uuid.uuid4().hex
    findings_json = "[" + ",".join(f.model_dump_json() for f in result.findings) + "]"
    await db.conn.execute(
        """INSERT INTO reviews
           (id, scope, target_id, findings_json, summary, model,
            prompt_tokens, completion_tokens, reasoning_tokens, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            review_id,
            body.target,
            body.automation_id or "",
            findings_json,
            result.summary,
            result.model,
            result.prompt_tokens,
            result.completion_tokens,
            result.reasoning_tokens,
        ),
    )
    await db.conn.commit()

    return ReviewResponse(
        review_id=review_id,
        findings=enriched_responses,
        summary=result.summary,
        quick_fix_count=quick_count,
        guided_fix_count=guided_count,
        automations_reviewed=result.automations_reviewed,
        dashboards_reviewed=result.dashboards_reviewed,
        model=result.model,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        reasoning_tokens=result.reasoning_tokens,
    )


@router.post("/review/apply-fix", response_model=ApplyFixResponse)
async def apply_fix(
    body: ApplyFixRequest,
    context_engine: ContextEngine = Depends(get_context_engine),
    db: Database = Depends(get_database),
) -> ApplyFixResponse:
    """Apply a single Quick Fix to an automation."""
    # Look up the review findings
    async with db.conn.execute(
        "SELECT findings_json FROM reviews WHERE id = ?", (body.review_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Review not found")

    findings_data = json.loads(row["findings_json"])
    target_finding = None
    for fd in findings_data:
        if fd.get("finding_id") == body.finding_id:
            target_finding = fd
            break

    if not target_finding:
        raise HTTPException(status_code=404, detail="Finding not found")

    # Re-classify to get fix_yaml
    finding = ReviewFinding(**target_finding)
    automations = context_engine.automations
    from autogen.quickfix.classifier import classify
    auto_map = {a.get("id", ""): a for a in automations}
    enriched = classify(finding, auto_map.get(finding.automation_id))

    if enriched.fix_type != FixClassification.QUICK or not enriched.fix_yaml:
        raise HTTPException(
            status_code=400,
            detail="This finding is not a Quick Fix or has no fix YAML",
        )

    if enriched.requires_confirmation and not body.confirmed:
        raise HTTPException(
            status_code=400,
            detail="This fix involves sensitive domains and requires explicit confirmation",
        )

    # Record the fix application
    fix_id = uuid.uuid4().hex
    await db.conn.execute(
        """INSERT INTO fix_applications
           (id, review_id, finding_id, fix_type, fix_yaml, automation_id,
            status, applied_at)
           VALUES (?, ?, ?, ?, ?, ?, 'applied', datetime('now'))""",
        (
            fix_id,
            body.review_id,
            body.finding_id,
            "quick",
            enriched.fix_yaml,
            finding.automation_id,
        ),
    )
    await db.conn.commit()

    return ApplyFixResponse(
        success=True,
        message=f"Fix applied for '{finding.title}'",
    )


@router.post("/review/apply-all-quick-fixes", response_model=ApplyAllQuickFixesResponse)
async def apply_all_quick_fixes(
    body: ApplyAllQuickFixesRequest,
    context_engine: ContextEngine = Depends(get_context_engine),
    db: Database = Depends(get_database),
) -> ApplyAllQuickFixesResponse:
    """Batch apply all Quick Fixes from a review."""
    async with db.conn.execute(
        "SELECT findings_json FROM reviews WHERE id = ?", (body.review_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Review not found")

    findings_data = json.loads(row["findings_json"])
    findings = [ReviewFinding(**fd) for fd in findings_data]

    # Classify all
    automations = context_engine.automations
    enriched = classify_findings(findings, automations)

    confirmed_set = set(body.confirmed_sensitive)
    applied = 0
    failed = 0
    total = 0

    for ef in enriched:
        if ef.fix_type != FixClassification.QUICK or not ef.fix_yaml:
            continue
        total += 1

        if ef.requires_confirmation and ef.finding.finding_id not in confirmed_set:
            failed += 1
            continue

        try:
            fix_id = uuid.uuid4().hex
            await db.conn.execute(
                """INSERT INTO fix_applications
                   (id, review_id, finding_id, fix_type, fix_yaml, automation_id,
                    status, applied_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'applied', datetime('now'))""",
                (
                    fix_id,
                    body.review_id,
                    ef.finding.finding_id,
                    "quick",
                    ef.fix_yaml,
                    ef.finding.automation_id,
                ),
            )
            applied += 1
        except Exception as e:
            logger.warning("Failed to apply fix: %s", e)
            failed += 1

    await db.conn.commit()

    return ApplyAllQuickFixesResponse(
        success=failed == 0,
        total=total,
        applied=applied,
        failed=failed,
        message=f"Applied {applied}/{total} quick fixes",
    )
