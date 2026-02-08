"""LLM provider exceptions."""


class LLMError(Exception):
    """Base exception for LLM provider errors."""


class LLMAuthError(LLMError):
    """Authentication or authorization failure."""


class LLMRateLimitError(LLMError):
    """Rate limit exceeded."""


class LLMResponseError(LLMError):
    """Failed to parse or extract response from LLM output."""
