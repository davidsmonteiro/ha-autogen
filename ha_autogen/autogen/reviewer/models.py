"""Data models for the automation review system."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class FindingSeverity(str, Enum):
    critical = "critical"
    warning = "warning"
    suggestion = "suggestion"
    info = "info"


class FindingCategory(str, Enum):
    # Automation categories
    trigger_efficiency = "trigger_efficiency"
    missing_guards = "missing_guards"
    deprecated_patterns = "deprecated_patterns"
    redundancy = "redundancy"
    security = "security"
    error_resilience = "error_resilience"
    # Dashboard categories
    unused_entities = "unused_entities"
    inconsistent_cards = "inconsistent_cards"
    missing_area_coverage = "missing_area_coverage"
    card_type_recommendation = "card_type_recommendation"
    layout_optimization = "layout_optimization"


class ReviewFinding(BaseModel):
    """A single finding from the review process."""

    severity: FindingSeverity
    category: FindingCategory
    automation_id: str = ""
    automation_alias: str = ""
    title: str
    description: str
    current_yaml: str | None = None
    suggested_yaml: str | None = None


class ReviewResult(BaseModel):
    """Complete result of a review run."""

    findings: list[ReviewFinding] = Field(default_factory=list)
    summary: str = ""
    automations_reviewed: int = 0
    dashboards_reviewed: int = 0
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
