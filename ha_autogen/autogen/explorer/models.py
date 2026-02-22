"""Data models for the automation explorer."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AutomationSuggestion(BaseModel):
    """A single automation suggestion from the explorer."""

    title: str
    description: str
    entities_involved: list[str] = Field(default_factory=list)
    area: str = ""
    complexity: str = "simple"  # simple, moderate, advanced
    category: str = "convenience"  # lighting, security, comfort, energy, convenience, notification
    example_yaml: str = ""


class AreaHighlight(BaseModel):
    """Summary of automation potential for an area."""

    area_id: str
    area_name: str
    total_entities: int = 0
    automated_entities: int = 0
    coverage_percent: float = 0.0
    potential_patterns: int = 0


class ExplorationResult(BaseModel):
    """Full result from an exploration run."""

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
