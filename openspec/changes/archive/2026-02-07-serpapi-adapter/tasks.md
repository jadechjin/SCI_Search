# Tasks: SerpAPI Google Scholar Adapter

All decisions are locked in `design.md`. Each task below is pure mechanical execution — zero decisions needed.

---

## Task 1: Add custom exceptions [DONE]

**File**: `src/paper_search/sources/exceptions.py` (NEW)

Create:
```python
class SearchSourceError(Exception): ...
class SerpAPIError(SearchSourceError): ...
class RetryableError(SerpAPIError): ...
class NonRetryableError(SerpAPIError): ...
```

**Verify**: `from paper_search.sources.exceptions import SerpAPIError` imports without error.

---

## Task 2: Update SearchSource ABC — add source_name property [DONE]

**File**: `src/paper_search/sources/base.py` (MODIFY)

Add abstract property:
```python
@property
@abstractmethod
def source_name(self) -> str: ...
```

Add optional `client` param documentation note.

**Verify**: Existing imports still work.

---

## Task 3: Implement summary parser — `_parse_summary` static method [DONE]

**File**: `src/paper_search/sources/serpapi_scholar.py` (MODIFY)

Implement `_parse_summary(summary: str) -> tuple[list[Author], int | None, str | None]`:

1. Split `summary` on regex `\s+-\s+` into segments
2. Find first segment matching `^(19|20)\d{2}$` → year (int)
3. Everything before year segment → comma-split → `Author(name=segment.strip())`, filter empty
4. Everything after year segment → filter hostnames (contains `.com`, `.org`, `.edu`, `.net`) → join remaining as venue
5. If no year found: first segment = authors, last segment = venue (if not hostname), year = None
6. Never raise; return `([], None, None)` on total parse failure

**Verify**: Test with these exact inputs:
- `"ZH Zhou, Y Liu - 2021 - Springer"` → `(["ZH Zhou", "Y Liu"], 2021, "Springer")`
- `"2021 - books.google.com"` → `([], 2021, None)`
- `"A Smith - Nature"` → `(["A Smith"], None, "Nature")`
- `""` → `([], None, None)`

---

## Task 4: Implement DOI extractor — `_extract_doi` static method [DONE]

**File**: `src/paper_search/sources/serpapi_scholar.py` (MODIFY)

Implement `_extract_doi(text: str) -> str | None`:

1. Regex: `r'10\.\d{4,9}/[^\s,;)}\]>]+`
2. Search across input text
3. Strip trailing punctuation `.,;:)`
4. Return first match or None

**Verify**: Test with:
- `"https://doi.org/10.1234/test.2024"` → `"10.1234/test.2024"`
- `"no doi here"` → `None`
- `"see 10.1038/s41586-024-07386-0, for details"` → `"10.1038/s41586-024-07386-0"`

---

## Task 5: Implement result parser — `_parse_result` static method [DONE]

**File**: `src/paper_search/sources/serpapi_scholar.py` (MODIFY)

Implement `_parse_result(raw: dict) -> RawPaper`:

Mapping:
- `title` ← `raw["title"]`
- `snippet` ← `raw.get("snippet")`
- `abstract` ← `None`
- `citation_count` ← `raw.get("inline_links", {}).get("cited_by", {}).get("total", 0)`
- `full_text_url` ← first resource with `file_format == "PDF"` link, else `raw.get("link")`
- `source` ← `"serpapi_scholar"`
- `raw_data` ← `raw`
- authors, year, venue ← `_parse_summary(raw.get("publication_info", {}).get("summary", ""))`
- `doi` ← `_extract_doi(raw.get("link", "") + " " + raw.get("snippet", ""))`

**Verify**: Parse a captured real SerpAPI result dict; assert all fields populated correctly.

---

## Task 6: Implement rate limiter [DONE]

**File**: `src/paper_search/sources/serpapi_scholar.py` (MODIFY)

In `__init__`:
- `self._lock = asyncio.Lock()`
- `self._last_request_time = 0.0`
- `self._min_interval = 1.0 / rate_limit_rps`

Method `async _rate_limit()`:
```python
async with self._lock:
    elapsed = time.monotonic() - self._last_request_time
    if elapsed < self._min_interval:
        await asyncio.sleep(self._min_interval - elapsed)
    self._last_request_time = time.monotonic()
```

**Verify**: Two rapid calls; assert >= min_interval between them.

---

## Task 7: Implement `_fetch_page` — single API call with retry [DONE]

**File**: `src/paper_search/sources/serpapi_scholar.py` (MODIFY)

Implement `async _fetch_page(params: dict) -> dict`:

1. Call `self._rate_limit()`
2. Loop `max_retries + 1` times:
   a. `response = await self._client.get("https://serpapi.com/search.json", params=params, timeout=self._timeout_s)`
   b. If 200 and `search_metadata.status == "Success"`: return response data
   c. If 200 but error: raise `SerpAPIError(data["error"])`
   d. If 429/500/503: if last attempt raise, else sleep `min(16, 2**attempt) + random.uniform(0, 1)`
   e. If 401/403: raise `NonRetryableError`
   f. On `httpx.TimeoutException`: treat as retryable

**Verify**: Mock httpx to return 429 twice then 200; assert 3 attempts total, returns data.

---

## Task 8: Implement `search()` with pagination [DONE]

**File**: `src/paper_search/sources/serpapi_scholar.py` (MODIFY)

Implement `async search(query, max_results=20, year_from=None, year_to=None, language=None) -> list[RawPaper]`:

1. Build base params: `engine=google_scholar`, `q=query`, `api_key`, `num=min(20, max_results)`
2. If year_from: `as_ylo=year_from`; if year_to: `as_yhi=year_to`
3. If language: `lr=f"lang_{language}"`
4. Loop:
   a. `data = await self._fetch_page({**base_params, start=offset})`
   b. Parse `data.get("organic_results", [])` via `_parse_result`
   c. Append to results, increment offset
   d. Stop if: no organic_results, or len(results) >= max_results
   e. On error mid-pagination: return results collected so far
5. Trim to max_results

**Verify**: Mock 2-page response; assert correct pagination and result count.

---

## Task 9: Implement `search_advanced()` [DONE]

**File**: `src/paper_search/sources/serpapi_scholar.py` (MODIFY)

Implement `async search_advanced(strategy: SearchStrategy) -> list[RawPaper]`:

1. Budget: `per_query = max(1, strategy.filters.max_results // len(strategy.queries))`
2. For each query in strategy.queries:
   a. `results += await self.search(query.boolean_query, max_results=per_query, ...filters)`
3. Dedupe by: `result_id` (from raw_data) → `full_text_url` → `title.lower().strip() + str(year)`
4. Return deduped list

**Verify**: Two queries with overlapping results; assert dedup works.

---

## Task 10: Update factory to pass config [DONE]

**File**: `src/paper_search/sources/factory.py` (MODIFY)

Change `create_source(config: SearchSourceConfig) -> SearchSource`:
```python
case "serpapi_scholar":
    return SerpAPIScholarSource(
        api_key=config.api_key,
        rate_limit_rps=config.rate_limit,
    )
```

**Verify**: `create_source(config)` returns configured instance.

---

## Task 11: Create test fixture — captured SerpAPI response [DONE]

**File**: `tests/fixtures/serpapi_response.json` (NEW)

Capture a real SerpAPI Google Scholar response for query "large language model" with 3-5 results. Alternatively, construct a realistic fixture matching the documented response format.

Must include: organic_results with varied publication_info.summary formats, inline_links, snippets.

---

## Task 12: Write unit tests [DONE]

**File**: `tests/test_sources/__init__.py` (NEW, empty)
**File**: `tests/test_sources/test_serpapi.py` (NEW)

Tests (all using fixtures/mocks, no live API calls):
1. `test_parse_summary_standard` — "Author1, Author2 - 2021 - Journal"
2. `test_parse_summary_no_year` — "Author - Journal"
3. `test_parse_summary_hostname_venue` — "Author - 2021 - books.google.com"
4. `test_parse_summary_empty` — ""
5. `test_extract_doi_from_url` — doi.org URL
6. `test_extract_doi_none` — no DOI
7. `test_parse_result_full` — complete result dict
8. `test_parse_result_minimal` — missing optional fields
9. `test_search_pagination` — mock 2 pages, assert correct count
10. `test_search_empty_results` — mock empty response
11. `test_search_partial_on_error` — mock page 1 OK, page 2 error
12. `test_retry_on_429` — mock 429 then 200
13. `test_no_retry_on_401` — mock 401, assert immediate raise
14. `test_rate_limiting` — rapid calls, assert timing gap

**Verify**: `pytest tests/test_sources/ -v` all pass.

---

## Execution Order

```
Task 1  → Task 2  (foundations, no dependencies on each other, can be parallel)
Task 3  → Task 4  → Task 5  (parsing chain, each builds on prior)
Task 6  → Task 7  (rate limit before fetch)
Task 8  → Task 9  (search before search_advanced)
Task 10 (factory, after Task 8)
Task 11 → Task 12 (fixture before tests)
```

All 12 tasks are mechanical. Zero decisions remain.
