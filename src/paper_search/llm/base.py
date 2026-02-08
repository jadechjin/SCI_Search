"""LLM provider abstraction base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from paper_search.llm.exceptions import LLMError


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Subclasses implement _call/_call_json for SDK-specific logic.
    Error handling is centralized in complete/complete_json via _error_map.
    """

    @abstractmethod
    async def _call(self, system_prompt: str, user_message: str) -> str:
        """Provider-specific text completion (no error wrapping)."""
        ...

    @abstractmethod
    async def _call_json(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Provider-specific JSON completion (no error wrapping)."""
        ...

    @abstractmethod
    def _error_map(self, exc: Exception) -> LLMError | None:
        """Map a provider SDK exception to our hierarchy.

        Return None if the exception is not from this provider's SDK.
        """
        ...

    @property
    def _provider_label(self) -> str:
        return self.__class__.__name__

    async def complete(self, system_prompt: str, user_message: str) -> str:
        """Return a text completion with unified error handling."""
        try:
            return await self._call(system_prompt, user_message)
        except LLMError:
            raise
        except Exception as exc:
            mapped = self._error_map(exc)
            if mapped is not None:
                raise mapped from exc
            raise LLMError(
                f"Unexpected error from {self._provider_label}: {exc}"
            ) from exc

    async def complete_json(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a structured JSON completion with unified error handling."""
        try:
            return await self._call_json(system_prompt, user_message, schema)
        except LLMError:
            raise
        except Exception as exc:
            mapped = self._error_map(exc)
            if mapped is not None:
                raise mapped from exc
            raise LLMError(
                f"Unexpected error from {self._provider_label}: {exc}"
            ) from exc
