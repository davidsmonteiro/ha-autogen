"""Context API — lightweight read-only endpoints for frontend dropdowns."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from autogen.context.engine import ContextEngine
from autogen.deps import get_context_engine

router = APIRouter(prefix="/api/context", tags=["context"])


class AreaItem(BaseModel):
    area_id: str
    name: str


class AutomationItem(BaseModel):
    id: str
    alias: str


class ViewItem(BaseModel):
    path: str
    title: str


@router.get("/areas", response_model=list[AreaItem])
async def list_areas(
    context_engine: ContextEngine = Depends(get_context_engine),
) -> list[AreaItem]:
    """Return all known areas for dropdown selectors."""
    return [
        AreaItem(area_id=a.area_id, name=a.name)
        for a in context_engine.areas
    ]


@router.get("/automations", response_model=list[AutomationItem])
async def list_automations(
    context_engine: ContextEngine = Depends(get_context_engine),
) -> list[AutomationItem]:
    """Return all known automations (id + alias) for selectors."""
    return [
        AutomationItem(
            id=a.get("id", ""),
            alias=a.get("alias", a.get("id", "Untitled")),
        )
        for a in context_engine.automations
        if a.get("id")
    ]


@router.get("/views", response_model=list[ViewItem])
async def list_views(
    context_engine: ContextEngine = Depends(get_context_engine),
) -> list[ViewItem]:
    """Return all dashboard view paths and titles for selectors."""
    dashboard = context_engine.dashboards
    views = dashboard.get("views", []) if isinstance(dashboard, dict) else []
    return [
        ViewItem(
            path=v.get("path", f"view-{i}"),
            title=v.get("title", f"View {i + 1}"),
        )
        for i, v in enumerate(views)
    ]
