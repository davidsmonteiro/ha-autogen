"""Plan Mode API endpoints."""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from autogen.api.generate import GenerateResponse, _save_generation, extract_yaml_from_response
from autogen.context.engine import ContextEngine
from autogen.context.token_budget import build_tiered_context, compute_budget, get_context_window
from autogen.db.database import Database
from autogen.deps import (
    get_context_engine,
    get_database,
    get_llm_backend,
    get_planner_engine,
    get_template_store,
)
from autogen.llm.base import LLMBackend
from autogen.llm.prompts.dashboard import DASHBOARD_SYSTEM_PROMPT
from autogen.llm.prompts.system import SYSTEM_PROMPT
from autogen.llm.prompts.templates import TemplateStore, apply_templates
from autogen.planner.engine import PlannerEngine
from autogen.planner.models import ApprovedPlan, PlanResponse
from autogen.validator import ValidationResult, validate, validate_dashboard

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["plan"])

MAX_RETRIES = 2


class PlanRequest(BaseModel):
    """Request body for POST /api/plan."""

    request: str = Field(..., min_length=5, max_length=2000)
    mode: Literal["automation", "dashboard"] = "automation"
    previous_plan: ApprovedPlan | None = Field(
        None, description="Previous plan for refinement (null for first call)"
    )
    refinement_notes: str | None = Field(
        None, description="Free-text refinement instructions (for re-plan calls)"
    )
    plan_id: str | None = Field(
        None, description="Existing plan_id to update on refinement"
    )


class PlanResult(BaseModel):
    """Response body for POST /api/plan."""

    plan_id: str = ""
    plan: PlanResponse
    original_request: str = ""
    mode: str = "automation"
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    context_block: str = ""
    iteration: int = 1


class GenerateFromPlanRequest(BaseModel):
    """Request body for POST /api/plan/generate."""

    plan_id: str = ""
    original_request: str = Field(..., min_length=5, max_length=2000)
    mode: Literal["automation", "dashboard"] = "automation"
    approved_plan: ApprovedPlan
    context_block: str = ""


def _build_context(
    body_request: str,
    mode: str,
    context_engine: ContextEngine,
    llm_backend: LLMBackend,
    base_system: str,
) -> tuple[str, str]:
    """Build the tiered entity context block. Returns (context_block, base_system)."""
    areas = context_engine.areas
    if mode == "dashboard":
        entities = context_engine.get_active_entities()
    else:
        entities = context_engine.filter_entities_by_request(body_request)

    model_ctx = get_context_window(llm_backend.model_name)
    budget = compute_budget(model_ctx, base_system, body_request)
    context_block = build_tiered_context(entities, areas, budget)
    return context_block, base_system


@router.post("/plan", response_model=PlanResult)
async def create_plan(
    body: PlanRequest,
    context_engine: ContextEngine = Depends(get_context_engine),
    llm_backend: LLMBackend = Depends(get_llm_backend),
    planner_engine: PlannerEngine = Depends(get_planner_engine),
    template_store: TemplateStore = Depends(get_template_store),
    db: Database = Depends(get_database),
) -> PlanResult:
    """Create or refine a structured plan from a natural language request."""
    is_dashboard = body.mode == "dashboard"
    is_refinement = body.previous_plan is not None and body.refinement_notes

    # Build system prompt with templates
    base_system = DASHBOARD_SYSTEM_PROMPT if is_dashboard else SYSTEM_PROMPT
    system_templates = await template_store.get_active_templates("system")
    target_templates = await template_store.get_active_templates(
        "dashboard" if is_dashboard else "automation"
    )
    base_system = apply_templates(base_system, system_templates + target_templates)

    # Build entity context
    context_block, base_system = _build_context(
        body.request, body.mode, context_engine, llm_backend, base_system,
    )

    known_entities = context_engine.get_active_entities()

    try:
        if is_refinement:
            plan, llm_response = await planner_engine.refine_plan(
                original_request=body.request,
                mode=body.mode,
                context_block=context_block,
                previous_plan=body.previous_plan,
                refinement_notes=body.refinement_notes,
                known_entities=known_entities,
            )
        else:
            plan, llm_response = await planner_engine.create_plan(
                request=body.request,
                mode=body.mode,
                context_block=context_block,
                known_entities=known_entities,
            )
    except Exception as e:
        logger.error("Plan generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail=str(e))

    # Determine plan_id and iteration
    if is_refinement and body.plan_id:
        plan_id = body.plan_id
        # Update existing plan row
        await db.conn.execute(
            """UPDATE plans SET plan_json = ?, model = ?, prompt_tokens = ?,
               completion_tokens = ?, iteration = iteration + 1,
               updated_at = datetime('now')
               WHERE id = ?""",
            (
                plan.model_dump_json(),
                llm_response.model,
                llm_response.prompt_tokens,
                llm_response.completion_tokens,
                plan_id,
            ),
        )
        await db.conn.commit()
        # Get current iteration
        async with db.conn.execute(
            "SELECT iteration FROM plans WHERE id = ?", (plan_id,)
        ) as cursor:
            row = await cursor.fetchone()
            iteration = row["iteration"] if row else 1
    else:
        plan_id = uuid.uuid4().hex
        iteration = 1
        await db.conn.execute(
            """INSERT INTO plans
               (id, request, mode, plan_json, context_block, model,
                prompt_tokens, completion_tokens, status, iteration,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', 1,
                       datetime('now'), datetime('now'))""",
            (
                plan_id,
                body.request,
                body.mode,
                plan.model_dump_json(),
                context_block,
                llm_response.model,
                llm_response.prompt_tokens,
                llm_response.completion_tokens,
            ),
        )
        await db.conn.commit()

    return PlanResult(
        plan_id=plan_id,
        plan=plan,
        original_request=body.request,
        mode=body.mode,
        model=llm_response.model,
        prompt_tokens=llm_response.prompt_tokens,
        completion_tokens=llm_response.completion_tokens,
        context_block=context_block,
        iteration=iteration,
    )


@router.post("/plan/generate", response_model=GenerateResponse)
async def generate_from_plan(
    body: GenerateFromPlanRequest,
    context_engine: ContextEngine = Depends(get_context_engine),
    llm_backend: LLMBackend = Depends(get_llm_backend),
    planner_engine: PlannerEngine = Depends(get_planner_engine),
    template_store: TemplateStore = Depends(get_template_store),
    db: Database = Depends(get_database),
) -> GenerateResponse:
    """Generate YAML from an approved plan."""
    is_dashboard = body.mode == "dashboard"
    known_entity_ids = {e.entity_id for e in context_engine.get_active_entities()}

    # Build system prompt
    base_system = DASHBOARD_SYSTEM_PROMPT if is_dashboard else SYSTEM_PROMPT
    validate_fn = validate_dashboard if is_dashboard else validate

    system_templates = await template_store.get_active_templates("system")
    target_templates = await template_store.get_active_templates(
        "dashboard" if is_dashboard else "automation"
    )
    base_system = apply_templates(base_system, system_templates + target_templates)

    # Use context block from plan step or rebuild
    context_block = body.context_block
    if not context_block:
        context_block, base_system = _build_context(
            body.original_request, body.mode, context_engine, llm_backend, base_system,
        )

    full_system = f"{base_system}\n\n{context_block}"

    retries = 0
    last_error = ""

    for attempt in range(1 + MAX_RETRIES):
        try:
            llm_response = await planner_engine.generate_from_plan(
                approved_plan=body.approved_plan,
                original_request=body.original_request,
                mode=body.mode,
                system_prompt=full_system,
            )
        except Exception as e:
            logger.error("Plan-based generation failed: %s", e, exc_info=True)
            raise HTTPException(status_code=502, detail=str(e))

        yaml_output = extract_yaml_from_response(llm_response.content)
        validation = validate_fn(yaml_output, known_entity_ids)

        if validation.valid:
            response = GenerateResponse(
                mode=body.mode,
                yaml_output=yaml_output,
                raw_response=llm_response.content,
                model=llm_response.model,
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
                validation=validation,
                retries=retries,
            )
            response.generation_id = await _save_generation(
                db, body.original_request, response,
            )

            # Link plan to generation
            if body.plan_id:
                await db.conn.execute(
                    "UPDATE plans SET status = 'generated', generation_id = ? WHERE id = ?",
                    (response.generation_id, body.plan_id),
                )
                await db.conn.commit()

            return response

        # Retry on YAML syntax errors
        syntax_errors = [i for i in validation.issues if i.check_name == "yaml_syntax"]
        if syntax_errors and attempt < MAX_RETRIES:
            last_error = syntax_errors[0].message
            retries += 1
            logger.warning(
                "Plan-based YAML validation failed (attempt %d/%d): %s",
                attempt + 1, 1 + MAX_RETRIES, last_error,
            )
            continue

        # Out of retries — return what we have
        response = GenerateResponse(
            mode=body.mode,
            yaml_output=yaml_output,
            raw_response=llm_response.content,
            model=llm_response.model,
            prompt_tokens=llm_response.prompt_tokens,
            completion_tokens=llm_response.completion_tokens,
            validation=validation,
            retries=retries,
        )
        response.generation_id = await _save_generation(
            db, body.original_request, response,
        )
        return response

    raise HTTPException(status_code=500, detail="Unexpected error in plan generation loop")
