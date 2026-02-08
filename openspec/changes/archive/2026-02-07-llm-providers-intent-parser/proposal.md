# Proposal: LLM Multi-Provider Abstraction + Intent Parser

## Summary
Implement 3 LLM providers (OpenAI, Claude, Gemini) conforming to the existing `LLMProvider` ABC, fix factory config wiring, and implement the `IntentParser` skill that converts natural language research queries into structured `ParsedIntent` objects.

## Motivation
Phase 1 delivered a working SerpAPI adapter. Phase 2 adds the AI layer — the ability to understand user intent in natural language (Chinese or English) and extract structured research parameters. This is the prerequisite for Phase 3 (query building) and Phase 4 (workflow orchestration).

## Scope

### In Scope
- OpenAI provider (supports OpenAI-compatible APIs via base_url)
- Claude provider (Anthropic SDK)
- Gemini provider (Google GenAI SDK)
- Factory refactor to pass LLMConfig to providers
- IntentParser skill with domain-specific prompt composition
- Robust JSON extraction from LLM responses
- Tests with mocked LLM responses

### Out of Scope
- Query builder skill (Phase 3)
- Relevance scorer skill (Phase 3)
- Workflow orchestration (Phase 4)
- Streaming/SSE support (not needed for batch processing)
- Provider-level retry logic (caller's responsibility)

## Discovered Constraints

### Hard Constraints (SDK-verified)

| Constraint | Source | Impact |
|------------|--------|--------|
| Anthropic has NO native JSON mode | SDK v0.78.0 | Must use prompt engineering + robust JSON extraction |
| Anthropic `max_tokens` is REQUIRED | SDK API | Cannot omit, must always pass |
| Anthropic system prompt is a separate `system` param, not a message role | SDK API | Different message construction |
| Google GenAI uses camelCase params | SDK v1.62.0 | `maxOutputTokens`, `responseMimeType`, `systemInstruction` |
| Google GenAI JSON mode uses `responseMimeType="application/json"` + `responseSchema` | SDK API | Different JSON enforcement mechanism |
| OpenAI supports `base_url` for compatible APIs | SDK v2.17.0 | Others don't — only OpenAI provider uses this config field |
| Each SDK has different exception hierarchies | All | Need per-provider exception mapping |
| No default model names | User decision | `LLM_MODEL` must be set in .env; empty string = error |

### Soft Constraints (Conventions)

| Constraint | Rationale |
|------------|-----------|
| Providers do NOT retry on rate limits | SRP — matches SerpAPI adapter pattern; caller handles retry |
| Domain selection is fixed at init time via `AppConfig.domain` | Simpler, matches current config design |
| JSON extraction must handle markdown fences and extra text | LLMs often wrap JSON in ```json...``` blocks |
| All providers are async-first | Matches existing codebase pattern |

### SDK API Patterns (Locked)

**OpenAI:**
```python
client = openai.AsyncOpenAI(api_key=..., base_url=...)
response = await client.chat.completions.create(
    model=...,
    messages=[{"role": "system", "content": ...}, {"role": "user", "content": ...}],
    temperature=..., max_tokens=...,
    response_format={"type": "json_object"},  # JSON mode
)
text = response.choices[0].message.content
```

**Anthropic:**
```python
client = anthropic.AsyncAnthropic(api_key=...)
response = await client.messages.create(
    model=...,
    system=system_prompt,  # separate param!
    messages=[{"role": "user", "content": ...}],
    temperature=..., max_tokens=...,  # max_tokens REQUIRED
)
text = response.content[0].text
```

**Google GenAI:**
```python
client = genai.Client(api_key=...)
response = await client.aio.models.generate_content(
    model=model,
    contents=user_message,
    config=types.GenerateContentConfig(
        systemInstruction=system_prompt,
        temperature=..., maxOutputTokens=...,
        responseMimeType="application/json",
        responseSchema=...,
    ),
)
text = response.text
```

## Requirements

### REQ-1: Provider Construction
Each provider accepts `LLMConfig` and validates:
- `api_key` is non-empty (raise ValueError if missing)
- `model` is non-empty (raise ValueError if missing)
- `base_url` is only used by OpenAI provider

### REQ-2: Text Completion
`complete(system_prompt, user_message) -> str` works for all 3 providers.

### REQ-3: JSON Completion
`complete_json(system_prompt, user_message, schema) -> dict`:
- OpenAI: uses `response_format={"type": "json_object"}`
- Claude: appends JSON instruction to system prompt, extracts JSON from response
- Gemini: uses `responseMimeType="application/json"` + `responseSchema`
- All providers: validate response with `json.loads()`, handle extraction failures

### REQ-4: JSON Extraction Robustness
A shared utility that extracts JSON from LLM text:
1. Try `json.loads(text)` directly
2. If fails, try to find ```json...``` markdown block
3. If fails, try to find first `{` and last `}` and parse substring
4. If all fail, raise with raw text for debugging

### REQ-5: Intent Parser
`IntentParser.parse(user_input) -> ParsedIntent`:
- Compose prompt: base INTENT_PARSING_SYSTEM + domain extra_intent_instructions
- Call `llm.complete_json(composed_prompt, user_input, schema=ParsedIntent.model_json_schema())`
- Validate with `ParsedIntent.model_validate(json_dict)`
- Handle: malformed JSON, missing fields, invalid enum values

### REQ-6: Domain Prompt Composition
- Load DomainConfig based on AppConfig.domain string
- If domain == "general": use base prompt only
- If domain == "materials_science": append MATERIALS_SCIENCE.extra_intent_instructions
- Domain config provides concept_categories list for prompt enrichment

### REQ-7: Factory Refactor
`create_provider(config: LLMConfig) -> LLMProvider` passes full config to each provider constructor.

### REQ-8: Error Mapping
Each provider maps SDK-specific exceptions to a common `LLMError` exception:
- Auth errors -> `LLMAuthError`
- Rate limit -> `LLMRateLimitError`
- API errors -> `LLMError`

## Success Criteria

1. `from paper_search.llm import create_provider` works
2. All 3 providers can be constructed with valid config (mocked in tests)
3. `IntentParser.parse("大语言模型在医学影像诊断中的应用")` returns valid `ParsedIntent` (mocked LLM)
4. JSON extraction handles: clean JSON, markdown-fenced JSON, JSON with surrounding text
5. Invalid/missing config raises clear ValueError
6. All tests pass with mocked LLM responses (no real API calls)

## Risks

1. LLM JSON output quality varies — mitigation: robust extraction + Pydantic validation
2. Anthropic no JSON mode — mitigation: strong prompt engineering + extraction fallbacks
3. SDK version changes — mitigation: pin versions in pyproject.toml
4. Mixed language input (Chinese+English) — mitigation: prompt explicitly supports multilingual
