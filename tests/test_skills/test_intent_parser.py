"""Tests for IntentParser skill (mocked LLM, no real API calls)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMResponseError
from paper_search.models import IntentType, ParsedIntent
from paper_search.prompts.intent_parsing import INTENT_PARSING_SYSTEM
from paper_search.skills.intent_parser import IntentParser


class MockLLMProvider(LLMProvider):
    """Mock LLM provider that returns a predefined JSON dict."""

    def __init__(self, json_response: dict[str, Any] | str | None = None) -> None:
        self._response = json_response

    def _error_map(self, exc: Exception) -> None:
        return None

    async def _call(self, system_prompt: str, user_message: str) -> str:
        if isinstance(self._response, dict):
            return json.dumps(self._response)
        return self._response or ""

    async def _call_json(
        self,
        system_prompt: str,
        user_message: str,
        schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(self._response, dict):
            return self._response
        if isinstance(self._response, str):
            raise LLMResponseError(f"Failed to extract JSON: {self._response}")
        raise LLMResponseError("Empty response")


_VALID_INTENT = {
    "topic": "大语言模型在医学影像诊断中的应用",
    "concepts": ["大语言模型", "医学影像", "诊断"],
    "intent_type": "survey",
    "constraints": {
        "year_from": 2020,
        "year_to": None,
        "language": None,
        "max_results": 100,
    },
}

_VALID_INTENT_EN = {
    "topic": "LLM applications in medical imaging diagnosis",
    "concepts": ["large language model", "medical imaging", "diagnosis"],
    "intent_type": "method",
    "constraints": {"max_results": 50},
}


class TestIntentParserParse:
    @pytest.mark.asyncio
    async def test_parse_chinese_input(self):
        llm = MockLLMProvider(_VALID_INTENT)
        parser = IntentParser(llm, domain="general")
        result = await parser.parse("大语言模型在医学影像诊断中的应用")

        assert isinstance(result, ParsedIntent)
        assert result.topic == "大语言模型在医学影像诊断中的应用"
        assert len(result.concepts) == 3
        assert result.intent_type == IntentType.SURVEY
        assert result.constraints.year_from == 2020

    @pytest.mark.asyncio
    async def test_parse_english_input(self):
        llm = MockLLMProvider(_VALID_INTENT_EN)
        parser = IntentParser(llm, domain="general")
        result = await parser.parse("LLM applications in medical imaging")

        assert isinstance(result, ParsedIntent)
        assert result.intent_type == IntentType.METHOD
        assert result.constraints.max_results == 50

    @pytest.mark.asyncio
    async def test_parse_malformed_json(self):
        llm = MockLLMProvider("not json at all")
        parser = IntentParser(llm, domain="general")
        with pytest.raises(LLMResponseError):
            await parser.parse("some query")

    @pytest.mark.asyncio
    async def test_parse_missing_required_fields(self):
        llm = MockLLMProvider({"topic": "test"})  # missing concepts, intent_type
        parser = IntentParser(llm, domain="general")
        with pytest.raises(ValidationError):
            await parser.parse("some query")


class TestIntentParserPromptComposition:
    def test_general_domain(self):
        llm = MockLLMProvider()
        parser = IntentParser(llm, domain="general")
        prompt = parser._compose_prompt()
        assert prompt == INTENT_PARSING_SYSTEM

    def test_materials_science_domain(self):
        llm = MockLLMProvider()
        parser = IntentParser(llm, domain="materials_science")
        prompt = parser._compose_prompt()
        assert prompt.startswith(INTENT_PARSING_SYSTEM)
        assert "material families" in prompt
        assert len(prompt) > len(INTENT_PARSING_SYSTEM)

    def test_unknown_domain_fallback(self):
        llm = MockLLMProvider()
        parser = IntentParser(llm, domain="unknown_xyz")
        prompt = parser._compose_prompt()
        assert prompt == INTENT_PARSING_SYSTEM

    def test_custom_domain_loaded_from_env(self, monkeypatch):
        llm = MockLLMProvider()
        monkeypatch.setenv("makesi", "makesi is metallurgy focused terminology")
        parser = IntentParser(llm, domain="makesi")
        prompt = parser._compose_prompt()
        assert prompt.startswith(INTENT_PARSING_SYSTEM)
        assert "makesi is metallurgy focused terminology" in prompt
