"""OpenAI LLM provider (also supports OpenAI-compatible APIs)."""

from __future__ import annotations

from typing import Any

import openai

from paper_search.config import LLMConfig
from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMAuthError, LLMError, LLMRateLimitError
from paper_search.llm.json_utils import extract_json


class OpenAIProvider(LLMProvider):
    """OpenAI API provider. Also works with OpenAI-compatible endpoints."""

    def __init__(self, config: LLMConfig) -> None:
        self._client = openai.AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    def _error_map(self, exc: Exception) -> LLMError | None:
        if isinstance(exc, openai.AuthenticationError):
            return LLMAuthError(str(exc))
        if isinstance(exc, openai.RateLimitError):
            return LLMRateLimitError(str(exc))
        if isinstance(exc, openai.APIError):
            return LLMError(str(exc))
        return None

    async def _call(self, system_prompt: str, user_message: str) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.choices[0].message.content or ""

    async def _call_json(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or ""
        return extract_json(text)
