# Spec: Intent Parser

## REQ-5: Intent Parsing

**Given** a valid LLM provider (mocked) and user input `"大语言模型在医学影像诊断中的应用"`,
**When** `IntentParser.parse(user_input)` is called,
**Then** returns a `ParsedIntent` with:
- `topic` is non-empty string
- `concepts` is non-empty list of strings
- `intent_type` is a valid `IntentType` enum value
- `constraints` is a `SearchConstraints` instance

**Given** the LLM returns malformed JSON,
**When** `IntentParser.parse(user_input)` is called,
**Then** raises `LLMResponseError` (from extract_json).

**Given** the LLM returns valid JSON but missing required fields,
**When** `IntentParser.parse(user_input)` is called,
**Then** raises `pydantic.ValidationError`.

## REQ-6: Domain Prompt Composition

**Given** `domain="general"`,
**When** `IntentParser._compose_prompt()` is called,
**Then** returns exactly `INTENT_PARSING_SYSTEM` (no extra).

**Given** `domain="materials_science"`,
**When** `IntentParser._compose_prompt()` is called,
**Then** returns `INTENT_PARSING_SYSTEM + "\n\n" + MATERIALS_SCIENCE.extra_intent_instructions`.

**Given** `domain="unknown_domain"`,
**When** `IntentParser._compose_prompt()` is called,
**Then** returns exactly `INTENT_PARSING_SYSTEM` (graceful fallback to general).

## REQ-7: Domain Config Loader

**Given** `domain="materials_science"`,
**When** `get_domain_config(domain)` is called,
**Then** returns the `MATERIALS_SCIENCE` DomainConfig instance.

**Given** `domain="general"`,
**When** `get_domain_config(domain)` is called,
**Then** returns `None`.

---

## PBT Properties

### PROP-7: ParsedIntent Validation
**Invariant**: Any dict that `ParsedIntent.model_validate()` accepts produces an object where `intent_type` is a valid `IntentType` enum member.
**Falsification**: Generate random dicts with valid-ish structures; assert validation either succeeds with valid enum or raises ValidationError.

### PROP-8: Prompt Composition Idempotency
**Invariant**: `_compose_prompt()` returns the same string on repeated calls with the same domain.
**Falsification**: Call `_compose_prompt()` multiple times; assert all results identical.

### PROP-9: Domain Prompt Superset
**Invariant**: For any domain, `_compose_prompt()` output always starts with `INTENT_PARSING_SYSTEM`.
**Falsification**: For each known domain, assert the composed prompt starts with the base prompt.
