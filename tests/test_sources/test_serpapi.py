"""Tests for the SerpAPI Google Scholar adapter."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from paper_search.models import SearchConstraints, SearchQuery, SearchStrategy
from paper_search.sources.exceptions import NonRetryableError, RetryableError
from paper_search.sources.serpapi_scholar import SerpAPIScholarSource

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _load_fixture() -> dict:
    return json.loads((FIXTURES_DIR / "serpapi_response.json").read_text())


def _make_source(
    client: httpx.AsyncClient | None = None,
    max_calls: int | None = None,
) -> SerpAPIScholarSource:
    return SerpAPIScholarSource(
        api_key="test_key",
        rate_limit_rps=100.0,  # fast for tests
        max_calls=max_calls,
        timeout_s=5.0,
        max_retries=3,
        client=client,
    )


def _mock_response(status_code: int = 200, json_data: dict | None = None) -> httpx.Response:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    return resp


# ======================================================================
# Task 3: _parse_summary
# ======================================================================


class TestParseSummary:
    def test_standard(self):
        authors, year, venue = SerpAPIScholarSource._parse_summary(
            "ZH Zhou, Y Liu - 2021 - Springer"
        )
        assert [a.name for a in authors] == ["ZH Zhou", "Y Liu"]
        assert year == 2021
        assert venue == "Springer"

    def test_no_year(self):
        authors, year, venue = SerpAPIScholarSource._parse_summary("A Smith - Nature")
        assert [a.name for a in authors] == ["A Smith"]
        assert year is None
        assert venue == "Nature"

    def test_hostname_venue(self):
        authors, year, venue = SerpAPIScholarSource._parse_summary(
            "A Smith - 2021 - books.google.com"
        )
        assert [a.name for a in authors] == ["A Smith"]
        assert year == 2021
        assert venue is None

    def test_empty(self):
        authors, year, venue = SerpAPIScholarSource._parse_summary("")
        assert authors == []
        assert year is None
        assert venue is None

    def test_year_only(self):
        authors, year, venue = SerpAPIScholarSource._parse_summary("2020 - arxiv.org")
        assert authors == []
        assert year == 2020
        assert venue is None  # arxiv.org is a hostname


# ======================================================================
# Task 4: _extract_doi
# ======================================================================


class TestExtractDoi:
    def test_from_url(self):
        result = SerpAPIScholarSource._extract_doi(
            "https://doi.org/10.1234/test.2024"
        )
        assert result == "10.1234/test.2024"

    def test_none(self):
        assert SerpAPIScholarSource._extract_doi("no doi here") is None

    def test_with_trailing_comma(self):
        result = SerpAPIScholarSource._extract_doi(
            "see 10.1038/s41586-024-07386-0, for details"
        )
        assert result == "10.1038/s41586-024-07386-0"

    def test_empty_string(self):
        assert SerpAPIScholarSource._extract_doi("") is None


# ======================================================================
# Task 5: _parse_result
# ======================================================================


class TestParseResult:
    def test_full(self):
        fixture = _load_fixture()
        raw = fixture["organic_results"][0]
        paper = SerpAPIScholarSource._parse_result(raw)

        assert paper.title == "Language Models are Few-Shot Learners"
        assert paper.source == "serpapi_scholar"
        assert paper.year == 2020
        assert paper.citation_count == 15234
        assert paper.doi == "10.48550/arXiv.2005.14165"
        assert paper.snippet is not None
        assert paper.abstract is None
        assert paper.full_text_url == "https://arxiv.org/pdf/2005.14165.pdf"
        assert len(paper.authors) > 0
        assert paper.raw_data == raw

    def test_minimal(self):
        raw = {"title": "Minimal Paper"}
        paper = SerpAPIScholarSource._parse_result(raw)
        assert paper.title == "Minimal Paper"
        assert paper.source == "serpapi_scholar"
        assert paper.authors == []
        assert paper.year is None
        assert paper.doi is None
        assert paper.citation_count == 0

    def test_hostname_venue_filtered(self):
        fixture = _load_fixture()
        raw = fixture["organic_results"][3]  # BERT, venue = books.google.com
        paper = SerpAPIScholarSource._parse_result(raw)
        assert paper.venue is None  # hostname filtered


# ======================================================================
# Task 8: search() with pagination
# ======================================================================


class TestSearch:
    @pytest.mark.asyncio
    async def test_pagination(self):
        fixture = _load_fixture()
        page1 = dict(fixture)
        page1["organic_results"] = fixture["organic_results"][:3]
        page2 = dict(fixture)
        page2["organic_results"] = fixture["organic_results"][3:]

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(
            side_effect=[
                _mock_response(200, page1),
                _mock_response(200, page2),
            ]
        )

        source = _make_source(client=client)
        results = await source.search("test query", max_results=5)

        assert len(results) == 5
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_results(self):
        empty_response = {
            "search_metadata": {"status": "Success"},
            "organic_results": [],
        }
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=_mock_response(200, empty_response))

        source = _make_source(client=client)
        results = await source.search("nonexistent query")

        assert results == []

    @pytest.mark.asyncio
    async def test_partial_on_error(self):
        fixture = _load_fixture()
        page1 = dict(fixture)
        page1["organic_results"] = fixture["organic_results"][:3]

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(
            side_effect=[
                _mock_response(200, page1),
                _mock_response(500),
                _mock_response(500),
                _mock_response(500),
                _mock_response(500),
            ]
        )

        source = SerpAPIScholarSource(
            api_key="test",
            rate_limit_rps=100.0,
            timeout_s=5.0,
            max_retries=3,
            client=client,
        )
        results = await source.search("test", max_results=10)

        assert len(results) == 3  # got page 1 results despite page 2 failure

    @pytest.mark.asyncio
    async def test_respects_max_calls_limit(self):
        fixture = _load_fixture()
        page1 = dict(fixture)
        page1["organic_results"] = fixture["organic_results"][:3]

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(
            side_effect=[
                _mock_response(200, page1),
                _mock_response(200, fixture),
            ]
        )

        source = _make_source(client=client, max_calls=1)
        results = await source.search("test query", max_results=10)

        assert len(results) == 3
        assert client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_zero_max_calls_makes_no_requests(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=_mock_response(200, _load_fixture()))

        source = _make_source(client=client, max_calls=0)
        results = await source.search("test query", max_results=10)

        assert results == []
        assert client.get.call_count == 0


# ======================================================================
# Task 7: _fetch_page retry behavior
# ======================================================================


class TestFetchPage:
    @pytest.mark.asyncio
    async def test_retry_on_429(self):
        fixture = _load_fixture()
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(
            side_effect=[
                _mock_response(429),
                _mock_response(429),
                _mock_response(200, fixture),
            ]
        )

        source = _make_source(client=client)
        result = await source._fetch_page({"q": "test", "api_key": "key"})

        assert result["search_metadata"]["status"] == "Success"
        assert client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_401(self):
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=_mock_response(401))

        source = _make_source(client=client)
        with pytest.raises(NonRetryableError):
            await source._fetch_page({"q": "test", "api_key": "key"})

        assert client.get.call_count == 1


# ======================================================================
# Task 6: Rate limiting
# ======================================================================


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_rate_limit_timing(self):
        source = SerpAPIScholarSource(
            api_key="test",
            rate_limit_rps=4.0,  # min_interval = 0.25s
            client=AsyncMock(spec=httpx.AsyncClient),
        )

        start = time.monotonic()
        await source._rate_limit()
        await source._rate_limit()
        elapsed = time.monotonic() - start

        # Second call should wait ~0.25s
        assert elapsed >= 0.20  # allow small scheduling variance


# ======================================================================
# Task 9: search_advanced() dedup
# ======================================================================


class TestSearchAdvanced:
    @pytest.mark.asyncio
    async def test_multi_query(self):
        fixture = _load_fixture()
        # Both queries return same results -> no source-level dedup (pipeline handles it)
        response = dict(fixture)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = AsyncMock(return_value=_mock_response(200, response))

        source = _make_source(client=client)
        strategy = SearchStrategy(
            queries=[
                SearchQuery(keywords=["LLM"], boolean_query="large language model"),
                SearchQuery(keywords=["GPT"], boolean_query="GPT language model"),
            ],
            sources=["serpapi_scholar"],
            filters=SearchConstraints(max_results=10),
        )

        results = await source.search_advanced(strategy)

        # 5 papers per query, no source-level dedup -> 10 total
        assert len(results) == 10
