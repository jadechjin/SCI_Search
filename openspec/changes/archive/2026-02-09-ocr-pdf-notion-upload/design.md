# Design: OCR PDF + Notion Upload

## Technical Decisions (Zero-Ambiguity)

### D-1: Architecture Pattern
**Decision**: Skills Extension with ABC + Factory
- `OCRProvider` ABC in `src/paper_search/ocr/base.py`
- `UploadTarget` ABC in `src/paper_search/targets/base.py`
- Factory functions in `ocr/factory.py` and `targets/factory.py`
- Matches existing `SearchSource` ABC / `LLMProvider` ABC / `create_provider()` pattern

### D-2: HTTP Client
**Decision**: Raw `httpx.AsyncClient` for both MinerU and Notion
- Consistent with existing codebase (SerpAPI adapter uses httpx)
- No `mineru-kie-sdk` (sync-only, KIE-specific, uses `requests`)
- No `notion-client` SDK (narrow scope, raw httpx gives precise control + unified retry)
- Single `AsyncClient` instance per adapter, pooled

### D-3: Exception Hierarchy
**Decision**: Shared transport error types, NOT reusing SerpAPI exceptions
```
paper_search/
├── exceptions.py  (NEW - shared base)
│   ├── TransientExternalError    # retryable (429, 500, 503, timeout)
│   └── PermanentExternalError    # non-retryable (401, 403, 404, bad input)
├── ocr/exceptions.py
│   ├── OCRError(TransientExternalError | PermanentExternalError)
│   ├── OCRAuthError(PermanentExternalError)
│   ├── OCRTimeoutError(TransientExternalError)
│   ├── OCRTaskFailedError(PermanentExternalError)
│   └── OCRFileError(PermanentExternalError)
└── targets/exceptions.py
    ├── NotionError(TransientExternalError | PermanentExternalError)
    ├── NotionAuthError(PermanentExternalError)
    ├── NotionRateLimitError(TransientExternalError)
    └── NotionNotFoundError(PermanentExternalError)
```

### D-4: MinerU Dual-Mode Adapter
**Decision**: Single `MineruAdapter` class with two code paths converging to shared poll→download→parse
```
submit_url(url, options) ────────────────┐
                                         ├─→ _poll_task(task_id)
submit_file(path, options) ──────────────┘        │
  (batch API: request URLs → PUT upload)          ▼
                                          _download_zip(full_zip_url)
                                                  │
                                                  ▼
                                          _parse_zip(zip_bytes) → OCRResult
```
- State machine: `submitted → polling → downloading → parsing → done | failed`
- Exponential backoff: `min(60, 2^attempt) + jitter`, ceiling 60s, wall-clock timeout configurable
- Persisted state: `task_id`, `data_id` for resumability

### D-5: Notion Rate Limiter
**Decision**: Global async token bucket, 2.5 req/s (conservative under 3 req/s limit)
- Single `AsyncTokenBucket` instance shared across all Notion operations
- Honor `Retry-After` header on 429 responses
- All Notion API calls go through the limiter

### D-6: BlockBuilder Two-Phase Conversion
**Decision**: Sanitize → Convert (two-phase)
- **Phase 1 (sanitize)**: Normalize OCR markdown, fix malformed syntax, remove control chars, normalize UTF-8 NFC
- **Phase 2 (convert)**: Clean markdown → Notion block objects with strict validators
- **Fallback**: Unknown/malformed elements → `paragraph` block (lossy but valid)
- **Chunking rules** (enforced in request packer):
  - Max 100 blocks per PATCH request
  - Max 2000 characters per `text.content`
  - Max 100 items per `rich_text` array
  - Max 2 nesting levels per request

### D-7: Web Server
**Decision**: Separate entry point from MCP server
- `python -m paper_search.web` — starts FastAPI server for drag-and-drop UI
- `python -m paper_search` — existing CLI
- MCP server via `mcp run` — existing MCP entry point
- All three share core libraries (`ocr/`, `targets/`, `skills/`)
- No ASGI conflict — independent processes

### D-8: Progress Feedback
**Decision**: Polling-based (SSE optional future)
- `POST /api/upload` returns `{ job_id }` immediately
- `GET /api/jobs/{job_id}` returns `{ status, stage, progress, papers: [...] }`
- Stages: `uploading → ocr_processing → formatting → uploading_to_notion → done | failed`
- Frontend polls every 2 seconds
- SSE is a future enhancement, not Phase 1

### D-9: Concurrency Control
**Decision**: Bounded async semaphores per external service
- MinerU: `asyncio.Semaphore(5)` — max 5 concurrent OCR tasks
- Notion: Global token bucket (2.5 req/s) + `asyncio.Semaphore(3)` per batch job
- In-process job queue with bounded workers (no external queue service needed)

### D-10: Image Handling
**Decision**: Use MinerU CDN URLs directly in Notion `image` blocks
- MinerU ZIP contains images at CDN URLs
- These URLs expire in 30 days
- Known limitation: document in README, images may break after 30 days
- Future improvement: re-upload images to Notion or external storage

### D-11: Deduplicate on Upload
**Decision**: Pre-check DOI before creating Notion page
- Before creating a page, query Notion database for existing DOI
- If exists, skip or update (configurable via `on_duplicate: skip | update | create`)
- Default: `skip` with warning in ProcessingReport

### D-12: Configuration Structure
**Decision**: Extend AppConfig with nested Pydantic models
```python
class OCRConfig(BaseModel):
    provider: str = "mineru"
    api_token: str = ""
    model_version: str = "vlm"     # pipeline | vlm | MinerU-HTML
    is_ocr: bool = True
    enable_formula: bool = True
    enable_table: bool = True
    language: str = "en"
    timeout_s: int = 300
    poll_interval_s: int = 5
    max_concurrent: int = 5

class NotionConfig(BaseModel):
    api_token: str = ""
    database_id: str = ""
    version: str = "2025-09-03"
    rate_limit_rps: float = 2.5
    max_blocks_per_request: int = 100
    max_text_length: int = 2000
    on_duplicate: str = "skip"     # skip | update | create

class WebConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8080
    max_upload_size_mb: int = 200
```
Loaded from `.env` via `load_config()` extension.

### D-13: Dependencies
```toml
[project.optional-dependencies]
ocr-notion = [
    "fastapi>=0.115,<1.0",
    "uvicorn[standard]>=0.31.1",
    "python-multipart>=0.0.9",
]
```
No new core dependencies. httpx already present.

---

## Module Architecture (Final)

```
src/paper_search/
├── exceptions.py              # NEW: shared TransientExternalError / PermanentExternalError
├── ocr/
│   ├── __init__.py
│   ├── base.py                # OCRProvider ABC
│   ├── factory.py             # create_ocr_provider(config) → OCRProvider
│   ├── mineru_adapter.py      # MineruAdapter: dual-mode (URL + file upload)
│   ├── models.py              # OCROptions, OCRResult, OCRTaskStatus
│   └── exceptions.py          # OCRError hierarchy
├── targets/
│   ├── __init__.py
│   ├── base.py                # UploadTarget ABC
│   ├── factory.py             # create_upload_target(config) → UploadTarget
│   ├── notion_adapter.py      # NotionAdapter: page creation + block append
│   ├── block_builder.py       # Two-phase: sanitize → convert markdown → Notion blocks
│   ├── rate_limiter.py        # AsyncTokenBucket for Notion rate limiting
│   ├── models.py              # NotionPageInfo, PaperMetadata
│   └── exceptions.py          # NotionError hierarchy
├── skills/
│   ├── ocr_processor.py       # OCRProcessor skill (uses OCRProvider)
│   └── content_uploader.py    # ContentUploader skill (uses UploadTarget)
├── web/
│   ├── __init__.py
│   ├── app.py                 # FastAPI app factory
│   ├── routes.py              # /api/upload, /api/jobs/{id}, /api/health
│   ├── job_manager.py         # In-process job queue + status tracking
│   ├── static/
│   │   ├── index.html         # Drag-and-drop upload page
│   │   ├── style.css
│   │   └── upload.js          # Upload logic + polling
│   └── __main__.py            # Entry point: python -m paper_search.web
├── config.py                  # Extended: +OCRConfig, +NotionConfig, +WebConfig
└── models.py                  # Extended: +OCRResult, +NotionPageInfo, +ProcessingReport
```

---

## Data Models (New/Extended)

### OCRResult
```python
class OCRSection(BaseModel):
    heading: str
    level: int  # 1, 2, 3
    content: str  # markdown content of section

class OCRImage(BaseModel):
    url: str
    alt_text: str = ""
    caption: str = ""

class OCRTable(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    caption: str = ""

class OCRResult(BaseModel):
    task_id: str
    markdown: str                  # full raw markdown
    sections: list[OCRSection]     # parsed sections
    images: list[OCRImage]         # extracted image URLs
    tables: list[OCRTable]         # extracted tables
    metadata: dict[str, Any] = {}  # any extra metadata from MinerU
```

### PaperMetadata
```python
class PaperMetadata(BaseModel):
    title: str
    authors: str = ""
    doi: str = ""
    venue: str = ""
    abstract: str = ""
    year: int | None = None
    citation_count: int | None = None
    source_url: str = ""
    tags: list[str] = []
```

### NotionPageInfo
```python
class NotionPageInfo(BaseModel):
    page_id: str
    url: str
    title: str
    block_count: int
    created_at: str  # ISO 8601
```

### ProcessingReport
```python
class PaperProcessingResult(BaseModel):
    filename: str
    status: str          # success | failed | skipped
    ocr_task_id: str = ""
    notion_page_url: str = ""
    error: str = ""
    stage: str = ""      # where it failed

class ProcessingReport(BaseModel):
    job_id: str
    total: int
    succeeded: int
    failed: int
    skipped: int
    results: list[PaperProcessingResult]
```

---

## API Contracts

### OCRProvider ABC
```python
class OCRProvider(ABC):
    @abstractmethod
    async def ocr_from_url(self, url: str, options: OCROptions | None = None) -> OCRResult:
        """Submit URL for OCR, poll, download, parse. Returns structured result."""

    @abstractmethod
    async def ocr_from_file(self, file_path: Path, options: OCROptions | None = None) -> OCRResult:
        """Upload local file, submit for OCR, poll, download, parse."""

    @abstractmethod
    async def get_task_status(self, task_id: str) -> OCRTaskStatus:
        """Check current status of an OCR task."""
```

### UploadTarget ABC
```python
class UploadTarget(ABC):
    @abstractmethod
    async def upload_paper(self, metadata: PaperMetadata, content: OCRResult) -> NotionPageInfo:
        """Create page with metadata properties + content blocks."""

    @abstractmethod
    async def check_duplicate(self, doi: str) -> str | None:
        """Check if DOI exists. Returns page_id if found, None otherwise."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify target is accessible and database exists."""
```

### Web API
```
POST /api/upload
  Content-Type: multipart/form-data
  Body: files[]=@paper.pdf, metadata={"title": "...", "doi": "..."}
  Response 202: { "job_id": "uuid" }

GET /api/jobs/{job_id}
  Response 200: {
    "job_id": "uuid",
    "status": "processing",
    "stage": "ocr_processing",
    "progress": { "current": 1, "total": 3 },
    "results": [
      { "filename": "paper1.pdf", "status": "success", "notion_page_url": "..." },
      { "filename": "paper2.pdf", "status": "processing", "stage": "ocr_processing" },
      { "filename": "paper3.pdf", "status": "pending" }
    ]
  }

GET /api/health
  Response 200: { "mineru": true, "notion": true }

GET /
  Serves static/index.html (drag-and-drop upload page)
```

---

## PBT Properties (Invariants)

### P-1: Block Chunking Correctness
- **Invariant**: For any list of N blocks, chunking into groups of max 100 produces ceil(N/100) groups, each with <= 100 blocks, and concatenating all groups == original list
- **Falsification**: Generate random block counts 1-5000, verify chunk sizes and order preservation

### P-2: Text Splitting Preserves Content
- **Invariant**: For any string S, splitting at 2000-char boundaries and joining produces S (no data loss)
- **Falsification**: Generate random Unicode strings 1-10000 chars, verify round-trip

### P-3: Rate Limiter Token Bucket
- **Invariant**: Over any 1-second window, at most ceil(rate_limit_rps) tokens are consumed
- **Falsification**: Rapid-fire N requests, measure actual throughput, verify <= rate

### P-4: Sanitizer Idempotency
- **Invariant**: sanitize(sanitize(text)) == sanitize(text)
- **Falsification**: Generate random markdown with special chars, verify double-sanitize stability

### P-5: OCR Dual-Mode Convergence
- **Invariant**: For the same PDF, ocr_from_url() and ocr_from_file() produce equivalent OCRResult.markdown (modulo timing metadata)
- **Falsification**: Mock MinerU returning same ZIP for both modes, verify OCRResult equality

### P-6: Notion Page Completeness
- **Invariant**: After upload, page property count == len(non-empty metadata fields) and block count == expected block count from BlockBuilder output
- **Falsification**: Generate metadata with random empty/filled fields, verify only non-empty appear as properties

### P-7: Partial Failure Isolation
- **Invariant**: If paper K fails during batch of N, papers 1..K-1 and K+1..N are still processed correctly
- **Falsification**: Inject random failures at different positions in batch, verify other papers succeed

### P-8: Deduplication Correctness
- **Invariant**: Uploading the same DOI twice with on_duplicate=skip results in exactly 1 Notion page
- **Falsification**: Upload same DOI N times concurrently, verify page count == 1

---

## Sequence Diagrams

### Single File Upload (Local PDF)
```
User        Web          FastAPI      MineruAdapter    Notion
 │─drag PDF──▶│            │              │              │
 │            │─POST /upload─▶│            │              │
 │            │   202 {job_id}◄─│          │              │
 │            │─poll /jobs/{id}─▶│         │              │
 │            │              │─ocr_from_file()─▶│         │
 │            │              │    POST /file-urls/batch──▶│MinerU
 │            │              │    PUT pre_signed_url─────▶│MinerU
 │            │              │    GET /task/{id} (poll)──▶│MinerU
 │            │              │    ◄──state:done, zip_url──│MinerU
 │            │              │    download + parse ZIP     │
 │            │              │◄──OCRResult─────────────────│
 │            │              │─upload_paper()──────────────────────▶│
 │            │              │    check_duplicate(doi)──────────────▶│
 │            │              │    POST /v1/pages────────────────────▶│
 │            │              │    PATCH blocks (batch 1)────────────▶│
 │            │              │    PATCH blocks (batch 2)────────────▶│
 │            │              │◄──NotionPageInfo─────────────────────│
 │            │◄──job status: done──│                               │
 │◄──display result──│               │                               │
```

---

## Risk Mitigations

| Risk | Mitigation | Monitoring |
|------|-----------|------------|
| MinerU task hangs | Wall-clock timeout (configurable), exponential backoff ceiling 60s | Log poll count + elapsed time |
| Notion 429 storm | Global token bucket 2.5 req/s, honor Retry-After | Log 429 count per batch |
| Malformed OCR markdown | Two-phase sanitize→convert, fallback to paragraph | Log fallback count |
| Large PDF (>100 pages) | Works normally (just more blocks/API calls) | Log block count per paper |
| Network interruption | Resumable state: page created first with OCR状态=处理中, blocks appended incrementally | Log partial upload state |
| Image URL expiry (30d) | Document as known limitation | N/A for now |
| Concurrent same-DOI | Pre-create dedupe query | Log skip count |
