# paper-search

AI 驱动的学术论文搜索工作流系统。通过自然语言描述研究需求，自动完成意图解析、查询构建、多源搜索、去重、相关性评分和结果整理。

## 系统架构

```
用户查询 (自然语言)
    │
    ▼
┌──────────────┐
│ IntentParser │  ← LLM 解析研究意图
└──────┬───────┘
       ▼
┌──────────────┐     ┌─────────────────────────┐
│ QueryBuilder │ ──▶ │ Checkpoint 1: 策略确认   │ (可选)
└──────┬───────┘     └─────────────────────────┘
       ▼
┌──────────────┐
│   Searcher   │  ← SerpAPI Google Scholar
└──────┬───────┘
       ▼
┌──────────────┐
│ Deduplicator │  ← DOI / URL / 标题 去重
└──────┬───────┘
       ▼
┌────────────────┐
│RelevanceScorer │  ← LLM 批量评分
└──────┬─────────┘
       ▼
┌────────────────┐     ┌─────────────────────────┐
│ResultOrganizer │ ──▶ │ Checkpoint 2: 结果审查   │ (必选)
└──────┬─────────┘     └─────────────────────────┘
       ▼
  PaperCollection (最终结果)
```

支持 **迭代搜索**：在结果审查阶段可以 reject/edit 触发新一轮搜索，用户反馈会传递给 QueryBuilder 优化下一轮查询。

## 安装

```bash
# 克隆项目
git clone <repo-url>
cd workflow

# 使用 uv 安装依赖
uv sync

# 如需 MCP Server 功能
uv sync --extra mcp
```

## 配置

复制 `.env.example` 为 `.env` 并填入 API Key：

```bash
cp .env.example .env
```

必要配置：

| 环境变量 | 说明 | 示例 |
|---------|------|------|
| `SERPAPI_API_KEY` | SerpAPI 密钥 (Google Scholar 搜索) | `abc123...` |
| `LLM_PROVIDER` | LLM 提供商 | `openai` / `anthropic` / `gemini` |
| `OPENAI_API_KEY` | OpenAI API Key (当 provider=openai) | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API Key (当 provider=anthropic) | `sk-ant-...` |
| `GOOGLE_API_KEY` | Google API Key (当 provider=gemini) | `AIza...` |

可选配置：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `LLM_MODEL` | (provider 默认) | 指定模型名称 |
| `LLM_TEMPERATURE` | `0.0` | LLM 温度参数 |
| `LLM_MAX_TOKENS` | `4096` | 最大输出 token 数 |
| `DEFAULT_MAX_RESULTS` | `100` | 默认最大结果数 |
| `DOMAIN` | `general` | 研究领域 (`general` 或 `materials_science`) |
| `LLM_BASE_URL` | (无) | 自定义 LLM 端点 (兼容 OpenAI API 的服务) |
| `RELEVANCE_BATCH_SIZE` | `10` | 相关性评分批大小 |
| `RELEVANCE_MAX_CONCURRENCY` | `3` | 相关性评分并发上限 |
| `DEDUP_ENABLE_LLM_PASS` | `true` | 是否启用 LLM 语义去重 |
| `DEDUP_LLM_MAX_CANDIDATES` | `60` | 语义去重最大候选数（超过则跳过 LLM pass） |
| `MCP_DECIDE_WAIT_TIMEOUT_S` | `15.0` | `decide()` 等待“下一状态”的最长秒数 |
| `MCP_POLL_INTERVAL_S` | `0.05` | MCP 会话轮询间隔（秒） |

## 使用方式

### 1. Python Library (推荐)

最简单的使用方式 —— 一行调用完成全流程搜索：

```python
import asyncio
from paper_search import search, export_markdown, export_json, export_bibtex

async def main():
    # 一行搜索 (自动审批所有 checkpoint)
    results = await search("perovskite solar cells efficiency 2020-2024")

    # 导出为 Markdown 表格
    print(export_markdown(results))

    # 导出为 JSON
    json_str = export_json(results)

    # 导出为 BibTeX (可直接导入 LaTeX)
    bibtex_str = export_bibtex(results)

asyncio.run(main())
```

**自定义配置：**

```python
from paper_search import search
from paper_search.config import AppConfig, LLMConfig, SearchSourceConfig

config = AppConfig(
    llm=LLMConfig(
        provider="anthropic",
        model="claude-sonnet-4-5-20250929",
        api_key="sk-ant-...",
    ),
    sources={
        "serpapi_scholar": SearchSourceConfig(
            name="serpapi_scholar",
            api_key="your-serpapi-key",
        ),
    },
    domain="materials_science",
)

results = await search("锂离子电池正极材料", config=config)
```

**访问结果数据：**

```python
results = await search("graphene thermal conductivity")

# 结果元数据
print(f"共找到 {results.metadata.total_found} 篇论文")

# 遍历论文
for paper in results.papers:
    print(f"[{paper.relevance_score:.2f}] {paper.title}")
    print(f"  作者: {', '.join(a.name for a in paper.authors)}")
    print(f"  年份: {paper.year}  期刊: {paper.venue}")
    if paper.doi:
        print(f"  DOI: {paper.doi}")

# 分面统计
print(f"年份分布: {results.facets.by_year}")
print(f"期刊分布: {results.facets.by_venue}")
print(f"高频作者: {results.facets.top_authors}")
print(f"关键主题: {results.facets.key_themes}")
```

### 2. 带人工审查的高级用法

如需在搜索过程中介入审查，使用 `SearchWorkflow` + 自定义 `CheckpointHandler`：

```python
import asyncio
from paper_search.config import load_config
from paper_search.workflow import SearchWorkflow
from paper_search.workflow.checkpoints import (
    Checkpoint, CheckpointHandler, CheckpointKind,
    Decision, DecisionAction,
)

class MyHandler:
    """自定义 checkpoint handler 示例。"""

    async def handle(self, checkpoint: Checkpoint) -> Decision:
        if checkpoint.kind == CheckpointKind.STRATEGY_CONFIRMATION:
            # 查看搜索策略
            strategy = checkpoint.payload.strategy
            print(f"搜索策略: {len(strategy.queries)} 条查询")
            for q in strategy.queries:
                print(f"  - {q.boolean_query}")

            # 批准策略
            return Decision(action=DecisionAction.APPROVE)

        elif checkpoint.kind == CheckpointKind.RESULT_REVIEW:
            # 查看搜索结果
            collection = checkpoint.payload.collection
            print(f"找到 {len(collection.papers)} 篇论文")

            # 可以选择:
            # - APPROVE: 接受结果
            # - REJECT: 拒绝并重新搜索 (附带反馈)
            # - EDIT: 修改后继续
            return Decision(action=DecisionAction.APPROVE)

config = load_config()
wf = SearchWorkflow.from_config(config, checkpoint_handler=MyHandler())
results = await wf.run("high-entropy alloys mechanical properties")
```

### 3. MCP Server (Agent 集成)

将搜索能力暴露为 MCP 工具，供 Claude 等 AI Agent 调用：

```bash
# 安装 MCP 依赖
uv sync --extra mcp

# 启动 MCP Server (STDIO 传输) — 两种方式
uv run paper-search-mcp              # 方式 1: 通过 uv run
.venv/Scripts/paper-search-mcp       # 方式 2: 直接调用 venv 中的脚本
```

> **注意**: `paper-search-mcp` 安装在项目的 `.venv/Scripts/` 目录中，不在系统 PATH 上。
> 直接运行 `paper-search-mcp` 会报 "无法识别" 错误，需要用上面两种方式之一。

在 Claude Desktop 的 `claude_desktop_config.json` 中配置：

**直连官方 API（不需要 base_url）：**

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "uv",
      "args": ["run", "--directory", "C:/Users/17162/Desktop/Terms/workflow", "paper-search-mcp"],
      "env": {
        "SERPAPI_API_KEY": "your-key",
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

**使用第三方代理 / 兼容 OpenAI 格式的服务：**

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "uv",
      "args": ["run", "--directory", "C:/Users/17162/Desktop/Terms/workflow", "paper-search-mcp"],
      "env": {
        "SERPAPI_API_KEY": "your-key",
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "your-key",
        "LLM_BASE_URL": "https://your-proxy.example.com/v1"
      }
    }
  }
}
```

也可以直接用 venv 中的 Python 启动（不依赖 uv）：

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "C:/Users/17162/Desktop/Terms/workflow/.venv/Scripts/python",
      "args": ["-m", "paper_search.mcp_server"],
      "env": {
        "SERPAPI_API_KEY": "your-key",
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

> 三个 provider（openai / anthropic / gemini）都支持 `LLM_BASE_URL`。官方 API 无需设置，SDK 使用默认端点。

MCP Server 提供 4 个工具：

| 工具 | 说明 |
|------|------|
| `search_papers(query, domain?, max_results?)` | 发起搜索，返回 session_id + 第一个 checkpoint（含 payload） |
| `decide(session_id, action, data?, note?)` | 对 checkpoint 做决策 (approve/edit/reject)，返回下一状态（含 payload） |
| `export_results(session_id, format?)` | 导出完成的搜索结果 (json/bibtex/markdown) |
| `get_session(session_id)` | 查询 session 状态（含 checkpoint payload） |

**Agent 交互流程：**

```
Agent                                    MCP Server
  │                                          │
  ├─ search_papers("...") ─────────────────▶│
  │                                          │── 启动后台工作流
  │◀─ {session_id, checkpoint_payload: {   ─┤
  │      intent: {...}, strategy: {...}      │
  │   }} ─────────────────────────────────── │
  │                                          │
  │  (Agent 审阅 strategy 后决策)            │
  ├─ decide(sid, "approve") ───────────────▶│
  │                                          │── 继续执行流水线
  │◀─ {checkpoint_payload: {               ─┤
  │      papers: [...], total_papers: 95,    │
  │      truncated: true, facets: {...}      │
  │   }} ─────────────────────────────────── │
  │                                          │
  │  (Agent 审阅 papers 后决策)              │
  ├─ decide(sid, "approve") ───────────────▶│
  │                                          │── 完成
  │◀─ {is_complete: true, paper_count: 95} ─┤
  │                                          │
  ├─ export_results(sid, "bibtex") ────────▶│
  │◀─ BibTeX 内容 ──────────────────────────┤
```

**Checkpoint Payload 结构：**

strategy_confirmation 返回：

```json
{
  "checkpoint_payload": {
    "intent": {
      "topic": "perovskite solar cells",
      "concepts": ["perovskite", "solar cell", "efficiency"],
      "intent_type": "survey",
      "constraints": {"max_results": 100}
    },
    "strategy": {
      "queries": [
        {"keywords": ["perovskite", "solar cell"], "boolean_query": "..."}
      ],
      "sources": ["serpapi_scholar"],
      "filters": {"max_results": 100}
    }
  },
  "checkpoint_id": "uuid:0",
  "checkpoint_kind": "strategy_confirmation"
}
```

result_review 返回（默认最多 30 篇摘要，超出截断）：

```json
{
  "checkpoint_payload": {
    "papers": [
      {
        "id": "...", "doi": "10.1234/...", "title": "...",
        "authors": ["Author1"], "year": 2024,
        "venue": "Nature", "relevance_score": 0.95,
        "tags": ["method"]
      }
    ],
    "total_papers": 95,
    "truncated": true,
    "facets": {"by_year": {"2024": 50}, "by_venue": {...}},
    "accumulated_count": 0
  },
  "checkpoint_id": "uuid:0",
  "checkpoint_kind": "result_review"
}
```

### 4. Dev CLI (开发调试)

最小化命令行入口，用于快速测试：

```bash
python -m paper_search "perovskite solar cells"
```

输出 Markdown 格式的结果表格。自动审批所有 checkpoint。

## 导出格式

### JSON

完整的结构化数据，包含论文、元数据和分面统计：

```python
from paper_search import export_json
json_str = export_json(results)  # indent=2
```

### BibTeX

可直接导入 LaTeX 的参考文献格式：

```python
from paper_search import export_bibtex
bibtex_str = export_bibtex(results)
```

输出示例：

```bibtex
@article{wang_2023_perovskite,
  author = {Wang Lei and Zhang Wei},
  title = {{Perovskite Solar Cells}},
  year = {2023},
  journal = {Nature Energy},
  doi = {10.1234/test},
}
```

### Markdown

表格格式，适合展示和分享：

```python
from paper_search import export_markdown
md_str = export_markdown(results)
```

输出示例：

```
| # | Title | Authors | Year | Venue | Score |
|---|-------|---------|------|-------|-------|
| 1 | Perovskite Solar Cells | Wang Lei, Zhang Wei | 2023 | Nature Energy | 0.95 |
```

## 核心数据模型

```python
# 论文
class Paper:
    id: str
    title: str
    authors: list[Author]      # Author(name, author_id?)
    year: int | None
    venue: str | None
    doi: str | None
    source: str                 # 来源 (如 "serpapi_scholar")
    relevance_score: float      # 0.0 ~ 1.0
    relevance_reason: str
    tags: list[PaperTag]        # method/review/empirical/theoretical/dataset
    citation_count: int
    full_text_url: str | None

# 搜索结果集合
class PaperCollection:
    metadata: SearchMetadata    # 查询信息、策略、总数
    papers: list[Paper]         # 论文列表 (按相关性排序)
    facets: Facets              # 分面: by_year, by_venue, top_authors, key_themes

# 搜索策略
class SearchStrategy:
    queries: list[SearchQuery]  # 布尔查询列表
    sources: list[str]          # 搜索源列表
    filters: SearchConstraints  # 年份范围、语言等

# 解析后的意图
class ParsedIntent:
    topic: str                  # 研究主题
    concepts: list[str]         # 核心概念
    intent_type: IntentType     # survey/method/dataset/baseline
    constraints: SearchConstraints
```

## 研究领域

系统支持领域特化的提示词模板：

- **`general`** — 通用学术搜索 (默认)
- **`materials_science`** — 材料科学领域，包含专业术语同义词映射和领域知识

通过 `DOMAIN` 环境变量或 `config.domain` 参数配置。

## 运行测试

```bash
uv run pytest tests/ -v
```

当前共 195 个测试用例，覆盖全部模块。

## 项目结构

```
src/paper_search/
├── __init__.py          # 公共 API: search(), export_*
├── __main__.py          # Dev CLI 入口
├── config.py            # 配置加载 (.env)
├── export.py            # 导出工具 (JSON/BibTeX/Markdown)
├── mcp_server.py        # MCP Server (4 tools)
├── models.py            # Pydantic 数据模型
├── llm/                 # LLM 提供商
│   ├── openai_provider.py
│   ├── claude_provider.py
│   ├── gemini_provider.py
│   ├── factory.py       # 提供商工厂
│   └── json_utils.py    # JSON 提取工具
├── prompts/             # 提示词模板
│   ├── intent_parsing.py
│   ├── query_building.py
│   ├── relevance_scoring.py
│   ├── dedup.py
│   └── domains/         # 领域特化配置
├── skills/              # 核心技能
│   ├── intent_parser.py
│   ├── query_builder.py
│   ├── searcher.py
│   ├── deduplicator.py
│   ├── relevance_scorer.py
│   └── result_organizer.py
├── sources/             # 搜索源适配器
│   └── serpapi_scholar.py
└── workflow/            # 工作流编排
    ├── engine.py        # SearchWorkflow 主引擎
    ├── checkpoints.py   # Checkpoint/Decision 模型
    └── state.py         # 迭代状态管理
```

## 依赖

- Python >= 3.11
- pydantic >= 2.0
- httpx
- openai / anthropic / google-genai (LLM 提供商)
- google-search-results (SerpAPI)
- mcp >= 1.22 (可选，MCP Server)

## 架构映射：本次优化改动

以下按源码架构说明本次改动的职责与作用，便于对照代码快速定位：

### 1) `src/paper_search/mcp_server.py`（MCP 会话与人机交互）
- 修复 `decide()` 竞态：提交决策后等待“下一 checkpoint / 完成 / 超时”，避免返回旧的 `strategy_confirmation`。
- 新增 checkpoint 签名（`run_id + iteration + kind`）用于判断是否真正进入下一状态。
- 会话状态新增进度字段：`phase`、`phase_details`、`phase_updated_at`、`elapsed_s`。
- 当没有 pending checkpoint 但流程仍在运行时，`get_session` 返回 processing 摘要，避免“看起来卡住”。

### 2) `src/paper_search/workflow/engine.py`（主编排引擎）
- 新增 `progress_reporter` 回调，将阶段进度上报给 MCP 会话层。
- 覆盖阶段：`intent_parsing`、`query_building`、`searching`、`deduplicating`、`scoring`、`organizing`、`waiting_checkpoint`、`iterating`、`completed`。
- `from_config()` 接入性能相关配置，并传递给 `Deduplicator` 与 `RelevanceScorer`。

### 3) `src/paper_search/skills/relevance_scorer.py`（相关性评分）
- 从串行 batch 改为受控并发 batch 评分，保持输出顺序不变。
- 新增参数 `max_concurrency`，用于限制并发请求上限，降低总耗时。

### 4) `src/paper_search/skills/deduplicator.py`（去重）
- 增加 `enable_llm_pass` 开关，可按环境关闭语义去重。
- 增加 `llm_max_candidates` 阈值，候选过大时跳过 LLM pass，避免大结果集长尾耗时。
- 算法去重（DOI/result_id/url/title）仍保持第一阶段默认执行。

### 5) `src/paper_search/config.py` 与 `.env.example`（配置层）
- 增加运行调优参数：
  - `RELEVANCE_BATCH_SIZE`
  - `RELEVANCE_MAX_CONCURRENCY`
  - `DEDUP_ENABLE_LLM_PASS`
  - `DEDUP_LLM_MAX_CANDIDATES`
  - `MCP_DECIDE_WAIT_TIMEOUT_S`
  - `MCP_POLL_INTERVAL_S`
- `load_config()` 统一读取并注入到 workflow 与 MCP 会话策略。

### 6) 回归测试覆盖
- `tests/test_mcp_server.py`
  - `decide()` 不返回旧 checkpoint（单调推进）验证。
  - 会话进度字段返回验证。
  - checkpoint payload 序列化形状与字段完整性验证。
  - payload JSON 可序列化验证。
  - result payload 截断行为验证。
  - payload 类型不匹配时的 TypeError 验证。
  - `get_session` / `decide` 返回 `checkpoint_payload` 与 `checkpoint_id` 验证。
- `tests/test_skills/test_relevance_scorer.py`
  - 并发评分行为验证。
- `tests/test_skills/test_deduplicator.py`
  - LLM 去重阈值与开关行为验证。

### 7) `src/paper_search/mcp_server.py` — Checkpoint Payload 回传（v0.1.3）

**问题**：MCP 客户端在 checkpoint 阶段只收到元数据（`checkpoint_kind`、`summary`），无法看到待审阅的策略或论文内容，人工介入形同虚设。

**方案**：新增 `_serialize_checkpoint_payload()` 辅助函数，在 `_session_state()` 中将 payload 序列化后注入响应。

实现护栏：
- 不用 `assert` 做运行时校验 —— 使用 `raise TypeError(...)` + 明确错误信息。
- 不写死 `else = ResultPayload` —— `if/elif/else` 三分支，未知 checkpoint kind 返回 `_warning`。
- `model_dump()` 统一使用 `mode="json"`，避免 enum/datetime 等非原生 JSON 类型穿透。
- Result payload 截断保护 —— `_RESULT_PAYLOAD_MAX_PAPERS=30`，超出时 `truncated=true` + `total_papers` 标注实际总量。
- papers 摘要包含 `doi` 字段，避免下游 agent 二次抓取。
- 会话状态新增 `checkpoint_id`（`run_id:iteration`），为客户端提供稳定的代次标识。

影响范围：
- `search_papers` / `decide` / `get_session` 三个工具自动获益（均通过 `_session_state()` 返回）。
- `export_results` 不受影响。
- 新增字段均为追加，向后兼容。

## License

MIT
