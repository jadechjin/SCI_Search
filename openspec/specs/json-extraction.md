# Spec: JSON Extraction Utility

## REQ-4: JSON Extraction Robustness

### Case 1: Clean JSON
**Given** text = `'{"topic": "LLM", "concepts": ["NLP"]}'`,
**When** `extract_json(text)` is called,
**Then** returns `{"topic": "LLM", "concepts": ["NLP"]}`.

### Case 2: Markdown-fenced JSON
**Given** text = `` '```json\n{"topic": "LLM"}\n```' ``,
**When** `extract_json(text)` is called,
**Then** returns `{"topic": "LLM"}`.

### Case 3: Markdown fence without language tag
**Given** text = `` '```\n{"topic": "LLM"}\n```' ``,
**When** `extract_json(text)` is called,
**Then** returns `{"topic": "LLM"}`.

### Case 4: JSON with surrounding text
**Given** text = `'Here is the result:\n{"topic": "LLM"}\nHope this helps!'`,
**When** `extract_json(text)` is called,
**Then** returns `{"topic": "LLM"}`.

### Case 5: No valid JSON
**Given** text = `'I cannot parse this query'`,
**When** `extract_json(text)` is called,
**Then** raises `LLMResponseError` with the raw text in the message.

### Case 6: Empty string
**Given** text = `''`,
**When** `extract_json(text)` is called,
**Then** raises `LLMResponseError`.

### Case 7: Nested JSON in markdown
**Given** text = `` '```json\n{"topic": "LLM", "constraints": {"year_from": 2020}}\n```' ``,
**When** `extract_json(text)` is called,
**Then** returns `{"topic": "LLM", "constraints": {"year_from": 2020}}` (nested structure preserved).

---

## PBT Properties

### PROP-4: Idempotent Extraction
**Invariant**: `extract_json(json.dumps(d)) == d` for any valid dict `d`.
**Falsification**: Generate random dicts with string/int/list/dict values; assert round-trip.

### PROP-5: Markdown Fence Transparency
**Invariant**: `extract_json('```json\n' + json.dumps(d) + '\n```') == d` for any valid dict `d`.
**Falsification**: Wrap random valid JSON in markdown fences; assert extraction matches.

### PROP-6: Extraction Priority
**Invariant**: Direct parse is tried first; only falls through to regex if direct fails.
**Falsification**: Valid JSON string should return immediately without regex search.
