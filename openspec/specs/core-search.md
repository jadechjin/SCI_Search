# Spec: SerpAPI Adapter — Core Search

## REQ-1: Basic Search

**Given** a valid API key and query string,
**When** `search(query)` is called,
**Then** returns `list[RawPaper]` where every item has:
- `title` is non-empty string
- `source == "serpapi_scholar"`
- `raw_data` contains the original API response dict
- `id` is a valid UUID string

## REQ-2: Pagination

**Given** `max_results > 20`,
**When** search is executed,
**Then** multiple pages are fetched (incrementing `start` by 20 each time)
**And** total results returned is `<= max_results`
**And** no duplicate `raw_data.result_id` exists in output

## REQ-3: Year Filtering

**Given** `year_from=2020` and/or `year_to=2024`,
**When** search is executed,
**Then** SerpAPI params include `as_ylo=2020` and/or `as_yhi=2024`

## REQ-4: Partial Result on Error

**Given** page 1 succeeds but page 2 fails with 500,
**When** search with `max_results=40`,
**Then** returns the papers from page 1 (not empty list, not exception)

## REQ-5: Empty Results

**Given** a query that returns no results,
**When** search is executed,
**Then** returns empty `list[RawPaper]` (no exception)

---

## PBT Properties

### PROP-1: Source Invariant
**Invariant**: For all papers returned by SerpAPIScholarSource, `paper.source == "serpapi_scholar"`
**Falsification**: Generate random queries; assert all results have correct source tag.

### PROP-2: ID Uniqueness
**Invariant**: All papers in a single search result have unique `id` values.
**Falsification**: Run search with max_results=20; assert `len(set(ids)) == len(ids)`.

### PROP-3: Result Count Bound
**Invariant**: `len(results) <= max_results` for any search call.
**Falsification**: For random max_results in [1, 100], assert bound holds.

### PROP-4: Idempotent Parsing
**Invariant**: `_parse_result(raw_dict)` called twice with same input returns identical `RawPaper`.
**Falsification**: Generate varied raw dicts; assert parse is deterministic.

### PROP-5: Year Extraction Monotonicity
**Invariant**: If `_parse_summary` extracts a year, it is in range [1900, current_year+1].
**Falsification**: Generate random summary strings with embedded numbers; assert year bounds.
