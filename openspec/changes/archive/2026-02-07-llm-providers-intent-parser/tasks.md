# Tasks: LLM Multi-Provider Abstraction + Intent Parser

All decisions are locked in `design.md`. Each task below is pure mechanical execution — zero decisions needed.

---

## Task 1: Add LLM exception hierarchy [DONE]

**File**: `src/paper_search/llm/exceptions.py` (NEW)

Create:
```python
class LLMError(Exception): ...
class LLMAuthError(LLMError): ...
class LLMRateLimitError(LLMError): ...
class LLMResponseError(LLMError): ...
```

**Verify**: `from paper_search.llm.exceptions import LLMError, LLMAuthError, LLMRateLimitError, LLMResponseError` imports without error.

---

## Task 2: Implement JSON extraction utility [DONE]

**File**: `src/paper_search/llm/json_utils.py` (NEW)

Implement `extract_json(text: str) -> dict[str, Any]`:

1. Try `json.loads(text.strip())` directly → return if valid dict
2. Try regex `r"```(?:json)?\s*\n?(.*?)\n?\s*```"` with `re.DOTALL` → parse captured group
3. Try find first `{` and last `}` → parse substring
4. All fail → raise `LLMResponseError(f"Failed to extract JSON from LLM response: {text[:200]}")`

Import `LLMResponseError` from `paper_search.llm.exceptions`.

**Verify**: Test with clean JSON, markdown-fenced JSON, JSON with surrounding text, empty string.

---

## Task 3: Implement OpenAIProvider [DONE]

**File**: `src/paper_search/llm/openai_provider.py` (REWRITE)

```python
import openai
from paper_search.config import LLMConfig
from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError, LLMAuthError, LLMRateLimitError
from paper_search.llm.json_utils import extract_json
```

Constructor:
- Accept `config: LLMConfig`
- `self._client = openai.AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)`
- Store `_model`, `_temperature`, `_max_tokens`

`complete()`:
- `client.chat.completions.create(model, messages=[system, user], temperature, max_tokens)`
- Return `response.choices[0].message.content or ""`
- Wrap in try/except for SDK exceptions → map to LLM exceptions

`complete_json()`:
- Same as complete but add `response_format={"type": "json_object"}`
- Parse response with `extract_json(text)`

Exception mapping:
- `openai.AuthenticationError` → `LLMAuthError`
- `openai.RateLimitError` → `LLMRateLimitError`
- `openai.APIError` → `LLMError`

**Verify**: `from paper_search.llm.openai_provider import OpenAIProvider` imports without error.

---

## Task 4: Implement ClaudeProvider [DONE]

**File**: `src/paper_search/llm/claude_provider.py` (REWRITE)

```python
import anthropic
from paper_search.config import LLMConfig
from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError, LLMAuthError, LLMRateLimitError
from paper_search.llm.json_utils import extract_json
```

Constructor:
- Accept `config: LLMConfig`
- `self._client = anthropic.AsyncAnthropic(api_key=config.api_key)`
- Store `_model`, `_temperature`, `_max_tokens`

`complete()`:
- `client.messages.create(model, system=system_prompt, messages=[{"role": "user", ...}], temperature, max_tokens)`
- Return `response.content[0].text`

`complete_json()`:
- Append to system prompt: `"\n\nYou MUST respond with valid JSON only. No markdown, no explanation, no extra text."`
- Same API call as complete
- Parse response with `extract_json(text)`

Exception mapping:
- `anthropic.AuthenticationError` → `LLMAuthError`
- `anthropic.RateLimitError` → `LLMRateLimitError`
- `anthropic.APIError` → `LLMError`

**Verify**: `from paper_search.llm.claude_provider import ClaudeProvider` imports without error.

---

## Task 5: Implement GeminiProvider [DONE]

**File**: `src/paper_search/llm/gemini_provider.py` (REWRITE)

```python
from google import genai
from google.genai import types
from paper_search.config import LLMConfig
from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError, LLMAuthError, LLMRateLimitError
from paper_search.llm.json_utils import extract_json
```

Constructor:
- Accept `config: LLMConfig`
- `self._client = genai.Client(api_key=config.api_key)`
- Store `_model`, `_temperature`, `_max_tokens`

`complete()`:
- `client.aio.models.generate_content(model, contents=user_message, config=GenerateContentConfig(system_instruction, temperature, max_output_tokens))`
- Return `response.text or ""`

`complete_json()`:
- Same but add to config: `response_mime_type="application/json"`, `response_schema=schema`
- Parse response with `extract_json(text)`

Exception mapping:
- `google.genai.errors.ClientError` with status 401/403 → `LLMAuthError`
- `google.genai.errors.ClientError` with status 429 → `LLMRateLimitError`
- `Exception` from genai → `LLMError`

**Verify**: `from paper_search.llm.gemini_provider import GeminiProvider` imports without error.

---

## Task 6: Rewrite factory to pass config [DONE]

**File**: `src/paper_search/llm/factory.py` (REWRITE)

1. Add validation: `if not config.api_key: raise ValueError(...)`
2. Add validation: `if not config.model: raise ValueError(...)`
3. Match on config.provider, pass `config` to each constructor
4. Unknown provider → raise ValueError

**Verify**: `create_provider(valid_config)` returns correct provider type.

---

## Task 7: Update `__init__.py` exports [DONE]

**File**: `src/paper_search/llm/__init__.py` (MODIFY)

Add:
```python
from paper_search.llm.factory import create_provider
from paper_search.llm.exceptions import LLMError, LLMAuthError, LLMRateLimitError, LLMResponseError
```

**Verify**: `from paper_search.llm import create_provider, LLMError` works.

---

## Task 8: Add domain config loader [DONE]

**File**: `src/paper_search/prompts/domains/__init__.py` (MODIFY)

Add function:
```python
def get_domain_config(domain: str) -> DomainConfig | None:
    match domain:
        case "materials_science":
            from paper_search.prompts.domains.materials_science import MATERIALS_SCIENCE
            return MATERIALS_SCIENCE
        case "general" | _:
            return None
```

Import `DomainConfig` from `.materials_science`.

**Verify**: `get_domain_config("materials_science")` returns `MATERIALS_SCIENCE`; `get_domain_config("general")` returns None.

---

## Task 9: Implement IntentParser [DONE]

**File**: `src/paper_search/skills/intent_parser.py` (REWRITE)

```python
from paper_search.llm.base import LLMProvider
from paper_search.models import ParsedIntent
from paper_search.prompts.intent_parsing import INTENT_PARSING_SYSTEM
from paper_search.prompts.domains import get_domain_config
```

Constructor: `__init__(self, llm: LLMProvider, domain: str = "general")`

`_compose_prompt() -> str`:
1. Start with `INTENT_PARSING_SYSTEM`
2. `domain_config = get_domain_config(self._domain)`
3. If domain_config: append `"\n\n" + domain_config.extra_intent_instructions`
4. Return composed prompt

`async parse(user_input: str) -> ParsedIntent`:
1. `prompt = self._compose_prompt()`
2. `schema = ParsedIntent.model_json_schema()`
3. `result = await self._llm.complete_json(prompt, user_input, schema=schema)`
4. `return ParsedIntent.model_validate(result)`

**Verify**: Mock LLM returns valid JSON → returns ParsedIntent; mock returns garbage → raises.

---

## Task 10: Write JSON extraction tests [DONE]

**File**: `tests/test_llm/__init__.py` (NEW, empty)
**File**: `tests/test_llm/test_json_utils.py` (NEW)

Tests:
1. `test_extract_clean_json` — plain JSON string → parsed dict
2. `test_extract_markdown_fenced_json` — ```json ... ``` → parsed dict
3. `test_extract_markdown_fenced_no_tag` — ``` ... ``` → parsed dict
4. `test_extract_json_with_surrounding_text` — text before/after { } → parsed dict
5. `test_extract_nested_json` — nested objects preserved
6. `test_extract_empty_string` — "" → raises LLMResponseError
7. `test_extract_no_json` — plain text → raises LLMResponseError

**Verify**: `pytest tests/test_llm/test_json_utils.py -v` all pass.

---

## Task 11: Write provider tests (mocked SDKs) [DONE]

**File**: `tests/test_llm/test_providers.py` (NEW)

Tests (all with mocked SDK clients, no real API calls):

### Factory tests:
1. `test_factory_openai` — provider="openai" → OpenAIProvider
2. `test_factory_claude` — provider="claude" → ClaudeProvider
3. `test_factory_gemini` — provider="gemini" → GeminiProvider
4. `test_factory_unknown` — provider="xxx" → ValueError
5. `test_factory_missing_api_key` — api_key="" → ValueError
6. `test_factory_missing_model` — model="" → ValueError

### OpenAI provider tests:
7. `test_openai_complete` — mock AsyncOpenAI → returns text
8. `test_openai_complete_json` — mock AsyncOpenAI → returns dict
9. `test_openai_auth_error` — mock raises AuthenticationError → LLMAuthError
10. `test_openai_rate_limit` — mock raises RateLimitError → LLMRateLimitError

### Claude provider tests:
11. `test_claude_complete` — mock AsyncAnthropic → returns text, verify system param separate
12. `test_claude_complete_json` — mock → returns dict, verify JSON instruction appended
13. `test_claude_auth_error` — mock raises AuthenticationError → LLMAuthError

### Gemini provider tests:
14. `test_gemini_complete` — mock genai.Client → returns text
15. `test_gemini_complete_json` — mock → returns dict, verify response_mime_type
16. `test_gemini_auth_error` — mock raises ClientError(401) → LLMAuthError

**Verify**: `pytest tests/test_llm/test_providers.py -v` all pass.

---

## Task 12: Write intent parser tests [DONE]

**File**: `tests/test_skills/__init__.py` (NEW, empty)
**File**: `tests/test_skills/test_intent_parser.py` (NEW)

Tests (all with mocked LLMProvider):

1. `test_parse_chinese_input` — mock returns valid ParsedIntent JSON for "大语言模型在医学影像诊断中的应用" → returns ParsedIntent
2. `test_parse_english_input` — mock returns valid JSON for "LLM applications in medical imaging" → returns ParsedIntent
3. `test_compose_prompt_general` — domain="general" → returns INTENT_PARSING_SYSTEM only
4. `test_compose_prompt_materials` — domain="materials_science" → returns base + extra instructions
5. `test_compose_prompt_unknown_domain` — domain="xyz" → returns INTENT_PARSING_SYSTEM only (graceful)
6. `test_parse_malformed_json` — mock returns "not json" → raises LLMResponseError
7. `test_parse_missing_fields` — mock returns `{"topic": "test"}` (missing required fields) → raises ValidationError

**Verify**: `pytest tests/test_skills/test_intent_parser.py -v` all pass.

---

## Execution Order

```
Task 1              (exceptions — no dependencies)
Task 2              (json_utils — depends on Task 1 for LLMResponseError)
Task 3  → Task 4  → Task 5  (providers — each depends on Task 1+2, independent of each other)
Task 6              (factory — depends on Task 3+4+5)
Task 7              (exports — depends on Task 1+6)
Task 8              (domain loader — no dependencies on LLM tasks)
Task 9              (intent parser — depends on Task 7+8)
Task 10             (json tests — depends on Task 2)
Task 11             (provider tests — depends on Task 6)
Task 12             (parser tests — depends on Task 9)
```

Parallelizable groups:
- Group A: Task 1 (exceptions) + Task 8 (domain loader) — fully independent
- Group B: Task 2 (json_utils) — after Task 1
- Group C: Tasks 3, 4, 5 (providers) — after Task 2, independent of each other
- Group D: Task 6 (factory) + Task 10 (json tests) — after Group C / Task 2
- Group E: Task 7 (exports) + Task 9 (parser) — after Group D + Task 8
- Group F: Tasks 11, 12 (remaining tests) — after Group E

All 12 tasks are mechanical. Zero decisions remain.
