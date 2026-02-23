"""Ollama LLM backend implementation."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from autogen.llm.base import LLMBackend, LLMResponse

logger = logging.getLogger(__name__)


class OllamaBackend(LLMBackend):
    """Ollama /api/chat backend."""

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        reasoning_model: str | None = None,
    ) -> LLMResponse:
        """Call Ollama /api/chat with system + user messages."""
        client = await self._get_client()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }

        logger.debug(
            "Ollama request: model=%s, prompt_len=%d",
            self._model,
            len(user_prompt),
        )

        resp = await client.post("/api/chat", json=payload)
        resp.raise_for_status()

        if not resp.content or not resp.content.strip():
            raise RuntimeError(
                f"Ollama returned an empty response (status {resp.status_code}). "
                f"Check that llm_api_url ({self._base_url}) points to a running "
                "Ollama instance. If you are using OpenRouter, OpenAI, or another "
                "cloud API, change llm_backend to 'openai_compat' in Settings."
            )

        try:
            data = resp.json()
        except Exception:
            preview = resp.text[:200] if resp.text else "(empty)"
            raise RuntimeError(
                f"Ollama returned non-JSON response (status {resp.status_code}): "
                f"{preview}... — If you are using OpenRouter or another OpenAI-"
                "compatible API, change llm_backend to 'openai_compat' in Settings."
            )

        if "message" not in data:
            raise RuntimeError(
                f"Unexpected Ollama response format (missing 'message' key). "
                f"Got keys: {list(data.keys())}. If using a non-Ollama API, "
                "change llm_backend to 'openai_compat' in Settings."
            )

        return LLMResponse(
            content=data["message"]["content"],
            model=data.get("model", self._model),
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            raw=data,
        )

    async def health_check(self) -> bool:
        """Check if Ollama is reachable by hitting the root endpoint."""
        try:
            client = await self._get_client()
            resp = await client.get("/")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
