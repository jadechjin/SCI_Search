"""Utilities for extracting JSON from LLM response text."""

from __future__ import annotations

import json
import re
from typing import Any

from paper_search.llm.exceptions import LLMResponseError

_MARKDOWN_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM response text.

    Tries in order:
    1. Direct ``json.loads``
    2. Extract from markdown ````` fence
    3. Find first ``{`` to last ``}`` and parse substring
    4. Raise ``LLMResponseError`` with raw text
    """
    if not text or not text.strip():
        raise LLMResponseError("Empty LLM response")

    stripped = text.strip()

    # Step 1: direct parse
    try:
        result = json.loads(stripped)
        if isinstance(result, dict):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # Step 2: markdown fence
    match = _MARKDOWN_FENCE_RE.search(text)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # Step 3: first { to last }
    first_brace = stripped.find("{")
    last_brace = stripped.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        try:
            result = json.loads(stripped[first_brace : last_brace + 1])
            if isinstance(result, dict):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    raise LLMResponseError(
        f"Failed to extract JSON from LLM response: {text[:200]}"
    )
