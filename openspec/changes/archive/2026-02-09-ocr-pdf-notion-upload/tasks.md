# Tasks: OCR PDF + Notion Upload

## Phase 1: Foundation + OCR Provider Layer

### Task 1.1: Shared Exception Base
- [x] Create `src/paper_search/exceptions.py`
  - `ExternalServiceError(Exception)` base class
  - `TransientExternalError(ExternalServiceError)` — retryable
  - `PermanentExternalError(ExternalServiceError)` — non-retryable
- [x] Test: `tests/test_exceptions.py` — verify hierarchy and isinstance checks
- **Refs**: REQ-CFG-002
- **Files**: `src/paper_search/exceptions.py`, `tests/test_exceptions.py`
- **Decisions**: NONE — direct implementation from spec

### Task 1.2: OCR Data Models
- [x] Create `src/paper_search/ocr/__init__.py`
- [x] Create `src/paper_search/ocr/models.py`
  - `OCROptions(BaseModel)`: model_version="vlm", is_ocr=True, enable_formula=True, enable_table=True, language="en", page_ranges=None, timeout_s=300, poll_interval_s=5
  - `OCRTaskStatus(BaseModel)`: task_id, state (Literal["pending","running","done","failed","converting"]), extracted_pages=0, total_pages=0, err_msg=""
  - `OCRSection(BaseModel)`: heading, level, content
  - `OCRImage(BaseModel)`: url, alt_text="", caption=""
  - `OCRTable(BaseModel)`: headers (list[str]), rows (list[list[str]]), caption=""
  - `OCRResult(BaseModel)`: task_id, markdown, sections (list[OCRSection]), images (list[OCRImage]), tables (list[OCRTable]), metadata (dict)
- [x] Test: `tests/test_ocr/test_models.py` — validate model construction, defaults, serialization
- **Refs**: REQ-OCR-007
- **Files**: `src/paper_search/ocr/__init__.py`, `src/paper_search/ocr/models.py`, `tests/test_ocr/__init__.py`, `tests/test_ocr/test_models.py`
- **Decisions**: NONE

### Task 1.3: OCR Exception Hierarchy
- [x] Create `src/paper_search/ocr/exceptions.py`
  - `OCRError(ExternalServiceError)` — base for all OCR errors
  - `OCRAuthError(PermanentExternalError)` — 401/403
  - `OCRTimeoutError(TransientExternalError)` — poll timeout
  - `OCRTaskFailedError(PermanentExternalError)` — state=failed
  - `OCRUploadError(TransientExternalError)` — file upload failed
  - `OCRRateLimitError(TransientExternalError)` — 429
  - `OCRFileError(PermanentExternalError)` — bad file type/size
- [x] Test: `tests/test_ocr/test_exceptions.py` — verify hierarchy, isinstance, messages
- **Refs**: REQ-OCR-005
- **Files**: `src/paper_search/ocr/exceptions.py`, `tests/test_ocr/test_exceptions.py`
- **Decisions**: NONE

### Task 1.4: OCRProvider ABC
- [x] Create `src/paper_search/ocr/base.py`
  - `OCRProvider` as `@runtime_checkable Protocol`
  - Abstract methods: `ocr_from_url(url, options) -> OCRResult`, `ocr_from_file(path, options) -> OCRResult`, `get_task_status(task_id) -> OCRTaskStatus`
- [x] Test: `tests/test_ocr/test_base.py` — verify Protocol enforcement (isinstance check, missing method detection)
- **Refs**: REQ-OCR-001
- **Files**: `src/paper_search/ocr/base.py`, `tests/test_ocr/test_base.py`
- **Decisions**: NONE

### Task 1.5: MinerU Adapter - Smart Parsing (URL mode)
- [x] Create `src/paper_search/ocr/mineru_adapter.py`
  - `MineruAdapter(OCRProvider)` class
  - Constructor: `__init__(api_token, base_url="https://mineru.net/api/v4", client=None)`
  - `ocr_from_url()`: POST /extract/task -> poll -> download ZIP -> parse
  - `_submit_url_task(url, options) -> str` (returns task_id)
  - `_poll_task(task_id, timeout_s, poll_interval_s) -> OCRTaskStatus` (exponential backoff: min(60, 2^attempt) + jitter)
  - `_download_zip(zip_url) -> bytes` (async stream to temp file)
  - `_parse_zip(zip_data) -> OCRResult` (extract in threadpool, zip-slip protection)
  - Error mapping: 401/403->OCRAuthError, 429->OCRRateLimitError, code!=0->OCRTaskFailedError
  - API token sanitized from all error messages
- [x] Test: `tests/test_ocr/test_mineru_url.py`
  - Mock httpx: successful task creation + polling + ZIP download
  - Mock httpx: task failure (state=failed)
  - Mock httpx: poll timeout
  - Mock httpx: auth error (401)
  - Mock httpx: rate limit (429)
  - Verify exponential backoff timing
- **Refs**: REQ-OCR-002, REQ-OCR-004, REQ-OCR-005
- **Files**: `src/paper_search/ocr/mineru_adapter.py`, `tests/test_ocr/test_mineru_url.py`
- **Decisions**: NONE — all parameters specified in design

### Task 1.6: MinerU Adapter - Batch Upload (File mode)
- [x] Extend `MineruAdapter` with `ocr_from_file()` implementation
  - `_validate_file(path)`: exists, is PDF, size <= 200MB
  - `_request_upload_url(filename, options) -> (batch_id, upload_url)`
  - `_upload_file(path, upload_url)`: PUT streaming binary
  - `_get_task_id_from_batch(batch_id) -> str`: poll batch status for task_id
  - Chain: validate -> request URL -> upload -> poll -> download -> parse (same as URL mode from poll step)
- [x] Test: `tests/test_ocr/test_mineru_file.py`
  - Mock httpx: successful batch creation + upload + polling
  - File validation: non-existent file, wrong extension, oversized
  - Upload failure handling
  - Verify streaming upload (not loading entire file)
- **Refs**: REQ-OCR-003
- **Files**: `src/paper_search/ocr/mineru_adapter.py`, `tests/test_ocr/test_mineru_file.py`
- **Decisions**: NONE

### Task 1.7: OCR Factory
- [x] Create `src/paper_search/ocr/factory.py`
  - `create_ocr_provider(config: OCRConfig) -> OCRProvider`
  - Validates api_token non-empty
  - Currently only returns `MineruAdapter`
- [x] Test: `tests/test_ocr/test_factory.py` — valid config, empty token error
- **Refs**: REQ-OCR-006
- **Files**: `src/paper_search/ocr/factory.py`, `tests/test_ocr/test_factory.py`
- **Decisions**: NONE

---

## Phase 2: Notion Upload Target Layer

### Task 2.1: Target Data Models
- [x] Create `src/paper_search/targets/__init__.py`
- [x] Create `src/paper_search/targets/models.py`
  - `PaperMetadata(BaseModel)`: title (required), authors="", doi="", venue="", abstract="", year=None, citation_count=None, source_url="", tags=[]
  - `NotionPageInfo(BaseModel)`: page_id, url, title, block_count, created_at
  - `NotionConfig(BaseModel)`: api_token, database_id, version="2025-09-03", rate_limit_rps=2.5, max_blocks_per_request=100, max_text_length=2000, on_duplicate="skip"
- [x] Test: `tests/test_targets/test_models.py`
- **Refs**: REQ-NOT-010
- **Files**: `src/paper_search/targets/__init__.py`, `src/paper_search/targets/models.py`, `tests/test_targets/__init__.py`, `tests/test_targets/test_models.py`
- **Decisions**: NONE

### Task 2.2: Target Exception Hierarchy
- [x] Create `src/paper_search/targets/exceptions.py`
  - `NotionError(ExternalServiceError)` — base
  - `NotionAuthError(PermanentExternalError)` — 401
  - `NotionRateLimitError(TransientExternalError)` — 429
  - `NotionNotFoundError(PermanentExternalError)` — 404
- [x] Test: `tests/test_targets/test_exceptions.py`
- **Refs**: REQ-NOT-008
- **Files**: `src/paper_search/targets/exceptions.py`, `tests/test_targets/test_exceptions.py`
- **Decisions**: NONE

### Task 2.3: UploadTarget ABC
- [x] Create `src/paper_search/targets/base.py`
  - `UploadTarget` as `@runtime_checkable Protocol`
  - Methods: `upload_paper(metadata, content) -> NotionPageInfo`, `check_duplicate(doi) -> str|None`, `health_check() -> bool`
- [x] Test: `tests/test_targets/test_base.py`
- **Refs**: REQ-NOT-001
- **Files**: `src/paper_search/targets/base.py`, `tests/test_targets/test_base.py`
- **Decisions**: NONE

### Task 2.4: AsyncTokenBucket Rate Limiter
- [x] Create `src/paper_search/targets/rate_limiter.py`
  - `AsyncTokenBucket(rate: float, capacity: int)` — async context manager or `async acquire()`
  - Replenishes tokens at `rate` per second, max `capacity`
  - `acquire()` blocks until token available
  - Thread-safe via asyncio.Lock
- [x] Test: `tests/test_targets/test_rate_limiter.py`
  - Verify throughput <= rate over 1s window
  - Verify blocking when empty
  - Verify capacity burst
- **Refs**: REQ-NOT-007
- **PBT**: Over any 1s window, acquired tokens <= ceil(rate)
- **Files**: `src/paper_search/targets/rate_limiter.py`, `tests/test_targets/test_rate_limiter.py`
- **Decisions**: NONE — rate=2.5, capacity=3

### Task 2.5: BlockBuilder - Sanitize Phase
- [x] Create `src/paper_search/targets/block_builder.py`
  - `sanitize(markdown: str) -> str`:
    1. UTF-8 NFC normalization
    2. Strip control chars (keep \n, \t)
    3. Fix double spaces, broken headings
    4. Normalize heading hierarchy
- [x] Test: `tests/test_targets/test_block_builder_sanitize.py`
  - Normal markdown passthrough
  - Control characters removed
  - Unicode normalization
  - PBT: idempotency `sanitize(sanitize(x)) == sanitize(x)`
- **Refs**: REQ-NOT-004
- **Files**: `src/paper_search/targets/block_builder.py`, `tests/test_targets/test_block_builder_sanitize.py`
- **Decisions**: NONE

### Task 2.6: BlockBuilder - Convert Phase
- [x] Extend `block_builder.py` with `convert(markdown: str) -> list[dict]`:
  - Parse sanitized markdown line-by-line
  - Map elements per REQ-NOT-005 table
  - Split text > 2000 chars at sentence/word boundary
  - Fallback: unknown -> paragraph
  - Return list of Notion block dicts
- [x] Test: `tests/test_targets/test_block_builder_convert.py`
  - Each block type: heading, paragraph, list, code, image, table, equation, divider
  - Long text splitting (>2000 chars)
  - Unknown element fallback
  - PBT: output always valid (non-empty list, each dict has "type" key)
  - PBT: no data loss on text splitting (join(split(text)) == text)
- **Refs**: REQ-NOT-005
- **Files**: `src/paper_search/targets/block_builder.py`, `tests/test_targets/test_block_builder_convert.py`
- **Decisions**: NONE — mapping table fully specified

### Task 2.7: BlockBuilder - Chunk Function
- [x] Add `chunk_blocks(blocks: list[dict], max_size: int = 100) -> list[list[dict]]`:
  - Split into groups of max_size
  - Preserve order
- [x] Test: `tests/test_targets/test_block_builder_chunk.py`
  - Empty list -> [[]]
  - Exactly 100 -> [100]
  - 150 -> [100, 50]
  - PBT: concat(chunks) == original, each chunk <= max_size
- **Refs**: REQ-NOT-006
- **Files**: `src/paper_search/targets/block_builder.py`, `tests/test_targets/test_block_builder_chunk.py`
- **Decisions**: NONE — max_size=100

### Task 2.8: Notion Adapter
- [x] Create `src/paper_search/targets/notion_adapter.py`
  - `NotionAdapter(UploadTarget)` class
  - Constructor: `__init__(config: NotionConfig, client: httpx.AsyncClient | None = None)`
  - `_make_headers()`: Authorization + Notion-Version
  - `_map_properties(metadata: PaperMetadata) -> dict`: per REQ-NOT-003 table
  - `upload_paper()`: build blocks -> create page -> append remaining chunks
  - `check_duplicate()`: query database by DOI filter
  - `health_check()`: GET database, verify 200
  - All calls go through `self._rate_limiter.acquire()` first
  - Error mapping: 401->NotionAuthError, 404->NotionNotFoundError, 429->handle retry, 500->TransientExternalError
- [x] Test: `tests/test_targets/test_notion_adapter.py`
  - Mock httpx: successful page creation with properties + children
  - Mock httpx: block append in batches (>100 blocks)
  - Mock httpx: duplicate check found / not found
  - Mock httpx: health check pass / fail
  - Mock httpx: 429 retry
  - Mock httpx: 401 auth error
  - Property mapping correctness (each field type)
  - Empty optional fields omitted
- **Refs**: REQ-NOT-002, REQ-NOT-003, REQ-NOT-008, REQ-NOT-009
- **Files**: `src/paper_search/targets/notion_adapter.py`, `tests/test_targets/test_notion_adapter.py`
- **Decisions**: NONE — all specified in design

### Task 2.9: Target Factory
- [x] Create `src/paper_search/targets/factory.py`
  - `create_upload_target(config: NotionConfig) -> UploadTarget`
  - Validates api_token and database_id non-empty
- [x] Test: `tests/test_targets/test_factory.py`
- **Refs**: Design D-1
- **Files**: `src/paper_search/targets/factory.py`, `tests/test_targets/test_factory.py`
- **Decisions**: NONE

---

## Phase 3: Skills + Config Integration

### Task 3.1: Config Extension
- [x] Extend `src/paper_search/config.py`:
  - Import `OCRConfig` from `ocr/models.py`
  - Import `NotionConfig` from `targets/models.py`
  - Add `WebConfig(BaseModel)`: host="127.0.0.1", port=8080, max_upload_size_mb=200
  - Add to `AppConfig`: `ocr: OCRConfig | None = None`, `notion: NotionConfig | None = None`, `web: WebConfig | None = None`
  - Extend `load_config()` to read MINERU_*, NOTION_*, WEB_* env vars
  - If MINERU_API_TOKEN missing -> ocr=None (feature disabled)
  - If NOTION_API_TOKEN missing -> notion=None (feature disabled)
- [x] Test: `tests/test_config_extended.py`
  - Load with all vars set
  - Load with OCR vars missing -> ocr=None
  - Load with Notion vars missing -> notion=None
  - Default values correct
  - Existing config tests still pass
- **Refs**: REQ-CFG-001
- **Files**: `src/paper_search/config.py`, `tests/test_config_extended.py`
- **Decisions**: NONE

### Task 3.2: OCRProcessor Skill
- [x] Create `src/paper_search/skills/ocr_processor.py`
  - `OCRProcessor(provider: OCRProvider, max_concurrent: int = 5)`
  - `async process(files: list[Path | str]) -> list[tuple[str, OCRResult | Exception]]`
  - Detect URL (starts with http) vs file path
  - Use `asyncio.Semaphore(max_concurrent)` for bounded parallelism
  - Catch exceptions per-file, continue others
- [x] Test: `tests/test_skills/test_ocr_processor.py`
  - Mock provider: 3 files, all succeed
  - Mock provider: 3 files, 1 fails -> 2 succeed + 1 error
  - URL vs file detection
  - Semaphore bounds verified
- **Refs**: REQ-SKL-001
- **Files**: `src/paper_search/skills/ocr_processor.py`, `tests/test_skills/test_ocr_processor.py`
- **Decisions**: NONE

### Task 3.3: ContentUploader Skill
- [x] Create `src/paper_search/skills/content_uploader.py`
  - `ContentUploader(target: UploadTarget)`
  - `async upload(metadata: PaperMetadata, content: OCRResult) -> NotionPageInfo`
  - Delegates to `target.upload_paper()`
- [x] Test: `tests/test_skills/test_content_uploader.py`
  - Mock target: successful upload
  - Mock target: upload failure propagation
- **Refs**: REQ-SKL-002
- **Files**: `src/paper_search/skills/content_uploader.py`, `tests/test_skills/test_content_uploader.py`
- **Decisions**: NONE

---

## Phase 4: Web Frontend

### Task 4.1: Web Data Models
- [x] Create `src/paper_search/web/__init__.py`
- [x] Create `src/paper_search/web/models.py`
  - `JobState(BaseModel)`: id, status, stage, total, results (list[PaperProcessingResult]), created_at
  - `PaperProcessingResult(BaseModel)`: filename, status, ocr_task_id, notion_page_url, error, stage
  - `ProcessingReport(BaseModel)`: job_id, total, succeeded, failed, skipped, results
  - `UploadResponse(BaseModel)`: job_id
  - `HealthResponse(BaseModel)`: mineru (bool), notion (bool)
- [x] Test: `tests/test_web/test_models.py`
- **Refs**: Design data models
- **Files**: `src/paper_search/web/__init__.py`, `src/paper_search/web/models.py`, `tests/test_web/__init__.py`, `tests/test_web/test_models.py`
- **Decisions**: NONE

### Task 4.2: JobManager
- [x] Create `src/paper_search/web/job_manager.py`
  - `JobManager(ocr_provider, upload_target, max_concurrent)`
  - `create_job(files, metadata_list) -> str` (job_id)
  - `get_job(job_id) -> JobState | None`
  - `_process_job(job_id)`: async background task
  - Per-file pipeline: OCR -> BlockBuild -> Upload -> update status
  - Stage transitions update `JobState` immediately
- [x] Test: `tests/test_web/test_job_manager.py`
  - Mock OCR + Notion: 2 files, both succeed
  - Mock OCR fails: partial success
  - Job not found returns None
  - Concurrent job limit
- **Refs**: REQ-WEB-005
- **Files**: `src/paper_search/web/job_manager.py`, `tests/test_web/test_job_manager.py`
- **Decisions**: NONE

### Task 4.3: FastAPI Routes
- [x] Create `src/paper_search/web/routes.py`
  - `POST /api/upload`: accept files + metadata, create job, return 202
  - `GET /api/jobs/{job_id}`: return job state, 404 if missing
  - `GET /api/health`: check MinerU + Notion connectivity
- [x] Create `src/paper_search/web/app.py`
  - `create_app(config) -> FastAPI`: factory function
  - Mount static files
  - Include routes
  - CORS middleware (localhost)
- [x] Test: `tests/test_web/test_routes.py`
  - TestClient: upload valid PDF -> 202
  - TestClient: upload non-PDF -> 422
  - TestClient: get job status -> 200
  - TestClient: get missing job -> 404
  - TestClient: health check
- **Refs**: REQ-WEB-001, REQ-WEB-002, REQ-WEB-003, REQ-WEB-004
- **Files**: `src/paper_search/web/routes.py`, `src/paper_search/web/app.py`, `tests/test_web/test_routes.py`
- **Decisions**: NONE

### Task 4.4: Web Entry Point
- [x] Create `src/paper_search/web/__main__.py`
  - Load config, create app, run uvicorn
  - `python -m paper_search.web` starts server
- [x] Test: manual smoke test (start server, access browser)
- **Refs**: REQ-WEB-001
- **Files**: `src/paper_search/web/__main__.py`
- **Decisions**: NONE

### Task 4.5: Frontend Static Files
- [x] Create `src/paper_search/web/static/index.html`
  - Drag-and-drop zone with visual feedback
  - File list display (name, size)
  - Optional metadata inputs (title, DOI, authors per file)
  - Upload button
  - Progress stepper per file
  - Result display with Notion links
- [x] Create `src/paper_search/web/static/style.css`
  - Clean, minimal design
  - Drop zone styling (dashed border, hover state)
  - Progress indicators
  - Responsive layout
- [x] Create `src/paper_search/web/static/upload.js`
  - Drag-and-drop handlers
  - File validation (PDF only, size limit)
  - FormData construction + fetch POST
  - Polling loop (2s interval)
  - DOM updates for progress and results
- [x] Test: manual E2E (drag PDF -> upload -> see Notion link)
- **Refs**: REQ-WEB-006
- **Files**: `src/paper_search/web/static/index.html`, `src/paper_search/web/static/style.css`, `src/paper_search/web/static/upload.js`
- **Decisions**: NONE — pure HTML/CSS/JS, no framework

### Task 4.6: Dependencies Update
- [x] Update `pyproject.toml`:
  - Add `[project.optional-dependencies] ocr-notion = ["fastapi>=0.115,<1.0", "uvicorn[standard]>=0.31.1", "python-multipart>=0.0.9"]`
- [x] Verify: `uv pip install -e ".[ocr-notion]"` succeeds
- [x] Verify: existing tests still pass
- **Refs**: Design D-13
- **Files**: `pyproject.toml`
- **Decisions**: NONE

---

## Phase 5: Final Verification

### Task 5.1: Integration Test
- [x] Create `tests/test_integration/test_ocr_notion_pipeline.py`
  - Full pipeline: mock PDF -> mock OCR -> mock Notion -> verify ProcessingReport
  - Multiple files with partial failure
  - Deduplication (same DOI twice)
- **Files**: `tests/test_integration/test_ocr_notion_pipeline.py`

### Task 5.2: Existing Test Regression
- [x] Run `pytest tests/ -v` — all 378 tests pass (180 existing + 198 new)
- [x] Run `pytest tests/ --cov=paper_search` — new code >= 80% coverage
- **No files modified** — verification only

### Task 5.3: Update .env.example
- [x] Add MINERU_*, NOTION_*, WEB_* env var examples
- **Files**: `.env.example`
