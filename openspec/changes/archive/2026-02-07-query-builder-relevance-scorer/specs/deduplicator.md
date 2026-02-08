# Spec: Deduplicator

## REQ-10: Algorithm Pass — DOI Matching

**Given** papers A (doi="10.1234/a") and B (doi="10.1234/A"),
**When** `deduplicate([A, B])` is called,
**Then** returns 1 paper (merged).

## REQ-11: Algorithm Pass — Source ID Matching

**Given** papers A and B with same `raw_data["result_id"]` but different UUIDs,
**When** `deduplicate([A, B])` is called,
**Then** returns 1 paper.

## REQ-12: Algorithm Pass — URL Matching

**Given** papers A (full_text_url="https://example.com/paper1") and B (full_text_url="https://example.com/paper1"),
**When** `deduplicate([A, B])` is called,
**Then** returns 1 paper.

## REQ-13: Algorithm Pass — Exact Normalized Title

**Given** paper A (title="  Effect of Temperature on Steel  ") and B (title="effect of temperature on steel"),
**When** `deduplicate([A, B])` is called,
**Then** returns 1 paper (case-insensitive, whitespace-normalized).

## REQ-14: LLM Pass — Semantic Duplicate Detection

**Given** paper A (title="Impact of LLM on Radiology", year=2023) and B (title="Large Language Models in Radiological Diagnosis", year=2023),
**And** an LLM that correctly identifies them as duplicates,
**When** `deduplicate([A, B])` is called with LLM enabled,
**Then** returns 1 paper (merged).

## REQ-15: LLM Failure Graceful Degradation

**Given** papers that are semantic duplicates but LLM fails,
**When** `deduplicate()` is called,
**Then** returns all papers (no dedup from LLM pass, algorithm pass still applied).

## REQ-16: Merge Strategy — Richest Record Wins

**Given** paper A (doi=None, snippet="short") and paper B (doi="10.1234/x", snippet="much longer snippet with more detail"),
**When** merged,
**Then** result has doi="10.1234/x" and the longer snippet.
**And** citation_count = max(A.citation_count, B.citation_count).

## REQ-17: Empty and Single Input

**Given** empty list or single paper,
**When** `deduplicate()` is called,
**Then** returns input unchanged.

## REQ-18: No LLM Mode

**Given** `Deduplicator(llm=None)`,
**When** `deduplicate()` is called,
**Then** only algorithm pass runs, no LLM call.

---

## PBT Properties

### PROP-7: Dedup Monotonicity
**Invariant**: `len(deduplicate(papers)) <= len(papers)`.
**Falsification**: Generate random paper lists; assert output length never exceeds input.

### PROP-8: Title Normalization Idempotency
**Invariant**: `normalize(normalize(t)) == normalize(t)` for any title string.
**Falsification**: Generate random Unicode strings; assert double-normalization equals single.

### PROP-9: Merge Preserves Best Data
**Invariant**: For any merged group, the result has `citation_count >= max(group.citation_counts)`.
**Falsification**: Generate groups with varied citation counts; assert max is preserved.

### PROP-10: No Data Loss
**Invariant**: Every input paper's title appears either in output directly or was merged into an output paper whose raw_data contains reference to it.
**Falsification**: Generate varied paper lists; verify coverage.

### PROP-11: Deterministic Algorithm Pass
**Invariant**: Algorithm pass with same input always produces same groups.
**Falsification**: Run algorithm pass multiple times; assert identical output.
