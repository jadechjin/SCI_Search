# Spec: LLM Providers

## REQ-1: Provider Construction Validation

**Given** a `LLMConfig` with empty `api_key`,
**When** `create_provider(config)` is called,
**Then** raises `ValueError` with message containing "API key required".

**Given** a `LLMConfig` with empty `model`,
**When** `create_provider(config)` is called,
**Then** raises `ValueError` with message containing "Model name required".

**Given** a `LLMConfig` with valid `api_key`, `model`, and `provider="openai"`,
**When** `create_provider(config)` is called,
**Then** returns an `OpenAIProvider` instance.

(Same for `"claude"` → `ClaudeProvider`, `"gemini"` → `GeminiProvider`)

**Given** `provider="unknown"`,
**When** `create_provider(config)` is called,
**Then** raises `ValueError` with message containing "Unknown LLM provider".

## REQ-2: Text Completion

**Given** a valid provider instance (mocked SDK client),
**When** `complete(system_prompt, user_message)` is called,
**Then** returns a `str` (the LLM's text response).

**Invariants**:
- Return type is always `str`
- Empty response from SDK → return `""` (not None, not exception)

### OpenAI-specific:
- SDK receives `messages=[{"role": "system", ...}, {"role": "user", ...}]`
- SDK receives `model`, `temperature`, `max_tokens` from config

### Claude-specific:
- SDK receives `system=system_prompt` as separate param (NOT in messages)
- SDK receives `messages=[{"role": "user", ...}]` (no system message)
- SDK always receives `max_tokens` (required)

### Gemini-specific:
- SDK receives `contents=user_message` (not messages array)
- SDK receives `config=GenerateContentConfig(system_instruction=system_prompt, ...)`
- Uses `max_output_tokens` (camelCase in config object)

## REQ-3: JSON Completion

**Given** a valid provider instance (mocked SDK),
**When** `complete_json(system_prompt, user_message, schema)` is called,
**Then** returns a `dict` (parsed JSON from LLM response).

### OpenAI-specific:
- SDK receives `response_format={"type": "json_object"}`

### Claude-specific:
- SDK receives `system=system_prompt + json_instruction` (appended instruction)
- JSON instruction: `"\n\nYou MUST respond with valid JSON only. No markdown, no explanation, no extra text."`

### Gemini-specific:
- SDK receives `response_mime_type="application/json"` in config
- SDK receives `response_schema=schema` in config (if provided)

## REQ-8: Error Mapping

**Given** an SDK raises an authentication error,
**When** `complete()` or `complete_json()` is called,
**Then** raises `LLMAuthError` (not SDK-specific exception).

**Given** an SDK raises a rate limit error,
**When** `complete()` or `complete_json()` is called,
**Then** raises `LLMRateLimitError`.

**Given** an SDK raises a generic API error,
**When** `complete()` or `complete_json()` is called,
**Then** raises `LLMError`.

---

## PBT Properties

### PROP-1: Provider Type Correctness
**Invariant**: `create_provider(config)` returns an instance of the correct provider class for each known provider string.
**Falsification**: For each of ["openai", "claude", "gemini"], assert `isinstance(result, expected_class)`.

### PROP-2: Config Propagation
**Invariant**: Provider stores model, temperature, max_tokens from config.
**Falsification**: Construct provider with various configs; assert attributes match.

### PROP-3: Return Type Stability
**Invariant**: `complete()` always returns `str`, `complete_json()` always returns `dict`.
**Falsification**: Mock various SDK responses (empty, whitespace, valid); assert return types.
