# Spec: Notion Upload Target Layer

## REQ-NOT-001: UploadTarget ABC
**Given** a developer implementing a new upload target
**When** they subclass `UploadTarget`
**Then** they must implement `upload_paper()`, `check_duplicate()`, and `health_check()` as async methods

**Constraints**:
- `upload_paper(metadata, content)` → `NotionPageInfo`
- `check_duplicate(doi)` → `str | None` (page_id or None)
- `health_check()` → `bool`
- ABC is `@runtime_checkable` Protocol

## REQ-NOT-002: Notion Page Creation
**Given** `PaperMetadata` and `OCRResult`
**When** `upload_paper()` is called
**Then** the adapter:
1. Calls `check_duplicate()` first if DOI is non-empty
2. If duplicate found and `on_duplicate=skip`: returns `NotionPageInfo` with existing page, status=skipped
3. Creates page via `POST https://api.notion.com/v1/pages` with:
   - `parent: { "database_id": config.database_id }`
   - `properties`: mapped from PaperMetadata (see REQ-NOT-003)
   - `children`: first 100 blocks from BlockBuilder output
4. If more than 100 blocks: appends remaining via `PATCH /v1/blocks/{page_id}/children` in batches of 100
5. Returns `NotionPageInfo(page_id, url, title, block_count, created_at)`

**All API calls go through the global rate limiter (REQ-NOT-007)**

## REQ-NOT-003: Property Mapping
**Given** a `PaperMetadata` object
**When** mapping to Notion properties
**Then**:

| Metadata field | Notion property | Notion type | Mapping |
|---------------|----------------|-------------|---------|
| title | 标题 | `title` | `[{"text": {"content": title}}]` |
| authors | 作者 | `rich_text` | `[{"text": {"content": authors}}]` |
| doi | DOI | `url` | DOI string (with https://doi.org/ prefix if bare DOI) |
| venue | 期刊 | `rich_text` | `[{"text": {"content": venue}}]` |
| abstract | 摘要 | `rich_text` | `[{"text": {"content": abstract[:2000]}}]` (truncate to Notion limit) |
| year | 年份 | `number` | integer |
| citation_count | 引用数 | `number` | integer |
| source_url | 来源URL | `url` | URL string |
| tags | 标签 | `multi_select` | `[{"name": tag} for tag in tags]` |
| (default) | 阅读状态 | `select` | `{"name": "未读"}` |
| (default) | OCR状态 | `select` | `{"name": "成功"}` (or "失败" on error) |
| (auto) | 上传时间 | `date` | `{"start": datetime.utcnow().isoformat()}` |

**Constraint**: Empty/None fields are OMITTED (not set to empty string)
**Constraint**: rich_text content truncated at 2000 chars

## REQ-NOT-004: BlockBuilder - Sanitize Phase
**Given** raw markdown from OCR result
**When** sanitizing
**Then**:
1. Normalize to UTF-8 NFC
2. Remove control characters (except newlines, tabs)
3. Fix common OCR markdown artifacts (double spaces, broken headings)
4. Normalize heading levels (ensure consistent hierarchy)

**Invariant (PBT)**: `sanitize(sanitize(text)) == sanitize(text)` (idempotent)

## REQ-NOT-005: BlockBuilder - Convert Phase
**Given** sanitized markdown
**When** converting to Notion blocks
**Then** produce list of Notion block objects:

| Markdown element | Notion block type |
|-----------------|-------------------|
| `# Heading` | `heading_1` |
| `## Heading` | `heading_2` |
| `### Heading` | `heading_3` |
| Paragraph text | `paragraph` |
| `- item` | `bulleted_list_item` |
| `1. item` | `numbered_list_item` |
| `> quote` | `quote` |
| `` ```lang\ncode\n``` `` | `code` (with language) |
| `![alt](url)` | `image` (external URL) |
| `---` | `divider` |
| `\| table \|` | `table` + `table_row` children |
| `$$formula$$` | `equation` |
| Anything else | `paragraph` (fallback) |

**Constraints**:
- Text content > 2000 chars → split into multiple blocks at sentence/word boundary
- rich_text items > 100 → split into multiple blocks
- Nesting limited to 2 levels per request batch
- All block objects validated before returning

**Invariant (PBT)**: For any input markdown, output is always a valid list of Notion block objects (never raises, always falls back to paragraph)

## REQ-NOT-006: Block Chunking
**Given** a list of N Notion blocks
**When** preparing for API submission
**Then**:
1. Split into groups of max 100 blocks each
2. First group goes in `POST /v1/pages` `children`
3. Remaining groups go in sequential `PATCH /v1/blocks/{page_id}/children` calls
4. Each PATCH call waits for rate limiter token

**Invariant (PBT)**: `concat(chunk(blocks, 100)) == blocks` (order preserved, no data loss)

## REQ-NOT-007: Rate Limiter
**Given** Notion API limit of 3 req/s
**When** any Notion API call is made
**Then**:
1. Acquire token from `AsyncTokenBucket(rate=2.5, capacity=3)`
2. If no token available, wait until one is replenished
3. On 429 response: honor `Retry-After` header (or default 1s), wait, retry
4. On retry: re-acquire token

**Invariant (PBT)**: Over any 1-second window, actual request count <= 3

## REQ-NOT-008: Notion Error Mapping
**Given** any HTTP error from Notion API
**When** mapping to domain exceptions
**Then**:
- 400 → `NotionError` (PermanentExternalError) with response body
- 401 → `NotionAuthError` (PermanentExternalError)
- 404 → `NotionNotFoundError` (PermanentExternalError)
- 429 → `NotionRateLimitError` (TransientExternalError) — handled by rate limiter
- 500/502/503 → `TransientExternalError` (retryable with backoff)

**Constraint**: API token NEVER in exception messages or logs

## REQ-NOT-009: Duplicate Check
**Given** a DOI string
**When** `check_duplicate(doi)` is called
**Then**:
1. POST `https://api.notion.com/v1/databases/{database_id}/query` with filter `{ "property": "DOI", "url": { "equals": doi_url } }`
2. If results non-empty: return first result's page_id
3. If empty: return None

**Constraint**: Query goes through rate limiter

## REQ-NOT-010: Notion Data Models
- `PaperMetadata`: title, authors, doi, venue, abstract, year, citation_count, source_url, tags — all optional except title
- `NotionPageInfo`: page_id, url, title, block_count, created_at
- `NotionConfig`: api_token, database_id, version, rate_limit_rps, max_blocks_per_request, max_text_length, on_duplicate
- All are Pydantic `BaseModel`
