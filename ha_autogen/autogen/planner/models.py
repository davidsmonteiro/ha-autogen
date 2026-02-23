"""Data models for Plan Mode."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EntitySelection(BaseModel):
    """An entity the LLM selected for the automation/dashboard."""

    entity_id: str
    friendly_name: str = ""
    role: str = ""  # "trigger", "condition", "action", "context", "display"
    alternatives: list[str] = Field(default_factory=list)


class PlanResponse(BaseModel):
    """Structured plan produced by the LLM (plan call output)."""

    entities_selected: list[EntitySelection] = Field(default_factory=list)
    trigger_outline: str | None = ""
    conditions_outline: str | None = None
    actions_outline: str | None = ""
    layout_outline: str | None = None  # dashboard mode
    assumptions: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class ApprovedPlan(BaseModel):
    """User-approved (or edited) plan sent back for generation or refinement."""

    plan_id: str = ""
    entities_selected: list[EntitySelection] = Field(default_factory=list)
    trigger_outline: str | None = ""
    conditions_outline: str | None = None
    actions_outline: str | None = ""
    layout_outline: str | None = None
    assumptions: list[str] = Field(default_factory=list)
    answered_questions: dict[str, str] = Field(default_factory=dict)
    user_notes: str = ""
