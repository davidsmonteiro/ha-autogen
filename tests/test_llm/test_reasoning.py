"""Tests for reasoning model support in LLM backends."""

import json

import pytest

from autogen.llm.ollama import OllamaBackend
from autogen.llm.openai_compat import OpenAICompatBackend


# -- OpenAI-compat reasoning tests --


@pytest.mark.asyncio
async def test_openai_compat_reasoning_model_overrides_model(httpx_mock) -> None:
    """When reasoning_model is set, the payload model should be the reasoning model."""
    httpx_mock.add_response(
        url="https://openrouter.ai/v1/chat/completions",
        json={
            "model": "anthropic/claude-sonnet-4-6",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )

    backend = OpenAICompatBackend(
        base_url="https://openrouter.ai",
        model="meta-llama/llama-3-8b",
        api_key="sk-test",
    )
    await backend.generate(
        "system", "user", reasoning_model="anthropic/claude-sonnet-4-6",
    )
    await backend.close()

    request = httpx_mock.get_request()
    body = json.loads(request.content)
    assert body["model"] == "anthropic/claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_openai_compat_reasoning_adds_reasoning_param(httpx_mock) -> None:
    """When reasoning_model is set, reasoning: {effort: 'high'} should be in the payload."""
    httpx_mock.add_response(
        url="https://openrouter.ai/v1/chat/completions",
        json={
            "model": "openai/gpt-5.2",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )

    backend = OpenAICompatBackend(
        base_url="https://openrouter.ai",
        model="meta-llama/llama-3-8b",
        api_key="sk-test",
    )
    await backend.generate(
        "system", "user", reasoning_model="openai/gpt-5.2",
    )
    await backend.close()

    request = httpx_mock.get_request()
    body = json.loads(request.content)
    assert body["reasoning"] == {"effort": "high"}


@pytest.mark.asyncio
async def test_openai_compat_no_reasoning_when_none(httpx_mock) -> None:
    """When reasoning_model is None, no reasoning params should be in the payload."""
    httpx_mock.add_response(
        url="https://openrouter.ai/v1/chat/completions",
        json={
            "model": "meta-llama/llama-3-8b",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "response"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        },
    )

    backend = OpenAICompatBackend(
        base_url="https://openrouter.ai",
        model="meta-llama/llama-3-8b",
        api_key="sk-test",
    )
    await backend.generate("system", "user", reasoning_model=None)
    await backend.close()

    request = httpx_mock.get_request()
    body = json.loads(request.content)
    assert body["model"] == "meta-llama/llama-3-8b"
    assert "reasoning" not in body


@pytest.mark.asyncio
async def test_openai_compat_parses_reasoning_tokens(httpx_mock) -> None:
    """reasoning_tokens should be extracted from usage.completion_tokens_details."""
    httpx_mock.add_response(
        url="https://openrouter.ai/v1/chat/completions",
        json={
            "model": "anthropic/claude-sonnet-4-6",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "result"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 250,
                "completion_tokens_details": {
                    "reasoning_tokens": 200,
                },
            },
        },
    )

    backend = OpenAICompatBackend(
        base_url="https://openrouter.ai",
        model="base-model",
        api_key="sk-test",
    )
    response = await backend.generate(
        "system", "user", reasoning_model="anthropic/claude-sonnet-4-6",
    )
    await backend.close()

    assert response.reasoning_tokens == 200
    assert response.completion_tokens == 250


@pytest.mark.asyncio
async def test_openai_compat_parses_thinking_content(httpx_mock) -> None:
    """Thinking content should be extracted from message.reasoning."""
    httpx_mock.add_response(
        url="https://openrouter.ai/v1/chat/completions",
        json={
            "model": "anthropic/claude-sonnet-4-6",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "final answer",
                        "reasoning": "Let me think step by step...",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 50},
        },
    )

    backend = OpenAICompatBackend(
        base_url="https://openrouter.ai",
        model="base-model",
        api_key="sk-test",
    )
    response = await backend.generate(
        "system", "user", reasoning_model="anthropic/claude-sonnet-4-6",
    )
    await backend.close()

    assert response.thinking == "Let me think step by step..."
    assert response.content == "final answer"


@pytest.mark.asyncio
async def test_openai_compat_no_thinking_when_absent(httpx_mock) -> None:
    """thinking should be None when message.reasoning is absent."""
    httpx_mock.add_response(
        url="https://openrouter.ai/v1/chat/completions",
        json={
            "model": "openai/gpt-5.2",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "answer"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
    )

    backend = OpenAICompatBackend(
        base_url="https://openrouter.ai",
        model="base-model",
        api_key="sk-test",
    )
    response = await backend.generate(
        "system", "user", reasoning_model="openai/gpt-5.2",
    )
    await backend.close()

    assert response.thinking is None
    assert response.reasoning_tokens == 0


# -- Ollama reasoning tests --


@pytest.mark.asyncio
async def test_ollama_ignores_reasoning_model(httpx_mock) -> None:
    """Ollama should ignore reasoning_model and use its own model."""
    httpx_mock.add_response(
        url="http://test-ollama:11434/api/chat",
        json={
            "model": "llama3",
            "message": {"role": "assistant", "content": "response"},
            "done": True,
            "prompt_eval_count": 50,
            "eval_count": 30,
        },
    )

    backend = OllamaBackend(base_url="http://test-ollama:11434", model="llama3")
    response = await backend.generate(
        "system", "user", reasoning_model="anthropic/claude-sonnet-4-6",
    )
    await backend.close()

    # Should use its own model, not the reasoning model
    request = httpx_mock.get_request()
    body = json.loads(request.content)
    assert body["model"] == "llama3"
    assert "reasoning" not in body

    # Response should have zero reasoning tokens
    assert response.reasoning_tokens == 0
    assert response.thinking is None
