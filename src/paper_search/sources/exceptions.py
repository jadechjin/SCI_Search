"""Exceptions for search source adapters."""


class SearchSourceError(Exception):
    """Base exception for all search source errors."""


class SerpAPIError(SearchSourceError):
    """Error from SerpAPI service."""


class RetryableError(SerpAPIError):
    """Transient error that can be retried (429, 500, 503, timeout)."""


class NonRetryableError(SerpAPIError):
    """Permanent error that should not be retried (401, 403)."""


class SerpAPICallLimitError(NonRetryableError):
    """SerpAPI call budget exhausted for current source instance."""
