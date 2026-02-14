# Spec: OCR Provider Layer

## REQ-OCR-001: OCRProvider ABC
**Given** a developer implementing a new OCR provider
**When** they subclass `OCRProvider`
**Then** they must implement `ocr_from_url()`, `ocr_from_file()`, and `get_task_status()` as async methods

**Constraints**:
- All methods are `async`
- `ocr_from_url()` accepts `str` URL + optional `OCROptions`, returns `OCRResult`
- `ocr_from_file()` accepts `Path` + optional `OCROptions`, returns `OCRResult`
- `get_task_status()` accepts `str` task_id, returns `OCRTaskStatus`
- ABC is `@runtime_checkable` Protocol (matching existing `CheckpointHandler` pattern)

## REQ-OCR-002: MinerU Smart Parsing (URL mode)
**Given** a public URL pointing to a PDF
**When** `ocr_from_url(url, options)` is called
**Then** the adapter:
1. POSTs to `https://mineru.net/api/v4/extract/task` with `{"url": url, "model_version": options.model_version, "is_ocr": options.is_ocr, ...}`
2. Receives `{"code": 0, "data": {"task_id": "..."}}`
3. Polls `GET /v4/extract/task/{task_id}` with exponential backoff (base=5s, ceiling=60s, jitter=random(0,1))
4. On `state=done`: downloads `full_zip_url`, extracts, parses markdown → `OCRResult`
5. On `state=failed`: raises `OCRTaskFailedError(err_msg)`
6. On timeout (wall-clock > `timeout_s`): raises `OCRTimeoutError`

**Invariant (PBT)**: Poll interval never exceeds 60 seconds; total polls <= ceil(timeout_s / 5)

## REQ-OCR-003: MinerU Batch Upload (File mode)
**Given** a local PDF file path
**When** `ocr_from_file(path, options)` is called
**Then** the adapter:
1. Validates file exists, is PDF, size <= 200MB
2. POSTs to `https://mineru.net/api/v4/file-urls/batch` with `{"files": [{"name": filename}], "model_version": ...}`
3. Receives `{"code": 0, "data": {"batch_id": "...", "file_urls": ["pre_signed_url"]}}`
4. PUTs file binary to `pre_signed_url` (no Content-Type header)
5. Polls for task result (same as REQ-OCR-002 step 3-6)
6. On upload failure: raises `OCRUploadError`

**Constraints**:
- File validation BEFORE any API call
- Pre-signed URL valid for 24h
- Upload uses streaming (not load entire file to memory)

## REQ-OCR-004: ZIP Download and Parsing
**Given** a `full_zip_url` from completed MinerU task
**When** downloading and parsing the result ZIP
**Then** the adapter:
1. Downloads ZIP as async stream to temp file (not memory)
2. Extracts ZIP in threadpool (`asyncio.to_thread`)
3. Validates: no path traversal (zip-slip protection)
4. Locates `*.md` file(s) — primary markdown content
5. Locates image files and maps to CDN URLs
6. Parses markdown into `OCRResult` (sections, images, tables)
7. Cleans up temp files

**Invariant**: Extracted file paths are all within temp directory (no escape)

## REQ-OCR-005: OCR Error Mapping
**Given** any HTTP error from MinerU API
**When** mapping to domain exceptions
**Then**:
- 401/403 → `OCRAuthError` (PermanentExternalError)
- 429 → `OCRRateLimitError` (TransientExternalError)
- 500/503 → `TransientExternalError` (retryable)
- Timeout → `OCRTimeoutError` (TransientExternalError)
- `code != 0` in response → `OCRTaskFailedError` with `msg` field

**Constraint**: API token NEVER appears in exception messages or logs

## REQ-OCR-006: OCR Factory
**Given** an `OCRConfig`
**When** `create_ocr_provider(config)` is called
**Then** returns `MineruAdapter` instance (only provider for now)
**Constraint**: Validates `api_token` is non-empty before construction

## REQ-OCR-007: OCR Data Models
- `OCROptions`: model_version, is_ocr, enable_formula, enable_table, language, page_ranges, timeout_s, poll_interval_s
- `OCRTaskStatus`: task_id, state (pending|running|done|failed|converting), progress (extracted_pages, total_pages), err_msg
- `OCRResult`: task_id, markdown, sections (list[OCRSection]), images (list[OCRImage]), tables (list[OCRTable]), metadata
- `OCRSection`: heading, level, content
- `OCRImage`: url, alt_text, caption
- `OCRTable`: headers, rows, caption
- All are Pydantic `BaseModel` with `model_config = ConfigDict(frozen=True)` where appropriate
