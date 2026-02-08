# Design: LLM Multi-Provider Abstraction + Intent Parser

## Architecture Decision: Per-SDK Native Async Clients

**Choice**: Each provider wraps its SDK's native async client directly. No shared HTTP layer.

**Rationale**:
- Each SDK has fundamentally different APIs (OpenAI chat, Anthropic messages, GenAI generate_content)
- SDKs handle auth, retries, and serialization internally
- Providers are thin adapters: construct client → call API → extract text → return
- JSON mode handled differently per SDK (native vs prompt engineering)

## Locked Constraints

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Provider names | `"openai"`, `"claude"`, `"gemini"` | Match config.provider string |
| Default model | None (empty string = error) | User must set LLM_MODEL explicitly |
| Temperature | From LLMConfig (default 0.0) | Deterministic for intent parsing |
| Max tokens | From LLMConfig (default 4096) | Required by Anthropic, optional for others |
| Retry policy | None in providers | SRP — caller's responsibility (matches Phase 1 pattern) |
| JSON mode: OpenAI | `response_format={"type": "json_object"}` | Native support |
| JSON mode: Claude | Prompt instruction + robust extraction | No native JSON mode in SDK |
| JSON mode: Gemini | `responseMimeType="application/json"` + `responseSchema` | Native support |
| Domain selection | Fixed at IntentParser init via domain string | AppConfig.domain |
| Prompt composition | Base INTENT_PARSING_SYSTEM + domain extra_intent_instructions | Concatenation |

## File Touch List

| File | Change Type | Description |
|------|-------------|-------------|
| `src/paper_search/llm/exceptions.py` | **New** | LLM exception hierarchy |
| `src/paper_search/llm/json_utils.py` | **New** | Shared JSON extraction utility |
| `src/paper_search/llm/openai_provider.py` | **Rewrite** | Full OpenAI implementation |
| `src/paper_search/llm/claude_provider.py` | **Rewrite** | Full Claude implementation |
| `src/paper_search/llm/gemini_provider.py` | **Rewrite** | Full Gemini implementation |
| `src/paper_search/llm/factory.py` | **Rewrite** | Pass LLMConfig to constructors |
| `src/paper_search/llm/__init__.py` | **Modify** | Export create_provider, exceptions |
| `src/paper_search/skills/intent_parser.py` | **Rewrite** | Full implementation |
| `src/paper_search/prompts/domains/__init__.py` | **Modify** | Add get_domain_config() loader |
| `tests/test_llm/__init__.py` | **New** | Test package |
| `tests/test_llm/test_json_utils.py` | **New** | JSON extraction tests |
| `tests/test_llm/test_providers.py` | **New** | Provider unit tests (mocked SDKs) |
| `tests/test_skills/__init__.py` | **New** | Test package |
| `tests/test_skills/test_intent_parser.py` | **New** | Intent parser tests (mocked LLM) |

## Component Design

### Exception Hierarchy

```
class LLMError(Exception): ...
class LLMAuthError(LLMError): ...
class LLMRateLimitError(LLMError): ...
class LLMResponseError(LLMError): ...     # JSON parse failures, empty response
```

### JSON Extraction Utility

```python
def extract_json(text: str) -> dict[str, Any]:
    """Extract JSON from LLM response text. Raises LLMResponseError on failure."""
    # Step 1: Try json.loads(text) directly
    # Step 2: Try regex for ```json\n...\n``` markdown fence
    # Step 3: Try find first '{' and last '}', parse substring
    # Step 4: Raise LLMResponseError with raw text for debugging
```

Regex for step 2: `` r"```(?:json)?\s*\n?(.*?)\n?\s*```" `` with `re.DOTALL`

### OpenAIProvider

```python
class OpenAIProvider(LLMProvider):
    def __init__(self, config: LLMConfig):
        # Validate api_key non-empty, model non-empty
        self._client = openai.AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    async def complete(self, system_prompt, user_message) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.choices[0].message.content or ""

    async def complete_json(self, system_prompt, user_message, schema=None) -> dict:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
            response_format={"type": "json_object"},
        )
        text = response.choices[0].message.content or ""
        return extract_json(text)
```

Exception mapping:
- `openai.AuthenticationError` → `LLMAuthError`
- `openai.RateLimitError` → `LLMRateLimitError`
- `openai.APIError` → `LLMError`

### ClaudeProvider

```python
class ClaudeProvider(LLMProvider):
    def __init__(self, config: LLMConfig):
        # Validate api_key non-empty, model non-empty
        self._client = anthropic.AsyncAnthropic(api_key=config.api_key)
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens  # REQUIRED by Anthropic

    async def complete(self, system_prompt, user_message) -> str:
        response = await self._client.messages.create(
            model=self._model,
            system=system_prompt,  # Separate param, NOT a message
            messages=[{"role": "user", "content": user_message}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        return response.content[0].text

    async def complete_json(self, system_prompt, user_message, schema=None) -> dict:
        json_instruction = "\n\nYou MUST respond with valid JSON only. No markdown, no explanation, no extra text."
        response = await self._client.messages.create(
            model=self._model,
            system=system_prompt + json_instruction,
            messages=[{"role": "user", "content": user_message}],
            temperature=self._temperature,
            max_tokens=self._max_tokens,
        )
        text = response.content[0].text
        return extract_json(text)
```

Exception mapping:
- `anthropic.AuthenticationError` → `LLMAuthError`
- `anthropic.RateLimitError` → `LLMRateLimitError`
- `anthropic.APIError` → `LLMError`

### GeminiProvider

```python
class GeminiProvider(LLMProvider):
    def __init__(self, config: LLMConfig):
        # Validate api_key non-empty, model non-empty
        self._client = genai.Client(api_key=config.api_key)
        self._model = config.model
        self._temperature = config.temperature
        self._max_tokens = config.max_tokens

    async def complete(self, system_prompt, user_message) -> str:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self._temperature,
                max_output_tokens=self._max_tokens,
            ),
        )
        return response.text or ""

    async def complete_json(self, system_prompt, user_message, schema=None) -> dict:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=user_message,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=self._temperature,
                max_output_tokens=self._max_tokens,
                response_mime_type="application/json",
                response_schema=schema,  # Pass Pydantic JSON schema if available
            ),
        )
        text = response.text or ""
        return extract_json(text)
```

Exception mapping:
- `google.genai.errors.ClientError` (status 401/403) → `LLMAuthError`
- `google.genai.errors.ClientError` (status 429) → `LLMRateLimitError`
- `google.genai.errors.APIError` → `LLMError`

### Factory

```python
def create_provider(config: LLMConfig) -> LLMProvider:
    if not config.api_key:
        raise ValueError(f"API key required for provider '{config.provider}'")
    if not config.model:
        raise ValueError(f"Model name required for provider '{config.provider}'")

    match config.provider:
        case "openai":
            from paper_search.llm.openai_provider import OpenAIProvider
            return OpenAIProvider(config)
        case "claude":
            from paper_search.llm.claude_provider import ClaudeProvider
            return ClaudeProvider(config)
        case "gemini":
            from paper_search.llm.gemini_provider import GeminiProvider
            return GeminiProvider(config)
        case _:
            raise ValueError(f"Unknown LLM provider: {config.provider}")
```

### IntentParser

```python
class IntentParser:
    def __init__(self, llm: LLMProvider, domain: str = "general"):
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
```

### Domain Config Loader

```python
# In prompts/domains/__init__.py
def get_domain_config(domain: str) -> DomainConfig | None:
    match domain:
        case "materials_science":
            from paper_search.prompts.domains.materials_science import MATERIALS_SCIENCE
            return MATERIALS_SCIENCE
        case "general" | _:
            return None
```

## PBT Properties

See specs for detailed property-based testing invariants.
