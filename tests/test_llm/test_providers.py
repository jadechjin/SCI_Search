"""Tests for LLM providers (mocked SDKs, no real API calls)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from paper_search.config import LLMConfig
from paper_search.llm.exceptions import LLMAuthError, LLMError, LLMRateLimitError
from paper_search.llm.factory import create_provider
from paper_search.llm.openai_provider import OpenAIProvider
from paper_search.llm.claude_provider import ClaudeProvider
from paper_search.llm.gemini_provider import GeminiProvider


def _config(provider: str = "openai", **overrides: Any) -> LLMConfig:
    defaults = {
        "provider": provider,
        "api_key": "test-key",
        "model": "test-model",
        "temperature": 0.0,
        "max_tokens": 1024,
    }
    defaults.update(overrides)
    return LLMConfig(**defaults)


# ---------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------


class TestFactory:
    def test_creates_openai(self):
        p = create_provider(_config("openai"))
        assert isinstance(p, OpenAIProvider)

    def test_creates_claude(self):
        p = create_provider(_config("claude"))
        assert isinstance(p, ClaudeProvider)

    def test_creates_gemini(self):
        p = create_provider(_config("gemini"))
        assert isinstance(p, GeminiProvider)

    def test_unknown_provider(self):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_provider(_config("xxx"))

    def test_missing_api_key(self):
        with pytest.raises(ValueError, match="API key required"):
            create_provider(_config("openai", api_key=""))

    def test_missing_model(self):
        with pytest.raises(ValueError, match="Model name required"):
            create_provider(_config("openai", model=""))


# ---------------------------------------------------------------
# OpenAI provider tests
# ---------------------------------------------------------------


class TestOpenAIProvider:
    @pytest.fixture()
    def provider(self):
        return OpenAIProvider(_config("openai"))

    @pytest.mark.asyncio
    async def test_complete(self, provider):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Hello world"

        provider._client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        result = await provider.complete("system", "user")
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_complete_json(self, provider):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"topic": "LLM"}'

        provider._client.chat.completions.create = AsyncMock(
            return_value=mock_response
        )
        result = await provider.complete_json("system", "user")
        assert result == {"topic": "LLM"}

    @pytest.mark.asyncio
    async def test_auth_error(self, provider):
        import openai

        provider._client.chat.completions.create = AsyncMock(
            side_effect=openai.AuthenticationError(
                message="bad key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )
        with pytest.raises(LLMAuthError):
            await provider.complete("system", "user")

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, provider):
        import openai

        provider._client.chat.completions.create = AsyncMock(
            side_effect=openai.RateLimitError(
                message="rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
        )
        with pytest.raises(LLMRateLimitError):
            await provider.complete("system", "user")


# ---------------------------------------------------------------
# Claude provider tests
# ---------------------------------------------------------------


class TestClaudeProvider:
    @pytest.fixture()
    def provider(self):
        return ClaudeProvider(_config("claude"))

    @pytest.mark.asyncio
    async def test_complete(self, provider):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Hello from Claude")]

        provider._client.messages.create = AsyncMock(
            return_value=mock_response
        )
        result = await provider.complete("system prompt", "user msg")
        assert result == "Hello from Claude"

        # Verify system is passed as separate param
        call_kwargs = provider._client.messages.create.call_args.kwargs
        assert call_kwargs["system"] == "system prompt"
        assert call_kwargs["messages"] == [{"role": "user", "content": "user msg"}]

    @pytest.mark.asyncio
    async def test_complete_json(self, provider):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"topic": "NLP"}')]

        provider._client.messages.create = AsyncMock(
            return_value=mock_response
        )
        result = await provider.complete_json("system", "user")
        assert result == {"topic": "NLP"}

        # Verify JSON instruction appended to system
        call_kwargs = provider._client.messages.create.call_args.kwargs
        assert "valid JSON only" in call_kwargs["system"]

    @pytest.mark.asyncio
    async def test_auth_error(self, provider):
        import anthropic

        provider._client.messages.create = AsyncMock(
            side_effect=anthropic.AuthenticationError(
                message="bad key",
                response=MagicMock(status_code=401),
                body=None,
            )
        )
        with pytest.raises(LLMAuthError):
            await provider.complete("system", "user")


# ---------------------------------------------------------------
# Gemini provider tests
# ---------------------------------------------------------------


class TestGeminiProvider:
    @pytest.fixture()
    def provider(self):
        return GeminiProvider(_config("gemini"))

    @pytest.mark.asyncio
    async def test_complete(self, provider):
        mock_response = MagicMock()
        mock_response.text = "Hello from Gemini"

        provider._client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )
        result = await provider.complete("system", "user msg")
        assert result == "Hello from Gemini"

    @pytest.mark.asyncio
    async def test_complete_json(self, provider):
        mock_response = MagicMock()
        mock_response.text = '{"topic": "AI"}'

        provider._client.aio.models.generate_content = AsyncMock(
            return_value=mock_response
        )
        result = await provider.complete_json("system", "user")
        assert result == {"topic": "AI"}

    @pytest.mark.asyncio
    async def test_auth_error(self, provider):
        from google.genai import errors as genai_errors

        provider._client.aio.models.generate_content = AsyncMock(
            side_effect=genai_errors.ClientError(401, "unauthorized")
        )
        with pytest.raises(LLMAuthError):
            await provider.complete("system", "user")

    @pytest.mark.asyncio
    async def test_rate_limit_error(self, provider):
        from google.genai import errors as genai_errors

        provider._client.aio.models.generate_content = AsyncMock(
            side_effect=genai_errors.ClientError(429, "rate limited")
        )
        with pytest.raises(LLMRateLimitError):
            await provider.complete("system", "user")
