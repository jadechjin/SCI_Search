"""SerpAPI Google Scholar search source adapter."""

from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any

import httpx

from paper_search.models import Author, RawPaper, SearchStrategy
from paper_search.sources.base import SearchSource
from paper_search.sources.exceptions import (
    NonRetryableError,
    RetryableError,
    SerpAPIError,
)

_HOSTNAME_PATTERN = re.compile(r"\S+\.(?:com|org|edu|net)(?:\b|/|$)", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"^(19|20)\d{2}$")
_DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s,;)}\]>]+")
_SEGMENT_SPLIT = re.compile(r"\s+-\s+")


def _is_hostname(value: str) -> bool:
    return bool(_HOSTNAME_PATTERN.search(value.strip()))


class SerpAPIScholarSource(SearchSource):
    """SerpAPI Google Scholar adapter."""

    def __init__(
        self,
        api_key: str,
        rate_limit_rps: float = 2.0,
        timeout_s: float = 20.0,
        max_retries: int = 3,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.rate_limit_rps = rate_limit_rps
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client = client or httpx.AsyncClient()
        self._lock = asyncio.Lock()
        self._last_request_time = 0.0
        self._min_interval = 1.0 / rate_limit_rps

    async def _rate_limit(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_request_time = time.monotonic()

    async def _fetch_page(self, params: dict) -> dict:
        await self._rate_limit()

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.get(
                    "https://serpapi.com/search.json",
                    params=params,
                    timeout=self.timeout_s,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    backoff = min(16, 2**attempt) + random.uniform(0, 1)
                    await asyncio.sleep(backoff)
                    continue
                break
            except httpx.RequestError:
                last_error = RetryableError("SerpAPI request failed")
                if attempt < self.max_retries:
                    backoff = min(16, 2**attempt) + random.uniform(0, 1)
                    await asyncio.sleep(backoff)
                    continue
                break

            status_code = response.status_code

            if status_code == 200:
                data = response.json()
                if "error" in data:
                    raise SerpAPIError(str(data["error"]))
                return data

            if status_code in {429, 500, 503}:
                last_error = RetryableError(
                    f"Transient SerpAPI HTTP {status_code}"
                )
                if attempt < self.max_retries:
                    backoff = min(16, 2**attempt) + random.uniform(0, 1)
                    await asyncio.sleep(backoff)
                    continue
                break

            if status_code in {401, 403}:
                raise NonRetryableError(f"SerpAPI authentication error ({status_code})")

            raise SerpAPIError(f"SerpAPI request failed with HTTP {status_code}")

        if isinstance(last_error, RetryableError):
            raise last_error
        if isinstance(last_error, httpx.TimeoutException):
            raise RetryableError("SerpAPI request timed out after retries") from last_error
        raise RetryableError("SerpAPI request failed after retries")

    @property
    def source_name(self) -> str:
        return "serpapi_scholar"

    # ------------------------------------------------------------------
    # Static parsers (Task 3, 4, 5)
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_summary(
        summary: str,
    ) -> tuple[list[Author], int | None, str | None]:
        """Parse publication_info.summary into (authors, year, venue).

        Never raises; returns ([], None, None) on any failure.
        """
        try:
            if not summary or not summary.strip():
                return [], None, None

            segments = [s.strip() for s in _SEGMENT_SPLIT.split(summary) if s.strip()]
            if not segments:
                return [], None, None

            # Find year segment
            year_index: int | None = None
            year: int | None = None
            for i, seg in enumerate(segments):
                if _YEAR_PATTERN.fullmatch(seg):
                    year_index = i
                    year = int(seg)
                    break

            if year_index is not None:
                # Authors: everything before year
                author_parts = ", ".join(segments[:year_index])
                authors = [
                    Author(name=name.strip())
                    for name in author_parts.split(",")
                    if name.strip()
                ]
                # Venue: everything after year, filtering hostnames
                venue_parts = [
                    s for s in segments[year_index + 1 :] if not _is_hostname(s)
                ]
                venue = " - ".join(venue_parts).strip() or None
                return authors, year, venue

            # No year found: first segment = authors, last = venue (if >1 segment)
            authors = [
                Author(name=name.strip())
                for name in segments[0].split(",")
                if name.strip()
            ]
            if len(segments) > 1:
                last = segments[-1]
                venue = last if not _is_hostname(last) else None
            else:
                venue = None
            return authors, None, venue
        except Exception:
            return [], None, None

    @staticmethod
    def _extract_doi(text: str) -> str | None:
        """Extract first DOI from arbitrary text. Returns None if not found."""
        try:
            if not text:
                return None
            match = _DOI_PATTERN.search(text)
            if not match:
                return None
            return match.group(0).rstrip(".,;:)")
        except Exception:
            return None

    @staticmethod
    def _parse_result(raw: dict[str, Any]) -> RawPaper:
        """Parse a single SerpAPI organic_result into RawPaper."""
        try:
            summary = raw.get("publication_info", {}).get("summary", "")
            authors, year, venue = SerpAPIScholarSource._parse_summary(summary)

            citation_count = (
                raw.get("inline_links", {}).get("cited_by", {}).get("total", 0)
            )

            # Prefer PDF resource link over generic link
            full_text_url = None
            for resource in raw.get("resources", []):
                if resource.get("file_format") == "PDF" and resource.get("link"):
                    full_text_url = resource["link"]
                    break
            if not full_text_url:
                full_text_url = raw.get("link")

            doi = SerpAPIScholarSource._extract_doi(
                f"{raw.get('link', '')} {raw.get('snippet', '')}"
            )

            return RawPaper(
                doi=doi,
                title=raw.get("title", ""),
                authors=authors,
                abstract=None,
                snippet=raw.get("snippet"),
                year=year,
                venue=venue,
                source="serpapi_scholar",
                citation_count=citation_count or 0,
                full_text_url=full_text_url,
                raw_data=raw,
            )
        except Exception:
            return RawPaper(
                title=str(raw.get("title", "")),
                source="serpapi_scholar",
                raw_data=raw,
            )

    # ------------------------------------------------------------------
    # Search methods (Task 6-9, implemented in Phase C)
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        max_results: int = 20,
        year_from: int | None = None,
        year_to: int | None = None,
        language: str | None = None,
    ) -> list[RawPaper]:
        if max_results <= 0:
            return []

        page_size = min(20, max_results)
        params: dict[str, Any] = {
            "engine": "google_scholar",
            "q": query,
            "api_key": self.api_key,
            "num": page_size,
        }
        if year_from is not None:
            params["as_ylo"] = year_from
        if year_to is not None:
            params["as_yhi"] = year_to
        if language:
            params["lr"] = f"lang_{language}"

        papers: list[RawPaper] = []
        start = 0

        while len(papers) < max_results:
            page_params = dict(params)
            page_params["start"] = start

            try:
                data = await self._fetch_page(page_params)
            except SerpAPIError:
                if papers:
                    return papers[:max_results]
                raise

            organic_results = data.get("organic_results", [])
            if not organic_results:
                break

            for raw in organic_results:
                papers.append(self._parse_result(raw))
                if len(papers) >= max_results:
                    break

            start += page_size

        return papers[:max_results]

    async def search_advanced(self, strategy: SearchStrategy) -> list[RawPaper]:
        if not strategy.queries:
            return []

        per_query = max(1, strategy.filters.max_results // len(strategy.queries))

        all_results: list[RawPaper] = []
        for query in strategy.queries:
            all_results.extend(
                await self.search(
                    query.boolean_query,
                    max_results=per_query,
                    year_from=strategy.filters.year_from,
                    year_to=strategy.filters.year_to,
                    language=strategy.filters.language,
                )
            )

        return all_results
