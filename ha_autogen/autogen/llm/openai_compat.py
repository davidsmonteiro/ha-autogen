"""OpenAI-compatible LLM backend implementation.

Works with OpenAI, Azure OpenAI, Groq, Together, local vLLM,
and any other provider exposing the /v1/chat/completions endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from autogen.llm.base import LLMBackend, LLMResponse

logger = logging.getLogger(__name__)


class OpenAICompatBackend(LLMBackend):
    """OpenAI-compatible /v1/chat/completions backend."""

    def __init__(self, base_url: str, model: str, api_key: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers: dict[str, str] = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=headers,
                timeout=httpx.Timeout(120.0, connect=10.0),
            )
        return self._client

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> LLMResponse:
        """Call /v1/chat/completions with system + user messages."""
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
            "OpenAI-compat request: model=%s, prompt_len=%d",
            self._model,
            len(user_prompt),
        )

        resp = await client.post("/v1/chat/completions", json=payload)
        if resp.status_code != 200:
            try:
                err_data = resp.json()
                err_msg = err_data.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            raise RuntimeError(f"API error ({resp.status_code}): {err_msg}")
        data = resp.json()

        choice = data["choices"][0]["message"]
        usage = data.get("usage", {})

        return LLMResponse(
            content=choice["content"],
            model=data.get("model", self._model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            raw=data,
        )

    async def health_check(self) -> bool:
        """Check if the API is reachable by listing models."""
        try:
            client = await self._get_client()
            resp = await client.get("/v1/models")
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
