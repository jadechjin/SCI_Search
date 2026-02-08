"""Anthropic Claude LLM provider."""

from __future__ import annotations

from typing import Any

import anthropic

from paper_search.config import LLMConfig
from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMAuthError, LLMError, LLMRateLimitError
from paper_search.llm.json_utils import extract_json

_JSON_INSTRUCTION = (
    "\n\nYou MUST respond with valid JSON only."
    " No markdown, no explanation, no extra text."
)


class ClaudeProvider(LLMProvider):
    """Anthropic Claude API provider."""

    def __init__(self, config: LLMConfig) -> None:
        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["base_url"] = config.base_url
        self._client = anthropic.AsyncAnthropic(**kwargs)
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    def _error_map(self, exc: Exception) -> LLMError | None:
        if isinstance(exc, anthropic.AuthenticationError):
            return LLMAuthError(str(exc))
        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError(str(exc))
        if isinstance(exc, anthropic.APIError):
            return LLMError(str(exc))
        return None

    async def _call(self, system_prompt: str, user_message: str) -> str:
        response = await self._client.messages.create(
            model=self._model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.content[0].text

    async def _call_json(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._client.messages.create(
            model=self._model,
            system=system_prompt + _JSON_INSTRUCTION,
            messages=[{"role": "user", "content": user_message}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        text = response.content[0].text
        return extract_json(text)
