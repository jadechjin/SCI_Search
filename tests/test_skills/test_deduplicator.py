"""Tests for Deduplicator skill."""

from __future__ import annotations

import json
from typing import Any

import pytest

from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError, LLMResponseError
from paper_search.models import RawPaper
from paper_search.skills.deduplicator import Deduplicator


class MockDedupLLM(LLMProvider):
    def __init__(self, response: dict | Exception | None = None) -> None:
        self._response = response
        self.call_count = 0

    def _error_map(self, exc: Exception) -> None:
        return None

    async def _call(self, system_prompt: str, user_message: str) -> str:
        return ""

    async def _call_json(
        self, system_prompt: str, user_message: str, schema: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.call_count += 1
        if isinstance(self._response, Exception):
            raise self._response
        if isinstance(self._response, dict):
            return self._response
        raise LLMResponseError("No response")


def _paper(
    title: str,
    id: str = "",
    doi: str | None = None,
    result_id: str | None = None,
    url: str | None = None,
    snippet: str | None = None,
    year: int | None = None,
    citation_count: int = 0,
) -> RawPaper:
    raw_data = {}
    if result_id:
        raw_data["result_id"] = result_id
    return RawPaper(
        id=id or title.lower().replace(" ", "-"),
        title=title,
        doi=doi,
        source="test",
        full_text_url=url,
        snippet=snippet,
        year=year,
        citation_count=citation_count,
        raw_data=raw_data,
    )


class TestDedupAlgorithmPass:
    @pytest.mark.asyncio
    async def test_dedup_by_doi(self):
        a = _paper("Paper A", id="a", doi="10.1234/A")
        b = _paper("Paper B Different Title", id="b", doi="10.1234/a")
        dedup = Deduplicator()
        result = await dedup.deduplicate([a, b])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_dedup_by_result_id(self):
        a = _paper("Paper A", id="a", result_id="RID123")
        b = _paper("Paper A Copy", id="b", result_id="RID123")
        dedup = Deduplicator()
        result = await dedup.deduplicate([a, b])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_dedup_by_url(self):
        a = _paper("Paper A", id="a", url="https://example.com/paper1")
        b = _paper("Paper B", id="b", url="https://example.com/paper1")
        dedup = Deduplicator()
        result = await dedup.deduplicate([a, b])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_dedup_by_normalized_title(self):
        a = _paper("  Effect of Temperature on Steel  ", id="a")
        b = _paper("effect of temperature on steel", id="b")
        dedup = Deduplicator()
        result = await dedup.deduplicate([a, b])
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_dedup_no_false_positive(self):
        a = _paper("Paper About LLM", id="a")
        b = _paper("Paper About Robotics", id="b")
        dedup = Deduplicator()
        result = await dedup.deduplicate([a, b])
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_dedup_empty(self):
        dedup = Deduplicator()
        result = await dedup.deduplicate([])
        assert result == []

    @pytest.mark.asyncio
    async def test_dedup_single(self):
        p = _paper("Solo Paper", id="solo")
        dedup = Deduplicator()
        result = await dedup.deduplicate([p])
        assert len(result) == 1
        assert result[0].id == "solo"


class TestDedupLLMPass:
    @pytest.mark.asyncio
    async def test_llm_groups_duplicates(self):
        a = _paper("Impact of LLM on Radiology", id="a", year=2023)
        b = _paper("Large Language Models in Radiological Diagnosis", id="b", year=2023)
        c = _paper("Unrelated Steel Paper", id="c", year=2020)

        llm = MockDedupLLM({"groups": [["a", "b"]], "singles": ["c"]})
        dedup = Deduplicator(llm=llm)
        result = await dedup.deduplicate([a, b, c])

        assert len(result) == 2  # 1 merged + 1 single

    @pytest.mark.asyncio
    async def test_llm_failure_graceful(self):
        a = _paper("Paper A", id="a")
        b = _paper("Paper B", id="b")

        llm = MockDedupLLM(LLMError("API down"))
        dedup = Deduplicator(llm=llm)
        result = await dedup.deduplicate([a, b])

        # LLM fails → algorithm pass only, both papers preserved (different titles)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_no_llm_mode(self):
        a = _paper("Paper A", id="a")
        b = _paper("Paper B", id="b")

        dedup = Deduplicator(llm=None)
        result = await dedup.deduplicate([a, b])
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_skip_llm_pass_when_over_candidate_limit(self):
        papers = [_paper(f"Paper {i}", id=str(i)) for i in range(3)]
        llm = MockDedupLLM({"groups": []})
        dedup = Deduplicator(
            llm=llm,
            enable_llm_pass=True,
            llm_max_candidates=2,
        )
        result = await dedup.deduplicate(papers)

        assert len(result) == 3
        assert llm.call_count == 0

    @pytest.mark.asyncio
    async def test_disable_llm_pass(self):
        a = _paper("Paper A", id="a")
        b = _paper("Paper B", id="b")
        llm = MockDedupLLM({"groups": [["a", "b"]]})
        dedup = Deduplicator(
            llm=llm,
            enable_llm_pass=False,
        )
        result = await dedup.deduplicate([a, b])

        assert len(result) == 2
        assert llm.call_count == 0


class TestDedupMerge:
    @pytest.mark.asyncio
    async def test_merge_richest_record(self):
        a = _paper("Same Title", id="a", doi=None, snippet="short", citation_count=5)
        b = _paper("Same Title", id="b", doi="10.1234/x", snippet="much longer snippet detail", citation_count=10)

        dedup = Deduplicator()
        result = await dedup.deduplicate([a, b])
        assert len(result) == 1
        merged = result[0]
        assert merged.doi == "10.1234/x"
        assert merged.citation_count == 10


class TestNormalizeTitle:
    def test_basic(self):
        assert Deduplicator._normalize_title("  Hello, World!  ") == "hello world"

    def test_punctuation(self):
        assert Deduplicator._normalize_title("A.B-C:D") == "abcd"

    def test_whitespace(self):
        assert Deduplicator._normalize_title("a   b\tc") == "a b c"

    def test_idempotent(self):
        t = "Effect of Temperature on Steel"
        assert Deduplicator._normalize_title(Deduplicator._normalize_title(t)) == Deduplicator._normalize_title(t)
