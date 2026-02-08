# Design: SerpAPI Google Scholar Adapter

## Architecture Decision: httpx.AsyncClient (not SDK)

**Choice**: Use `httpx.AsyncClient` to call `https://serpapi.com/search.json` directly.

**Rationale**:
- Matches our async `SearchSource` ABC contract
- Full control over timeout, retry, rate limiting
- `google-search-results` SDK is sync-only; wrapping in `asyncio.to_thread()` adds complexity
- Direct HTTP is simpler to test with response fixtures

## Locked Constraints

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Rate limit | 2 req/sec | User has paid tier |
| Default max results | 20 | Development/testing phase, conserve quota |
| Max retries | 3 | With exponential backoff (base=1s, cap=16s) + jitter |
| Retry on | 429, 500, 503, transport timeout | Never retry 401/403 |
| Results per page | 20 (SerpAPI max) | Single page when max_results <= 20 |
| Partial result policy | Return collected results on mid-pagination error | Don't waste already-fetched data |
| DOI extraction | Regex `10\.\d{4,9}/[^\s]+` from link + snippet | Nullable, best-effort |
| Language mapping | `constraints.language` -> SerpAPI `lr` param (e.g. "en" -> "lang_en") | None = no filter |
| Dedup key precedence | result_id > link > normalized(title+year) | For search_advanced multi-query |

## File Touch List

| File | Change Type | Description |
|------|-------------|-------------|
| `src/paper_search/sources/serpapi_scholar.py` | **Rewrite** | Full implementation |
| `src/paper_search/sources/factory.py` | **Modify** | Pass config to constructor |
| `src/paper_search/sources/base.py` | **Modify** | Add `source_name` property to ABC |
| `src/paper_search/config.py` | **Minor** | Ensure SearchSourceConfig has all needed fields |
| `tests/fixtures/serpapi_response.json` | **New** | Captured real response for testing |
| `tests/test_sources/test_serpapi.py` | **New** | Unit tests |

## Component Design

### SerpAPIScholarSource

```
class SerpAPIScholarSource(SearchSource):
    def __init__(self, api_key, rate_limit_rps=2.0, timeout_s=20.0, max_retries=3, client=None)

    async def search(query, max_results=20, year_from=None, year_to=None, language=None) -> list[RawPaper]
    async def search_advanced(strategy: SearchStrategy) -> list[RawPaper]

    # Internal
    async def _fetch_page(params: dict) -> dict           # Single API call with rate limit + retry
    async def _paginate(base_params, max_results) -> list  # Loop pages until done

    @staticmethod
    def _parse_result(raw: dict) -> RawPaper              # Single result -> RawPaper

    @staticmethod
    def _parse_summary(summary: str) -> tuple[list[Author], int|None, str|None]  # Parse publication_info.summary

    @staticmethod
    def _extract_doi(text: str) -> str|None               # Regex DOI extraction
```

### Summary Parsing Algorithm

Input: `"ZH Zhou, Y Liu - 2021 - Springer"`

1. Split on regex `\s+-\s+` → segments: `["ZH Zhou, Y Liu", "2021", "Springer"]`
2. Find segment matching `^(19|20)\d{2}$` → year = 2021
3. First segment (before year) → comma-split → authors = ["ZH Zhou", "Y Liu"]
4. Remaining segments after year, filter out hostnames (`*.com`, `*.org`, `*.edu`) → venue = "Springer"
5. Edge cases: missing year, single segment, "... - " prefix → graceful degradation to None

### Rate Limiter

```
_lock: asyncio.Lock
_last_request_time: float  # monotonic
_min_interval: float       # 1 / rate_limit_rps = 0.5s

async def _rate_limit():
    async with self._lock:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()
```

### Retry Strategy

```
for attempt in range(max_retries + 1):
    try:
        response = await client.get(url, params=params, timeout=timeout_s)
        if response.status_code == 200:
            data = response.json()
            if data.get("search_metadata", {}).get("status") == "Success":
                return data
            raise SerpAPIError(data.get("error", "Unknown error"))
        if response.status_code in (429, 500, 503):
            raise RetryableError(...)
        raise NonRetryableError(...)  # 401, 403, etc.
    except RetryableError:
        if attempt == max_retries:
            raise
        delay = min(16, (2 ** attempt)) + random.uniform(0, 1)
        await asyncio.sleep(delay)
```

## PBT Properties

See specs for detailed property-based testing invariants.
