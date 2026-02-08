"""Tests for JSON extraction utility."""

import pytest

from paper_search.llm.exceptions import LLMResponseError
from paper_search.llm.json_utils import extract_json


class TestExtractCleanJson:
    def test_simple_object(self):
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_with_whitespace(self):
        assert extract_json('  {"a": 1}  ') == {"a": 1}

    def test_nested_object(self):
        text = '{"topic": "LLM", "constraints": {"year_from": 2020, "max_results": 50}}'
        result = extract_json(text)
        assert result["topic"] == "LLM"
        assert result["constraints"]["year_from"] == 2020

    def test_with_array_values(self):
        text = '{"concepts": ["NLP", "transformers", "attention"]}'
        result = extract_json(text)
        assert result["concepts"] == ["NLP", "transformers", "attention"]


class TestExtractMarkdownFenced:
    def test_json_tag(self):
        text = '```json\n{"topic": "LLM"}\n```'
        assert extract_json(text) == {"topic": "LLM"}

    def test_no_tag(self):
        text = '```\n{"topic": "LLM"}\n```'
        assert extract_json(text) == {"topic": "LLM"}

    def test_nested_in_markdown(self):
        text = '```json\n{"topic": "LLM", "constraints": {"year_from": 2020}}\n```'
        result = extract_json(text)
        assert result["constraints"]["year_from"] == 2020

    def test_with_extra_text_around_fence(self):
        text = 'Here is the JSON:\n```json\n{"topic": "LLM"}\n```\nDone.'
        assert extract_json(text) == {"topic": "LLM"}


class TestExtractSurroundingText:
    def test_text_before_and_after(self):
        text = 'Here is the result:\n{"topic": "LLM"}\nHope this helps!'
        assert extract_json(text) == {"topic": "LLM"}

    def test_text_before_only(self):
        text = 'Result: {"a": 1}'
        assert extract_json(text) == {"a": 1}


class TestExtractFailures:
    def test_empty_string(self):
        with pytest.raises(LLMResponseError, match="Empty LLM response"):
            extract_json("")

    def test_whitespace_only(self):
        with pytest.raises(LLMResponseError, match="Empty LLM response"):
            extract_json("   ")

    def test_no_json(self):
        with pytest.raises(LLMResponseError, match="Failed to extract JSON"):
            extract_json("I cannot parse this query")

    def test_invalid_json(self):
        with pytest.raises(LLMResponseError):
            extract_json("{invalid json content}")
