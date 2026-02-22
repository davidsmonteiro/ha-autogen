"""Settings API — template CRUD endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

from autogen.deps import get_template_store
from autogen.llm.prompts.templates import PromptTemplate, TemplateStore

router = APIRouter(prefix="/api", tags=["settings"])


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
