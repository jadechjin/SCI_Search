"""Google Gemini LLM provider."""

from __future__ import annotations

from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from paper_search.config import LLMConfig
from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMAuthError, LLMError, LLMRateLimitError
from paper_search.llm.json_utils import extract_json


class GeminiProvider(LLMProvider):
    """Google Gemini API provider."""

    def __init__(self, config: LLMConfig) -> None:
        kwargs: dict[str, Any] = {"api_key": config.api_key}
        if config.base_url:
            kwargs["http_options"] = types.HttpOptions(base_url=config.base_url)
        self._client = genai.Client(**kwargs)
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    async def complete(self, system_prompt: str, user_message: str) -> str:
        try:
            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_message,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=self._temperature,
                    max_output_tokens=self._max_tokens,
                ),
            )
            return response.text or ""
        except genai_errors.ClientError as exc:
            self._map_client_error(exc)
        except genai_errors.APIError as exc:
            raise LLMError(str(exc)) from exc
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"Unexpected error from Gemini-compatible API: {exc}"
            ) from exc

    async def complete_json(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self._temperature,
                max_output_tokens=self._max_tokens,
                response_mime_type="application/json",
            )
            if schema is not None:
                config.response_schema = schema

            response = await self._client.aio.models.generate_content(
                model=self._model,
                contents=user_message,
                config=config,
            )
            text = response.text or ""
            return extract_json(text)
        except genai_errors.ClientError as exc:
            self._map_client_error(exc)
        except genai_errors.APIError as exc:
            raise LLMError(str(exc)) from exc
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"Unexpected error from Gemini-compatible API: {exc}"
            ) from exc

    @staticmethod
    def _map_client_error(exc: genai_errors.ClientError) -> None:
        """Map Gemini ClientError to our exception hierarchy. Always raises."""
        code = exc.code
        if code in (401, 403):
            raise LLMAuthError(str(exc)) from exc
        if code == 429:
            raise LLMRateLimitError(str(exc)) from exc
        raise LLMError(str(exc)) from exc
