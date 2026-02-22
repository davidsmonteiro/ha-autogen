"""Database record models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class GenerationStatus(str, Enum):
    draft = "draft"
    deployed = "deployed"
    rolled_back = "rolled_back"


class GenerationRecord(BaseModel):
    id: str
    request: str
    yaml_output: str
    raw_response: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    validation_json: str = "{}"
    retries: int = 0
    status: GenerationStatus = GenerationStatus.draft
    type: str = "automation"
    created_at: str = ""
    updated_at: str = ""


class DeploymentRecord(BaseModel):
    id: str
    generation_id: str
    automation_id: str | None = None
    yaml_deployed: str
    backup_path: str | None = None
    status: str = "deployed"
    type: str = "automation"
    deployed_at: str = ""
    rolled_back_at: str | None = None


class ReviewRecord(BaseModel):
    id: str
    scope: str = "all"
    target_id: str | None = None
    findings_json: str = "[]"
    summary: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    created_at: str = ""
