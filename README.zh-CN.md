# paper-search

基于 AI 的学术论文搜索工作流系统。用自然语言描述你的研究需求，系统自动完成意图解析、查询构建、多源搜索、去重、相关性评分和结果整理。

[English](./README.md) | **中文**

## 特性

- **自然语言输入** - 用日常语言描述你要找的论文
- **多 LLM 支持** - OpenAI、Anthropic Claude、Google Gemini 统一接口
- **人机协作** - 检查点机制，支持策略审批和结果审阅
- **迭代优化** - 拒绝或编辑结果可触发带反馈的精细化搜索
- **领域特化** - 内置材料科学领域术语支持
- **多种接口** - Python 库、命令行、MCP Server（AI Agent 集成）
- **导出格式** - JSON、BibTeX、Markdown

## 系统架构

```
用户查询（自然语言）
    |
    v
+----------------+
|  IntentParser  |  <- LLM 解析研究意图
+-------+--------+
        v
+----------------+     +----------------------------+
|  QueryBuilder  | --> | 检查点 1：策略确认          | （可选）
+-------+--------+     +----------------------------+
        v
+----------------+
|    Searcher    |  <- SerpAPI Google Scholar 搜索
+-------+--------+
        v
+----------------+
|  Deduplicator  |  <- DOI / URL / 标题去重 + LLM 语义匹配
+-------+--------+
        v
+------------------+
| RelevanceScorer  |  <- LLM 批量评分，并发控制
+-------+----------+
        v
+------------------+     +----------------------------+
| ResultOrganizer  | --> | 检查点 2：结果审阅          | （必需）
+-------+----------+     +----------------------------+
        v
  PaperCollection（最终结果）
```

在结果审阅检查点，可以选择**拒绝**或**编辑**来触发新一轮搜索迭代。用户反馈会传递给 QueryBuilder 以优化下一轮查询。

## 安装

```bash
git clone <repo-url>
cd workflow

# 使用 uv 安装依赖
uv sync

# 如需 MCP Server 支持
uv sync --extra mcp
```

**环境要求：** Python >= 3.11

## 配置

将 `.env.example` 复制为 `.env` 并填入 API 密钥：

```bash
cp .env.example .env
```

### 必需配置

| 变量 | 说明 | 示例 |
|------|------|------|
| `SERPAPI_API_KEY` | SerpAPI 密钥（Google Scholar） | `abc123...` |
| `LLM_PROVIDER` | LLM 提供商 | `openai` / `anthropic` / `gemini` |
| `OPENAI_API_KEY` | OpenAI API 密钥（provider=openai 时） | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API 密钥（provider=anthropic 时） | `sk-ant-...` |
| `GOOGLE_API_KEY` | Google API 密钥（provider=gemini 时） | `AIza...` |

### 可选配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_MODEL` | 提供商默认 | 模型名称 |
| `LLM_TEMPERATURE` | `0.0` | LLM 温度参数 |
| `LLM_MAX_TOKENS` | `4096` | 最大输出 token 数 |
| `LLM_BASE_URL` | - | 自定义端点（兼容 OpenAI 的代理） |
| `DEFAULT_MAX_RESULTS` | `100` | 每次搜索最大结果数 |
| `DOMAIN` | `general` | 研究领域（`general` 或 `materials_science`） |

### 性能调优

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RELEVANCE_BATCH_SIZE` | `10` | 每批评分的论文数 |
| `RELEVANCE_MAX_CONCURRENCY` | `3` | 最大并发评分批次 |
| `DEDUP_ENABLE_LLM_PASS` | `true` | 启用 LLM 语义去重 |
| `DEDUP_LLM_MAX_CANDIDATES` | `60` | 候选数超过此值时跳过 LLM 去重 |
| `MCP_DECIDE_WAIT_TIMEOUT_S` | `15.0` | `decide()` 等待下一状态的最大秒数 |
| `MCP_POLL_INTERVAL_S` | `0.05` | MCP 会话轮询间隔（秒） |

## 使用方式

### Python 库

一行代码搜索（自动批准所有检查点）：

```python
import asyncio
from paper_search import search, export_markdown, export_json, export_bibtex

async def main():
    results = await search("钙钛矿太阳能电池效率 2020-2024")

    print(export_markdown(results))   # Markdown 表格
    json_str = export_json(results)   # 结构化 JSON
    bib_str = export_bibtex(results)  # LaTeX 用 BibTeX

asyncio.run(main())
```

自定义配置：

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

访问结果数据：

```python
results = await search("石墨烯热导率")

print(f"找到 {results.metadata.total_found} 篇论文")

for paper in results.papers:
    print(f"[{paper.relevance_score:.2f}] {paper.title}")
    print(f"  作者: {', '.join(a.name for a in paper.authors)}")
    print(f"  年份: {paper.year}  期刊: {paper.venue}")
    if paper.doi:
        print(f"  DOI: {paper.doi}")

# 统计分面
print(f"按年份: {results.facets.by_year}")
print(f"按期刊: {results.facets.by_venue}")
print(f"高频作者: {results.facets.top_authors}")
print(f"关键主题: {results.facets.key_themes}")
```

### 自定义检查点处理器

实现人机协作控制：

```python
from paper_search.config import load_config
from paper_search.workflow import SearchWorkflow
from paper_search.workflow.checkpoints import (
    Checkpoint, CheckpointKind, Decision, DecisionAction,
)

class MyHandler:
    async def handle(self, checkpoint: Checkpoint) -> Decision:
        if checkpoint.kind == CheckpointKind.STRATEGY_CONFIRMATION:
            strategy = checkpoint.payload.strategy
            print(f"策略: {len(strategy.queries)} 条查询")
            for q in strategy.queries:
                print(f"  - {q.boolean_query}")
            return Decision(action=DecisionAction.APPROVE)

        elif checkpoint.kind == CheckpointKind.RESULT_REVIEW:
            collection = checkpoint.payload.collection
            print(f"找到 {len(collection.papers)} 篇论文")
            # APPROVE 接受 / REJECT 或 EDIT 触发迭代
            return Decision(action=DecisionAction.APPROVE)

config = load_config()
wf = SearchWorkflow.from_config(config, checkpoint_handler=MyHandler())
results = await wf.run("高熵合金力学性能")
```

### MCP Server

将搜索功能暴露为 MCP 工具，供 Claude 等 AI Agent 调用：

```bash
uv sync --extra mcp

# 启动 MCP Server（STDIO 传输）
uv run paper-search-mcp
```

Claude Desktop 配置（`claude_desktop_config.json`）：

```json
{
  "mcpServers": {
    "paper-search": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/workflow", "paper-search-mcp"],
      "env": {
        "SERPAPI_API_KEY": "your-key",
        "LLM_PROVIDER": "openai",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

使用 OpenAI 兼容代理时，在 `env` 中添加 `"LLM_BASE_URL": "https://your-proxy.example.com/v1"`。

**MCP 工具：**

| 工具 | 说明 |
|------|------|
| `search_papers(query, domain?, max_results?)` | 启动搜索，返回 session_id + 首个检查点 |
| `decide(session_id, action, data?, note?)` | 提交检查点决策（approve/edit/reject） |
| `export_results(session_id, format?)` | 导出结果（json/bibtex/markdown） |
| `get_session(session_id)` | 查询会话状态和进度 |

**Agent 交互流程：**

```
Agent                                    MCP Server
  |                                          |
  +- search_papers("...") ------------------>|
  |                                          |-- 启动后台工作流
  |<- {session_id, checkpoint_payload: {   --|
  |      intent: {...}, strategy: {...}      |
  |   }} ----------------------------------- |
  |                                          |
  |  （Agent 审阅策略，做出决策）              |
  +- decide(sid, "approve") ---------------->|
  |                                          |-- 管线继续执行
  |<- {checkpoint_payload: {               --|
  |      papers: [...], facets: {...}        |
  |   }} ----------------------------------- |
  |                                          |
  |  （Agent 审阅结果，做出决策）              |
  +- decide(sid, "approve") ---------------->|
  |                                          |-- 完成
  |<- {is_complete: true} ------------------|
  |                                          |
  +- export_results(sid, "bibtex") --------->|
  |<- BibTeX 内容 ------------------------- |
```

### 命令行

用于快速测试的最小命令行入口（自动批准所有检查点）：

```bash
python -m paper_search "钙钛矿太阳能电池"
```

## 导出格式

### JSON

包含论文、元数据和统计分面的完整结构化数据：

```python
from paper_search import export_json
json_str = export_json(results)
```

### BibTeX

LaTeX 引用格式：

```python
from paper_search import export_bibtex
bibtex_str = export_bibtex(results)
```

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

表格格式，方便分享：

```python
from paper_search import export_markdown
md_str = export_markdown(results)
```

```
| # | Title | Authors | Year | Venue | Score |
|---|-------|---------|------|-------|-------|
| 1 | Perovskite Solar Cells | Wang Lei, Zhang Wei | 2023 | Nature Energy | 0.95 |
```

## 数据模型

```python
class Paper:
    id: str
    title: str
    authors: list[Author]       # Author(name, author_id?)
    year: int | None
    venue: str | None
    doi: str | None
    source: str                  # 如 "serpapi_scholar"
    relevance_score: float       # 0.0 ~ 1.0
    relevance_reason: str
    tags: list[PaperTag]         # method / review / empirical / theoretical / dataset
    citation_count: int
    full_text_url: str | None

class PaperCollection:
    metadata: SearchMetadata     # 查询信息、策略、总数
    papers: list[Paper]          # 按相关性排序
    facets: Facets               # by_year, by_venue, top_authors, key_themes

class SearchStrategy:
    queries: list[SearchQuery]   # 布尔查询列表
    sources: list[str]
    filters: SearchConstraints   # 年份范围、语言等

class ParsedIntent:
    topic: str
    concepts: list[str]
    intent_type: IntentType      # survey / method / dataset / baseline
    constraints: SearchConstraints
```

## 领域特化

系统支持领域专用的提示词模板：

- **`general`** - 通用学术搜索（默认）
- **`materials_science`** - 材料科学领域，包含专业术语映射和领域知识

通过 `DOMAIN` 环境变量或 `config.domain` 参数配置。

## 项目结构

```
src/paper_search/
├── __init__.py              # 公共 API: search(), export_*
├── __main__.py              # 命令行入口
├── config.py                # 配置管理（.env 加载）
├── export.py                # 导出（JSON / BibTeX / Markdown）
├── mcp_server.py            # MCP Server（4 个工具）
├── models.py                # Pydantic 数据模型
├── llm/                     # LLM 提供商
│   ├── base.py              # 抽象基类 LLMProvider
│   ├── openai_provider.py
│   ├── claude_provider.py
│   ├── gemini_provider.py
│   ├── factory.py           # 提供商工厂
│   ├── json_utils.py        # JSON 提取（3 步回退）
│   └── exceptions.py        # 异常层级
├── prompts/                 # 提示词模板
│   ├── intent_parsing.py
│   ├── query_building.py
│   ├── relevance_scoring.py
│   ├── dedup.py
│   └── domains/             # 领域特化
│       └── materials_science.py
├── skills/                  # 核心管线技能
│   ├── intent_parser.py     # 自然语言 -> ParsedIntent
│   ├── query_builder.py     # Intent -> SearchStrategy
│   ├── searcher.py          # Strategy -> RawPaper[]
│   ├── deduplicator.py      # 算法 + LLM 去重
│   ├── relevance_scorer.py  # 并发批量评分
│   └── result_organizer.py  # 过滤、排序、分面统计
├── sources/                 # 搜索源适配器
│   ├── base.py              # 抽象基类 SearchSource
│   ├── serpapi_scholar.py   # 通过 SerpAPI 访问 Google Scholar
│   ├── factory.py
│   └── exceptions.py
└── workflow/                # 编排层
    ├── engine.py            # SearchWorkflow（主管线）
    ├── checkpoints.py       # 检查点 / 决策模型
    └── state.py             # 迭代状态管理
```

## 测试

```bash
uv run pytest tests/ -v
```

213 项测试覆盖所有模块：数据模型、LLM 提供商、SerpAPI 适配器、全部 6 个技能、工作流引擎、检查点、导出、库 API、MCP Server 和命令行。

## 依赖

- **pydantic** >= 2.0 - 数据验证
- **httpx** - HTTP 客户端
- **python-dotenv** - 环境配置
- **openai** - OpenAI 提供商
- **anthropic** - Claude 提供商
- **google-genai** - Gemini 提供商
- **google-search-results** - SerpAPI 客户端
- **mcp** >= 1.22 - MCP Server（可选）

## 许可证

MIT
