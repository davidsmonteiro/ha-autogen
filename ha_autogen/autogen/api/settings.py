"""Settings API — LLM config + template CRUD endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

import autogen.deps as deps
from autogen.deps import get_llm_backend, get_template_store
from autogen.llm.base import LLMBackend
from autogen.llm.ollama import OllamaBackend
from autogen.llm.openai_compat import OpenAICompatBackend
from autogen.llm.prompts.templates import PromptTemplate, TemplateStore
from autogen.planner.engine import PlannerEngine
from autogen.reviewer.engine import ReviewEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["settings"])


# -- LLM settings --

VALID_REASONING_MODELS = {
    "",
    "anthropic/claude-sonnet-4-6",
    "openai/gpt-5.2",
}


class LLMSettingsResponse(BaseModel):
    llm_backend: str = ""
    llm_api_url: str = ""
    llm_model: str = ""
    has_api_key: bool = False
    reasoning_model: str | None = None


class LLMSettingsUpdateRequest(BaseModel):
    llm_backend: Literal["ollama", "openai_compat"] | None = None
    llm_api_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    reasoning_model: str | None = None


@router.get("/settings/llm", response_model=LLMSettingsResponse)
async def get_llm_settings(
    llm: LLMBackend = Depends(get_llm_backend),
) -> LLMSettingsResponse:
    """Return current LLM backend configuration (key is redacted)."""
    if isinstance(llm, OpenAICompatBackend):
        return LLMSettingsResponse(
            llm_backend="openai_compat",
            llm_api_url=llm._base_url,
            llm_model=llm._model,
            has_api_key=bool(llm._api_key),
            reasoning_model=deps._reasoning_model,
        )
    elif isinstance(llm, OllamaBackend):
        return LLMSettingsResponse(
            llm_backend="ollama",
            llm_api_url=llm._base_url,
            llm_model=llm._model,
            has_api_key=False,
            reasoning_model=deps._reasoning_model,
        )
    return LLMSettingsResponse()


@router.put("/settings/llm", response_model=LLMSettingsResponse)
async def update_llm_settings(
    body: LLMSettingsUpdateRequest,
) -> LLMSettingsResponse:
    """Update LLM backend settings at runtime (no restart needed).

    Only provided fields are updated; omitted fields keep their current value.
    """
    current = deps._llm_backend
    if current is None:
        raise HTTPException(status_code=500, detail="LLM backend not initialised")

    # Read current values as defaults
    cur_backend = "openai_compat" if isinstance(current, OpenAICompatBackend) else "ollama"
    cur_url = current._base_url
    cur_model = current._model
    cur_key = getattr(current, "_api_key", "")

    new_backend = body.llm_backend or cur_backend
    new_url = body.llm_api_url.strip() if body.llm_api_url is not None else cur_url
    new_model = body.llm_model.strip() if body.llm_model is not None else cur_model
    new_key = body.llm_api_key if body.llm_api_key is not None else cur_key

    if not new_url:
        raise HTTPException(status_code=400, detail="API URL cannot be empty")
    if not new_model:
        raise HTTPException(status_code=400, detail="Model name cannot be empty")

    # Close old backend
    if hasattr(current, "close"):
        await current.close()

    # Create new backend
    if new_backend == "openai_compat":
        new_llm: LLMBackend = OpenAICompatBackend(
            base_url=new_url,
            model=new_model,
            api_key=new_key,
        )
    else:
        new_llm = OllamaBackend(
            base_url=new_url,
            model=new_model,
        )

    # Swap globally
    deps._llm_backend = new_llm

    # Reinit engines that depend on the LLM backend
    deps._review_engine = ReviewEngine(new_llm)
    deps._planner_engine = PlannerEngine(new_llm)
    if deps._explorer_engine is not None:
        from autogen.explorer.engine import ExplorerEngine
        deps._explorer_engine = ExplorerEngine(new_llm)

    # Handle reasoning model update
    if body.reasoning_model is not None:
        rm = body.reasoning_model.strip()
        if rm and rm not in VALID_REASONING_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid reasoning_model: must be one of {sorted(VALID_REASONING_MODELS - {''})} or empty to disable",
            )
        deps._reasoning_model = rm if rm else None

    logger.info(
        "LLM settings updated: backend=%s, model=%s, url=%s, reasoning=%s",
        new_backend, new_model, new_url, deps._reasoning_model,
    )

    return LLMSettingsResponse(
        llm_backend=new_backend,
        llm_api_url=new_url,
        llm_model=new_model,
        has_api_key=bool(new_key),
        reasoning_model=deps._reasoning_model,
    )


@router.get("/health/llm")
async def health_check_llm(
    llm: LLMBackend = Depends(get_llm_backend),
) -> dict:
    """Check if the LLM backend is reachable."""
    model = getattr(llm, "_model", "")
    try:
        healthy = await llm.health_check()
    except Exception as e:
        return {"healthy": False, "model": model, "error": str(e)}
    return {"healthy": healthy, "model": model, "error": "" if healthy else "unreachable"}


# -- Prompt templates --

class TemplateCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    content: str = Field(..., min_length=1)
    target: Literal["system", "automation", "dashboard", "review"] = "system"
    position: Literal["prepend", "append"] = "append"
    enabled: bool = True


class TemplateUpdateRequest(BaseModel):
    name: str | None = None
    content: str | None = None
    target: Literal["system", "automation", "dashboard", "review"] | None = None
    position: Literal["prepend", "append"] | None = None
    enabled: bool | None = None


@router.get("/templates", response_model=list[PromptTemplate])
async def list_templates(
    store: TemplateStore = Depends(get_template_store),
) -> list[PromptTemplate]:
    """List all prompt templates."""
    return await store.list_templates()


@router.post("/templates", response_model=PromptTemplate)
async def create_template(
    body: TemplateCreateRequest,
    store: TemplateStore = Depends(get_template_store),
) -> PromptTemplate:
    """Create a new prompt template."""
    template = PromptTemplate(
        name=body.name,
        content=body.content,
        target=body.target,
        position=body.position,
        enabled=body.enabled,
    )
    return await store.create_template(template)


@router.get("/templates/{template_id}", response_model=PromptTemplate)
async def get_template(
    template_id: str,
    store: TemplateStore = Depends(get_template_store),
) -> PromptTemplate:
    """Get a single template by ID."""
    template = await store.get_template(template_id)
    if not template:
        raise HTTPException(status_code=404, detail="Template not found")
    return template


@router.put("/templates/{template_id}", response_model=PromptTemplate)
async def update_template(
    template_id: str,
    body: TemplateUpdateRequest,
    store: TemplateStore = Depends(get_template_store),
) -> PromptTemplate:
    """Update an existing template."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = await store.update_template(template_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Template not found")
    return result


@router.delete("/templates/{template_id}")
async def delete_template(
    template_id: str,
    store: TemplateStore = Depends(get_template_store),
) -> dict[str, str]:
    """Delete a template."""
    deleted = await store.delete_template(template_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"status": "deleted"}
