"""LLM provider abstraction base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Implementations must support both free-form text completion
    and structured JSON output. The provider knows nothing about
    papers or search -- it is a generic LLM interface.
    """

    @abstractmethod
    async def complete(self, system_prompt: str, user_message: str) -> str:
        """Return a text completion."""
        ...

    @abstractmethod
    async def complete_json(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a structured JSON completion.

        If *schema* is provided, the provider should use it to guide
        the output format (e.g. via function calling or JSON mode).
        """
        ...
