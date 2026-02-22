"""POST /api/generate endpoint."""

from __future__ import annotations

import logging
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from typing import Literal

from autogen.context.engine import ContextEngine
from autogen.context.token_budget import (
    build_tiered_context,
    compute_budget,
    get_context_window,
)
from autogen.db.database import Database
from autogen.deps import get_context_engine, get_database, get_llm_backend, get_template_store
from autogen.llm.base import LLMBackend
from autogen.llm.prompts.automation import build_user_prompt
from autogen.llm.prompts.dashboard import (
    DASHBOARD_SYSTEM_PROMPT,
    build_dashboard_user_prompt,
)
from autogen.llm.prompts.system import SYSTEM_PROMPT
from autogen.llm.prompts.templates import TemplateStore, apply_templates
from autogen.validator import ValidationResult, validate, validate_dashboard

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["generate"])

MAX_RETRIES = 2


class GenerateRequest(BaseModel):
    """Request body for POST /api/generate."""

    request: str = Field(
        ..., min_length=5, max_length=2000, description="Natural language request"
    )
    mode: Literal["automation", "dashboard"] = Field(
        "automation", description="Generation mode: automation or dashboard"
    )


class GenerateResponse(BaseModel):
    """Response body for POST /api/generate."""

    generation_id: str = Field("", description="ID of the saved generation record")
    mode: str = Field("automation", description="Generation mode used")
    yaml_output: str = Field(..., description="Generated YAML")
    raw_response: str = Field("", description="Full LLM response (for debugging)")
    model: str = Field("", description="Model that generated the response")
    prompt_tokens: int = 0
    completion_tokens: int = 0
    validation: ValidationResult | None = None
    retries: int = 0


def extract_yaml_from_response(content: str) -> str:
    """Extract YAML from markdown code fences in the LLM response."""
    match = re.search(r"```(?:yaml)?\s*\n(.*?)```", content, re.DOTALL)
    if match:
        return match.group(1).strip()
    return content.strip()


async def _save_generation(
    db: Database, request_text: str, resp: GenerateResponse,
) -> str:
    """Persist a generation record and return its id."""
    gen_id = uuid.uuid4().hex
    validation_json = (
        resp.validation.model_dump_json() if resp.validation else None
    )
    status = "valid" if (resp.validation and resp.validation.valid) else "invalid"
    await db.conn.execute(
        """INSERT INTO generations
           (id, request, yaml_output, raw_response, model,
            prompt_tokens, completion_tokens, validation_json, retries,
            status, type, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))""",
        (
            gen_id,
            request_text,
            resp.yaml_output,
            resp.raw_response,
            resp.model,
            resp.prompt_tokens,
            resp.completion_tokens,
            validation_json,
            resp.retries,
            status,
            resp.mode,
        ),
    )
    await db.conn.commit()
    return gen_id


@router.post("/generate", response_model=GenerateResponse)
async def generate_automation(
    body: GenerateRequest,
    context_engine: ContextEngine = Depends(get_context_engine),
    llm_backend: LLMBackend = Depends(get_llm_backend),
    db: Database = Depends(get_database),
    template_store: TemplateStore = Depends(get_template_store),
) -> GenerateResponse:
    """Generate automation or dashboard YAML from a natural language request."""
    is_dashboard = body.mode == "dashboard"

    # Build context & prompts based on mode
    areas = context_engine.areas
    known_entity_ids = {e.entity_id for e in context_engine.get_active_entities()}

    if is_dashboard:
        # Dashboard mode: use all active entities, tiered by budget
        entities = context_engine.get_active_entities()
        base_system = DASHBOARD_SYSTEM_PROMPT
        user_prompt = build_dashboard_user_prompt(body.request)
        validate_fn = validate_dashboard
    else:
        # Automation mode: filter entities by relevance, then tier
        entities = context_engine.filter_entities_by_request(body.request)
        base_system = SYSTEM_PROMPT
        user_prompt = build_user_prompt(body.request)
        validate_fn = validate

    # Apply user-defined prompt templates
    system_templates = await template_store.get_active_templates("system")
    target_templates = await template_store.get_active_templates(
        "dashboard" if is_dashboard else "automation"
    )
    base_system = apply_templates(base_system, system_templates + target_templates)

    # Compute token budget and build tiered entity context
    model_ctx = get_context_window(llm_backend.model_name)
    budget = compute_budget(model_ctx, base_system, user_prompt)
    context_block = build_tiered_context(entities, areas, budget)
    full_system = f"{base_system}\n\n{context_block}"

    retries = 0
    last_error = ""

    for attempt in range(1 + MAX_RETRIES):
        # On retry, append the validation error to the user prompt
        current_user_prompt = user_prompt
        if last_error:
            current_user_prompt = (
                f"{user_prompt}\n\n"
                f"IMPORTANT: Your previous output had a YAML syntax error:\n"
                f"{last_error}\n\n"
                f"Please fix the error and regenerate valid YAML."
            )

        try:
            llm_response = await llm_backend.generate(full_system, current_user_prompt)
        except Exception as e:
            logger.error("LLM generation failed: %s", e, exc_info=True)
            raise HTTPException(status_code=502, detail=str(e))

        yaml_output = extract_yaml_from_response(llm_response.content)

        # Validate using mode-appropriate validator
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
                db, body.request, response,
            )
            return response

        # YAML syntax error — retry if we have attempts left
        syntax_errors = [i for i in validation.issues if i.check_name == "yaml_syntax"]
        if syntax_errors and attempt < MAX_RETRIES:
            last_error = syntax_errors[0].message
            retries += 1
            logger.warning(
                "YAML validation failed (attempt %d/%d): %s",
                attempt + 1,
                1 + MAX_RETRIES,
                last_error,
            )
            continue

        # Out of retries or non-syntax error — return what we have
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
            db, body.request, response,
        )
        return response

    # Should not reach here, but just in case
    raise HTTPException(status_code=500, detail="Unexpected error in generation loop")
