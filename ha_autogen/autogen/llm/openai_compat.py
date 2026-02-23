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
        reasoning_model: str | None = None,
    ) -> LLMResponse:
        """Call /v1/chat/completions with system + user messages."""
        client = await self._get_client()
        effective_model = reasoning_model or self._model

        payload: dict[str, Any] = {
            "model": effective_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
        }

        # Enable reasoning when using a reasoning model via OpenRouter
        if reasoning_model:
            payload["reasoning"] = {"effort": "high"}

        logger.debug(
            "OpenAI-compat request: model=%s, prompt_len=%d, reasoning=%s",
            effective_model,
            len(user_prompt),
            bool(reasoning_model),
        )

        resp = await client.post("/v1/chat/completions", json=payload)
        if resp.status_code != 200:
            try:
                err_data = resp.json()
                err_msg = err_data.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            raise RuntimeError(f"API error ({resp.status_code}): {err_msg}")

        if not resp.content or not resp.content.strip():
            raise RuntimeError(
                f"API returned an empty response (status {resp.status_code}). "
                f"Check that llm_api_url ({self._base_url}) is correct."
            )

        try:
            data = resp.json()
        except Exception:
            preview = resp.text[:200] if resp.text else "(empty)"
            raise RuntimeError(
                f"API returned non-JSON response: {preview}... — "
                f"Check that llm_api_url ({self._base_url}) is correct."
            )

        if "choices" not in data or not data["choices"]:
            raise RuntimeError(
                f"Unexpected API response format (missing 'choices'). "
                f"Got keys: {list(data.keys())}."
            )

        choice = data["choices"][0]["message"]
        usage = data.get("usage", {})

        # Extract reasoning tokens from usage details
        completion_details = usage.get("completion_tokens_details") or {}
        reasoning_tokens = completion_details.get("reasoning_tokens", 0)

        # Extract thinking content (OpenRouter returns it in message.reasoning)
        thinking = choice.get("reasoning")

        return LLMResponse(
            content=choice.get("content") or "",
            model=data.get("model", self._model),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            reasoning_tokens=reasoning_tokens,
            thinking=thinking if thinking else None,
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
