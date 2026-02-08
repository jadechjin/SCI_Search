"""LLM provider factory."""

from __future__ import annotations

from paper_search.config import LLMConfig
from paper_search.llm.base import LLMProvider


def create_provider(config: LLMConfig) -> LLMProvider:
    """Create an LLM provider from configuration."""
    if not config.api_key:
        raise ValueError(
            f"API key required for provider '{config.provider}'"
        )
    if not config.model:
        raise ValueError(
            f"Model name required for provider '{config.provider}'"
        )

    match config.provider:
        case "openai":
            from paper_search.llm.openai_provider import OpenAIProvider

            return OpenAIProvider(config)
        case "claude":
            from paper_search.llm.claude_provider import ClaudeProvider

            return ClaudeProvider(config)
        case "gemini":
            from paper_search.llm.gemini_provider import GeminiProvider

            return GeminiProvider(config)
        case _:
            raise ValueError(f"Unknown LLM provider: {config.provider}")
