# Spec: Skills, Config, Web, and Integration

## REQ-SKL-001: OCRProcessor Skill
**Given** an `OCRProvider` instance and file(s)
**When** processing papers
**Then**:
1. For each file: detect mode (URL or local path)
2. Call `ocr_from_url()` or `ocr_from_file()` accordingly
3. Collect results as `list[OCRResult]`
4. Failed files: catch exceptions, record in report, continue processing others
5. Returns `list[tuple[filename, OCRResult | Exception]]`

**Constraint**: Uses `asyncio.Semaphore(config.max_concurrent)` to bound parallel OCR tasks

## REQ-SKL-002: ContentUploader Skill
**Given** an `UploadTarget` instance, `PaperMetadata`, and `OCRResult`
**When** uploading a paper
**Then**:
1. Build Notion blocks via `BlockBuilder.convert(ocr_result)`
2. Call `target.upload_paper(metadata, content)`
3. Returns `NotionPageInfo`

**Constraint**: Single-paper granularity; batch orchestration is in job_manager

## REQ-CFG-001: Configuration Extension
**Given** existing `AppConfig` in `config.py`
**When** loading config with OCR+Notion env vars
**Then**:
- `AppConfig` gains optional fields: `ocr: OCRConfig | None`, `notion: NotionConfig | None`, `web: WebConfig | None`
- Each loaded from `.env` with prefix: `MINERU_*`, `NOTION_*`, `WEB_*`
- Missing OCR/Notion config → features disabled (not error)
- `load_config()` extended to populate new fields

**Env vars**:
```
MINERU_API_TOKEN, MINERU_MODEL_VERSION, MINERU_IS_OCR, MINERU_LANGUAGE, MINERU_TIMEOUT_S
NOTION_API_TOKEN, NOTION_DATABASE_ID, NOTION_VERSION, NOTION_RATE_LIMIT_RPS, NOTION_ON_DUPLICATE
WEB_HOST, WEB_PORT, WEB_MAX_UPLOAD_SIZE_MB
```

## REQ-CFG-002: Shared Exception Base
**Given** OCR and Notion modules need unified error handling
**When** creating shared exceptions in `src/paper_search/exceptions.py`
**Then**:
```python
class ExternalServiceError(Exception):
    """Base for all external service errors."""

class TransientExternalError(ExternalServiceError):
    """Retryable external service error (429, 500, timeout)."""

class PermanentExternalError(ExternalServiceError):
    """Non-retryable external service error (401, 404, bad input)."""
```
**Constraint**: These do NOT inherit from existing `RetryableError`/`NonRetryableError` in `sources/exceptions.py` (those are SerpAPI-scoped)

## REQ-WEB-001: FastAPI Application
**Given** the web module
**When** started via `python -m paper_search.web`
**Then**:
1. Creates FastAPI app with CORS (localhost only by default)
2. Mounts `/static` serving `web/static/` directory
3. Registers routes: `/api/upload`, `/api/jobs/{job_id}`, `/api/health`, `/` (redirect to index.html)
4. Starts uvicorn on `config.web.host:config.web.port`

**Constraint**: Separate process from MCP server (no ASGI conflict)

## REQ-WEB-002: Upload Endpoint
**Given** `POST /api/upload` with `multipart/form-data`
**When** receiving file(s) and optional metadata JSON
**Then**:
1. Validate files: must be PDF (check MIME + extension), size <= `max_upload_size_mb`
2. Save files to temp directory
3. Create job in `JobManager` with status=pending
4. Launch async background task for processing
5. Return `202 Accepted` with `{"job_id": "uuid"}`

**Constraints**:
- Accept multiple files in single request
- Metadata is optional — can be provided per-file or omitted
- File validation BEFORE saving (reject early)
- `python-multipart` handles form parsing

## REQ-WEB-003: Job Status Endpoint
**Given** `GET /api/jobs/{job_id}`
**When** polling job status
**Then** returns:
```json
{
  "job_id": "uuid",
  "status": "processing|completed|failed",
  "stage": "uploading|ocr_processing|formatting|uploading_to_notion|done",
  "progress": {"current": 1, "total": 3},
  "results": [
    {"filename": "paper.pdf", "status": "success", "notion_page_url": "..."},
    {"filename": "paper2.pdf", "status": "failed", "error": "OCR timeout", "stage": "ocr_processing"}
  ]
}
```
**Constraint**: 404 if job_id not found

## REQ-WEB-004: Health Endpoint
**Given** `GET /api/health`
**When** checking service connectivity
**Then** returns `{"mineru": bool, "notion": bool}` based on API reachability

## REQ-WEB-005: JobManager
**Given** background processing of uploaded files
**When** managing jobs
**Then**:
1. Maintains in-memory dict of `{job_id: JobState}`
2. `JobState`: id, status, stage, files, results, created_at
3. Processing pipeline per file: OCR → BlockBuild → Upload
4. Updates `JobState` at each stage transition
5. Bounded concurrent processing via `asyncio.Semaphore`

**Constraint**: In-process only (no Redis/external queue). Jobs lost on restart (acceptable for MVP).

## REQ-WEB-006: Frontend Upload Page
**Given** `static/index.html`
**When** user accesses `/`
**Then**:
1. Displays drag-and-drop zone for PDF files
2. Accepts click-to-browse as alternative
3. Shows file list with names and sizes
4. Optional metadata input per file (title, DOI, authors)
5. "Upload" button starts upload
6. Progress display: stepper showing current stage per file
7. Results: Notion page links on success, error messages on failure

**Constraints**:
- Pure HTML/CSS/JS (no build step, no framework)
- Client-side validation: PDF only, size < 200MB
- Polls `/api/jobs/{id}` every 2 seconds during processing
- Responsive layout (desktop-first, mobile acceptable)

## REQ-INT-001: Model Extensions
**Given** existing `src/paper_search/models.py`
**When** extending for OCR+Notion feature
**Then** add to models.py OR reference from submodule models:
- `OCRResult`, `OCRSection`, `OCRImage`, `OCRTable` (in `ocr/models.py`)
- `PaperMetadata`, `NotionPageInfo` (in `targets/models.py`)
- `ProcessingReport`, `PaperProcessingResult` (in `web/models.py` or shared)

**Constraint**: Do NOT modify existing Paper/PaperCollection/RawPaper models

## REQ-INT-002: Package Exports
**Given** `src/paper_search/__init__.py`
**When** extending public API
**Then** add to `__all__`:
- `OCRResult`, `PaperMetadata`, `NotionPageInfo`, `ProcessingReport`
- Do NOT export internal adapters or ABCs

## REQ-INT-003: Test Isolation
**Given** new tests for OCR/Notion/Web
**When** running test suite
**Then**:
- All 180+ existing tests still pass
- New tests in `tests/test_ocr/`, `tests/test_targets/`, `tests/test_web/`
- No external API calls in tests (all mocked via httpx mock or respx)
- Web tests use FastAPI TestClient
- Target: 80%+ coverage on new code
