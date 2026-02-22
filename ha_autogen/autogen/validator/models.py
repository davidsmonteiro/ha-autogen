"""Validation data models."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ValidationSeverity(str, Enum):
    """Severity level for validation issues."""

    error = "error"
    warning = "warning"
    info = "info"


class ValidationIssue(BaseModel):
    """A single validation finding."""

    severity: ValidationSeverity
    check_name: str
    message: str
    line: int | None = None
    suggestion: str | None = None


class ValidationResult(BaseModel):
    """Aggregated result from the validation pipeline."""

    valid: bool = True
    issues: list[ValidationIssue] = Field(default_factory=list)
    yaml_parsed: dict[str, Any] | None = None
