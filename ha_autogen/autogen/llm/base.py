"""Abstract LLM backend interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class LLMResponse(BaseModel):
    """Structured response from any LLM backend."""

    content: str
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = Field(default_factory=dict)


class LLMBackend(ABC):
    """Abstract interface for LLM backends."""

    @property
    def model_name(self) -> str:
        """Return the configured model name (for token budget lookups)."""
        return getattr(self, "_model", "")

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResponse:
        """Generate a completion given system and user prompts."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the backend is reachable and ready."""
        ...
