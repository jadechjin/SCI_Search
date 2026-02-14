# Proposal: OCR PDF + Notion Upload

## Context

技术总纲第三步：将用户手动下载的 PDF 文献通过 MinerU OCR 解析后，结构化上传到 Notion 数据库，作为后续文献库的基础。

本功能是 paper-search workflow 的下游模块，接收论文元数据（DOI、标题、作者等）和 PDF 文件，产出 Notion 页面。

### User Decisions (已确认)

| 决策点 | 选择 |
|--------|------|
| 架构方案 | **方案 B: Skills 扩展** — OCRProvider ABC + UploadTarget ABC |
| MinerU 模式 | **双模式** — 本地文件(Batch Upload) + URL(Smart Parsing) |
| Notion Schema | 完整学术元数据 + 全文结构化正文 |
| 内容范围 | MinerU 全文档解析结果直接传 Notion |
| 前端 | 拖拽上传页面 |
| Token | 已有 MinerU + Notion API tokens |

---

## Hard Constraints (不可违反)

### HC-1: MinerU Smart Parsing API

| 约束 | 值 |
|------|-----|
| 创建任务 | `POST https://mineru.net/api/v4/extract/task` |
| 查询结果 | `GET https://mineru.net/api/v4/extract/task/{task_id}` |
| 认证 | `Authorization: Bearer {token}` |
| 输入 | **URL only** — 必须提供公开可访问的文件 URL |
| 文件限制 | 200MB, 600 页 |
| 每日额度 | 2000 页高优先级 |
| 模型版本 | `pipeline` / `vlm` / `MinerU-HTML` |
| 可选参数 | `is_ocr`, `enable_formula`, `enable_table`, `language`, `page_ranges`, `data_id`, `callback`, `seed`, `extra_formats`, `model_version` |
| 任务状态 | pending → running → done / failed / converting |
| 结果格式 | `full_zip_url` — ZIP 包含 markdown + JSON |
| 进度字段 | `extract_progress.extracted_pages`, `total_pages`, `start_time` |

### HC-2: MinerU Batch Upload API

| 约束 | 值 |
|------|-----|
| 申请链接 | `POST https://mineru.net/api/v4/file-urls/batch` |
| 上传文件 | `PUT {pre_signed_url}` — binary body, 无 Content-Type |
| 认证 | 同上 Bearer token |
| 文件数 | 单次最多 200 个 |
| 链接有效期 | 24 小时 |
| 自动解析 | 上传完成后系统自动提交解析任务 |
| 请求体 | `files[].name` (必需), `files[].data_id`, `files[].is_ocr`, `files[].page_ranges` |
| 全局参数 | `model_version`, `enable_formula`, `enable_table`, `language`, `callback`, `seed` |
| 响应 | `batch_id` + `file_urls[]` |
| 结果查询 | 使用各文件的 task_id 轮询（同 HC-1） |

### HC-3: Notion API

| 约束 | 值 |
|------|-----|
| Base URL | `https://api.notion.com` |
| 认证 | `Authorization: Bearer {token}`, `Notion-Version: 2025-09-03` |
| 创建页面 | `POST /v1/pages` |
| 追加块 | `PATCH /v1/blocks/{block_id}/children` |
| 频率限制 | **3 req/s** (429 → retry-after) |
| Children 限制 | 每次请求最多 **100 个 block** |
| 嵌套限制 | 单次请求最多 **2 层嵌套** |
| Rich text 限制 | 每个 rich_text 数组最多 100 项 |
| 文本长度限制 | 单个 text content 最多 **2000 字符** |
| 支持的 block | paragraph, heading_1/2/3, code, table, table_row, bulleted_list_item, numbered_list_item, quote, callout, divider, image, bookmark, embed, toggle, to_do |
| 属性类型 | title, rich_text, url, select, multi_select, number, date, checkbox, relation, files, status |

### HC-4: 现有代码库

| 约束 | 说明 |
|------|------|
| 全异步 | 所有网络操作必须使用 `async/await` + `httpx.AsyncClient` |
| Pydantic | 所有数据模型必须继承 `BaseModel` |
| 配置 | 通过 `.env` + `AppConfig` 加载 |
| 错误体系 | 复用 `RetryableError` / `NonRetryableError` |
| 测试 | pytest + pytest-asyncio, 现有 180+ 测试不可破坏 |
| 目录 | 新代码放在 `src/paper_search/` 下 |

---

## Soft Constraints (约定/偏好)

### SC-1: 代码风格
- 文件 200-400 行，最多 800 行
- 函数 < 50 行
- 不可变操作优先
- 无 console.log / print（使用 logging）
- 无硬编码值

### SC-2: 设计模式
- ABC 抽象接口 → 具体适配器（参考 `SearchSource`, `LLMProvider`）
- Factory 模式创建适配器实例
- Skills 模式：每个处理步骤是独立 skill 类
- 错误映射：provider-specific exception → 统一异常

### SC-3: 测试
- 新功能 80%+ 覆盖率
- Mock 外部 API 调用
- 每个 adapter 独立测试 + 集成测试

---

## Notion Database Schema

### Properties (第一层: 属性)

| 属性名 | Notion 类型 | 来源 | 必需 |
|--------|-------------|------|------|
| 标题 | `title` | MinerU 解析结果 / Paper.title | Y |
| 作者 | `rich_text` | Paper.authors | N |
| DOI | `url` | Paper.doi | N |
| 期刊 | `rich_text` | Paper.venue | N |
| 摘要 | `rich_text` | MinerU 解析结果 abstract section | N |
| 阅读状态 | `select` | 默认 "未读"，选项: 未读/在读/已读 | Y |
| 年份 | `number` | Paper.year | N |
| 引用数 | `number` | Paper.citation_count | N |
| 来源URL | `url` | Paper.full_text_url | N |
| 标签 | `multi_select` | Paper.tags | N |
| OCR状态 | `select` | 处理状态: 成功/失败/处理中 | Y |
| 上传时间 | `date` | 当前时间 | Y |

### Content (第二层: 正文 Blocks)

MinerU 解析的全文档内容，按结构化块上传：
- `heading_2` / `heading_3` — 章节标题
- `paragraph` — 正文段落
- `code` — 代码块（保留语言标记）
- `table` + `table_row` — 表格
- `image` — 图片（MinerU ZIP 中的图片 URL）
- `bulleted_list_item` / `numbered_list_item` — 列表
- `equation` — 公式（如 MinerU 解析出 LaTeX）
- `divider` — 章节分隔

**分块策略**: Notion 每次最多 100 blocks，需分批 PATCH `/v1/blocks/{page_id}/children`。

**文本截断**: 单个 block 的 rich_text content 最多 2000 字符，超长段落需拆分。

---

## Module Architecture (方案 B: Skills 扩展)

```
src/paper_search/
├── ocr/                          # OCR 提供商层
│   ├── __init__.py
│   ├── base.py                   # OCRProvider ABC
│   ├── mineru_adapter.py         # MinerU 双模式实现
│   ├── models.py                 # OCRResult, OCRTask, OCRConfig
│   └── exceptions.py             # OCRError hierarchy
├── targets/                      # 上传目标层
│   ├── __init__.py
│   ├── base.py                   # UploadTarget ABC
│   ├── notion_adapter.py         # Notion API 实现
│   ├── block_builder.py          # Markdown → Notion blocks 转换
│   ├── models.py                 # NotionPageInfo, NotionConfig
│   └── exceptions.py             # NotionError hierarchy
├── skills/
│   ├── ... (existing 6 skills)
│   ├── ocr_processor.py          # OCR skill (使用 OCRProvider)
│   └── content_uploader.py       # Upload skill (使用 UploadTarget)
├── web/                          # 前端上传页面
│   ├── __init__.py
│   ├── app.py                    # FastAPI/Starlette web server
│   ├── routes.py                 # Upload API endpoints
│   ├── static/                   # 前端静态文件
│   │   ├── index.html            # 拖拽上传页面
│   │   ├── style.css
│   │   └── upload.js
│   └── models.py                 # Web request/response models
└── models.py                     # 扩展: OCRResult, NotionPageInfo
```

---

## Data Flow

```
[用户] --拖拽PDF--> [Web前端]
                        │
                        ▼
              [FastAPI Upload Endpoint]
                        │
                   ┌────┴────┐
                   │ 本地文件 │  或  │ URL │
                   └────┬────┘      └──┬──┘
                        │              │
                        ▼              ▼
              [MinerU Batch API]  [MinerU Smart API]
              (申请URL→上传→自动解析)  (提交URL→解析)
                        │              │
                        └──────┬───────┘
                               │
                          [轮询 task_id]
                               │
                               ▼
                     [下载 full_zip_url]
                               │
                               ▼
                    [解压 → 提取 markdown/JSON]
                               │
                               ▼
                      [OCRResult 模型]
                               │
                               ▼
                [BlockBuilder: markdown → Notion blocks]
                               │
                               ▼
              [Notion API: 创建页面 + 分批追加 blocks]
                               │
                               ▼
                    [NotionPageInfo(url)]
```

---

## Error Handling

### OCR Errors

| 错误类型 | 触发条件 | 处理策略 |
|----------|----------|----------|
| `OCRAuthError` | MinerU 401/403 | NonRetryable, 提示检查 token |
| `OCRTimeoutError` | 轮询超时 | Retryable, 可延长超时继续轮询 |
| `OCRTaskFailedError` | state=failed | NonRetryable, 返回 err_msg |
| `OCRUploadError` | PUT 上传失败 | Retryable, 指数退避重试 |
| `OCRRateLimitError` | 超日配额 | NonRetryable, 提示次日重试 |
| `OCRFileError` | 文件格式/大小不支持 | NonRetryable, 验证前置检查 |

### Notion Errors

| 错误类型 | 触发条件 | 处理策略 |
|----------|----------|----------|
| `NotionAuthError` | 401 | NonRetryable, 检查 token |
| `NotionRateLimitError` | 429 | Retryable, respect retry-after |
| `NotionNotFoundError` | 404 database | NonRetryable, 检查 database_id |
| `NotionBlockLimitError` | >100 blocks | 自动分批, 非错误 |
| `NotionContentError` | >2000 chars | 自动拆分, 非错误 |

### 批量处理容错

- 单个 PDF 失败不阻塞其他文件
- 返回 `ProcessingReport`: 成功列表 + 失败列表(含原因)
- Partial success 是合法结果

---

## API Interfaces

### OCRProvider ABC

```python
class OCRProvider(ABC):
    @abstractmethod
    async def ocr_from_url(self, url: str, options: OCROptions) -> OCRResult:
        """OCR a file from a public URL."""

    @abstractmethod
    async def ocr_from_file(self, file_path: Path, options: OCROptions) -> OCRResult:
        """OCR a local file (upload first, then process)."""

    @abstractmethod
    async def get_task_status(self, task_id: str) -> OCRTaskStatus:
        """Poll task status."""
```

### UploadTarget ABC

```python
class UploadTarget(ABC):
    @abstractmethod
    async def upload_paper(
        self, metadata: PaperMetadata, content: OCRResult
    ) -> UploadResult:
        """Upload a paper with metadata and OCR content."""

    @abstractmethod
    async def check_connection(self) -> bool:
        """Verify target is accessible."""
```

### Web Upload Endpoint

```
POST /api/upload
  - multipart/form-data: files[] + metadata (JSON)
  - Response: { job_id, status, papers: [{ title, ocr_status, notion_url }] }

GET /api/status/{job_id}
  - Response: { status, progress, papers: [...] }

GET /
  - Serves drag-and-drop upload HTML page
```

---

## Success Criteria

| # | 判据 | 验证方式 |
|---|------|----------|
| SC-1 | 本地 PDF → MinerU OCR → 结构化 OCRResult | 单元测试: mock MinerU API → 验证 OCRResult 字段 |
| SC-2 | URL PDF → MinerU Smart API → OCRResult | 单元测试: mock Smart API → 验证任务创建+轮询+结果 |
| SC-3 | OCRResult → Notion 页面 (属性 + 正文 blocks) | 单元测试: mock Notion API → 验证请求体结构 |
| SC-4 | 超过 100 blocks 自动分批追加 | 单元测试: 150 blocks → 验证 2 次 PATCH 调用 |
| SC-5 | 超过 2000 字符段落自动拆分 | 单元测试: 3000 字符文本 → 验证拆分成 2 个 paragraph |
| SC-6 | Notion 429 错误自动退避重试 | 单元测试: mock 429 → 验证 retry 逻辑 |
| SC-7 | 批量处理 N 个 PDF, 部分失败返回报告 | 集成测试: 3 files, 1 fails → 验证 2 成功 + 1 失败 |
| SC-8 | 前端拖拽上传 → 后端处理 → 返回结果 | E2E: 上传页面 → 提交文件 → 检查 Notion 页面 |
| SC-9 | 现有 180+ 测试全部通过 | CI: pytest tests/ 全绿 |
| SC-10 | 新功能 80%+ 测试覆盖率 | Coverage: pytest --cov |

---

## Implementation Phases (建议)

### Phase 1: OCR 提供商层
- `ocr/base.py` — OCRProvider ABC + 数据模型
- `ocr/mineru_adapter.py` — 双模式 MinerU 实现
- `ocr/exceptions.py` — 错误层次
- 测试: 15-20 个

### Phase 2: Notion 上传目标层
- `targets/base.py` — UploadTarget ABC
- `targets/block_builder.py` — Markdown → Notion blocks 转换器
- `targets/notion_adapter.py` — Notion API 实现
- `targets/exceptions.py` — 错误层次
- 测试: 15-20 个

### Phase 3: Skills + 配置集成
- `skills/ocr_processor.py` — OCR skill
- `skills/content_uploader.py` — Upload skill
- `config.py` 扩展: OCRConfig + NotionConfig
- `models.py` 扩展: OCRResult, NotionPageInfo
- 测试: 10-15 个

### Phase 4: Web 前端
- `web/app.py` — FastAPI server
- `web/routes.py` — Upload endpoints
- `web/static/` — 拖拽上传 HTML/CSS/JS
- 测试: 5-10 个

---

## Dependencies (新增)

```toml
[project.optional-dependencies]
ocr-notion = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
]
```

注: httpx 已有, Notion API 通过 httpx 直接调用 (无需 notion-client SDK)。
MinerU API 也通过 httpx 直接调用 (无需 mineru-kie-sdk)。

---

## Config Extension

```env
# MinerU OCR
MINERU_API_TOKEN=xxx
MINERU_MODEL_VERSION=vlm
MINERU_IS_OCR=true
MINERU_LANGUAGE=en
MINERU_TIMEOUT_S=300

# Notion
NOTION_API_TOKEN=xxx
NOTION_DATABASE_ID=xxx
NOTION_VERSION=2025-09-03

# Web
WEB_HOST=127.0.0.1
WEB_PORT=8080
```

---

## Risks

| 风险 | 影响 | 缓解 |
|------|------|------|
| MinerU 日配额 2000 页 | 大批量处理受限 | 队列化, 跨天分批 |
| Notion 3 req/s 限速 | 大文档上传慢 | 令牌桶限速器, 批量 blocks |
| MinerU 结果 ZIP 下载失败 | OCR 完成但无法获取结果 | 重试 + 30 天有效期内可再下载 |
| Markdown → Notion blocks 转换丢失格式 | 部分内容降级 | 降级策略: 未知格式 → paragraph |
| 图片 URL 30 天过期 | Notion 图片失效 | 下载图片 → 上传到 Notion / 外部存储 |
| 大 PDF (>100 页) 解析时间长 | 用户等待 | 异步处理 + 进度回调 |
