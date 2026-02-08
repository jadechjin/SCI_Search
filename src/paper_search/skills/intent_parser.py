"""Intent parser skill: natural language -> ParsedIntent."""

from __future__ import annotations

from paper_search.llm.base import LLMProvider
from paper_search.models import ParsedIntent
from paper_search.prompts.domains import get_domain_config
from paper_search.prompts.intent_parsing import INTENT_PARSING_SYSTEM


class IntentParser:
    """Parse user's natural language query into structured research intent."""

    def __init__(self, llm: LLMProvider, domain: str = "general") -> None:
        self._llm = llm
        self._domain = domain

    def _compose_prompt(self) -> str:
        base = INTENT_PARSING_SYSTEM
        domain_config = get_domain_config(self._domain)
        if domain_config:
            base += "\n\n" + domain_config.extra_intent_instructions
        return base

    async def parse(self, user_input: str) -> ParsedIntent:
        prompt = self._compose_prompt()
        schema = ParsedIntent.model_json_schema()
        result = await self._llm.complete_json(prompt, user_input, schema=schema)
        return ParsedIntent.model_validate(result)
