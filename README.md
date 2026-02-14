# paper-search

AI-powered academic paper search workflow system. Describe your research needs in natural language, and the system automatically handles intent parsing, query construction, multi-source search, deduplication, relevance scoring, and result organization.

**English** | [中文](./README.zh-CN.md)

## Features

- **Natural Language Input** - Describe what you're looking for in plain language
- **Multi-LLM Support** - OpenAI, Anthropic Claude, Google Gemini with unified interface
- **Human-in-the-Loop** - Checkpoint system for strategy approval and result review
- **Iterative Refinement** - Reject or edit results to trigger refined searches with feedback
- **Domain Specialization** - Built-in support for materials science terminology
- **Multiple Interfaces** - Python library, CLI, MCP server for AI agent integration
- **Export Formats** - JSON, BibTeX, Markdown

## Architecture

```
User Query (natural language)
    |
    v
+----------------+
|  IntentParser  |  <- LLM parses research intent
+-------+--------+
        v
+----------------+     +----------------------------+
|  QueryBuilder  | --> | Checkpoint 1: Strategy     | (optional)
+-------+--------+     +----------------------------+
        v
+----------------+
|    Searcher    |  <- SerpAPI Google Scholar
+-------+--------+
        v
+----------------+
|  Deduplicator  |  <- DOI / URL / title dedup + LLM semantic matching
+-------+--------+
        v
+------------------+
| RelevanceScorer  |  <- LLM batch scoring with controlled concurrency
+-------+----------+
        v
+------------------+     +----------------------------+
| ResultOrganizer  | --> | Checkpoint 2: Result Review | (required)
+-------+----------+     +----------------------------+
        v
  PaperCollection (final results)
```

At the result review checkpoint, you can **reject** or **edit** to trigger a new search iteration. User feedback is passed to QueryBuilder to refine the next round.

## Installation

```bash
git clone <repo-url>
cd workflow

# Install dependencies with uv
uv sync

# For MCP server support
uv sync --extra mcp
```

**Requirements:** Python >= 3.11

## Configuration

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `SERPAPI_API_KEY` | SerpAPI key (Google Scholar) | `abc123...` |
| `LLM_PROVIDER` | LLM provider | `openai` / `anthropic` / `gemini` |
| `OPENAI_API_KEY` | OpenAI API key (when provider=openai) | `sk-...` |
| `ANTHROPIC_API_KEY` | Anthropic API key (when provider=anthropic) | `sk-ant-...` |
| `GOOGLE_API_KEY` | Google API key (when provider=gemini) | `AIza...` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_MODEL` | provider default | Model name |
| `LLM_TEMPERATURE` | `0.0` | LLM temperature |
| `LLM_MAX_TOKENS` | `4096` | Max output tokens |
| `LLM_BASE_URL` | - | Custom endpoint (OpenAI-compatible proxy) |
| `DEFAULT_MAX_RESULTS` | `100` | Max results per search |
| `SERPAPI_MAX_CALLS` | - | Max SerpAPI requests per workflow run (empty = unlimited) |
| `DOMAIN` | `general` | Research domain (`general` or `materials_science`) |

### Performance Tuning

| Variable | Default | Description |
|----------|---------|-------------|
| `RELEVANCE_BATCH_SIZE` | `10` | Papers per scoring batch |
| `RELEVANCE_MAX_CONCURRENCY` | `3` | Max concurrent scoring batches |
| `DEDUP_ENABLE_LLM_PASS` | `true` | Enable LLM semantic dedup |
| `DEDUP_LLM_MAX_CANDIDATES` | `60` | Skip LLM dedup if candidates exceed this |
| `MCP_DECIDE_WAIT_TIMEOUT_S` | `15.0` | Max seconds to wait for next state in `decide()` |
| `MCP_POLL_INTERVAL_S` | `0.05` | MCP session poll interval (seconds) |

## Usage

### Python Library

One-line search with auto-approval of all checkpoints:

```python
import asyncio
from paper_search import search, export_markdown, export_json, export_bibtex

async def main():
    results = await search("perovskite solar cells efficiency 2020-2024")

    print(export_markdown(results))   # Markdown table
    json_str = export_json(results)   # Structured JSON
    bib_str = export_bibtex(results)  # BibTeX for LaTeX

asyncio.run(main())
```

Custom configuration:

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

results = await search("lithium-ion battery cathode materials", config=config)
```

Accessing result data:

```python
results = await search("graphene thermal conductivity")

print(f"Found {results.metadata.total_found} papers")

for paper in results.papers:
    print(f"[{paper.relevance_score:.2f}] {paper.title}")
    print(f"  Authors: {', '.join(a.name for a in paper.authors)}")
    print(f"  Year: {paper.year}  Venue: {paper.venue}")
    if paper.doi:
        print(f"  DOI: {paper.doi}")

# Facet statistics
print(f"By year: {results.facets.by_year}")
print(f"By venue: {results.facets.by_venue}")
print(f"Top authors: {results.facets.top_authors}")
print(f"Key themes: {results.facets.key_themes}")
```

### Custom Checkpoint Handler

For human-in-the-loop control during search:

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
            print(f"Strategy: {len(strategy.queries)} queries")
            for q in strategy.queries:
                print(f"  - {q.boolean_query}")
            return Decision(action=DecisionAction.APPROVE)

        elif checkpoint.kind == CheckpointKind.RESULT_REVIEW:
            collection = checkpoint.payload.collection
            print(f"Found {len(collection.papers)} papers")
            # APPROVE to accept, REJECT/EDIT to iterate
            return Decision(action=DecisionAction.APPROVE)

config = load_config()
wf = SearchWorkflow.from_config(config, checkpoint_handler=MyHandler())
results = await wf.run("high-entropy alloys mechanical properties")
```

### MCP Server

Expose search as MCP tools for Claude and other AI agents:

```bash
uv sync --extra mcp

# Start MCP server (STDIO transport)
uv run paper-search-mcp
```

Claude Desktop configuration (`claude_desktop_config.json`):

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

For OpenAI-compatible proxies, add `"LLM_BASE_URL": "https://your-proxy.example.com/v1"` to `env`.

**MCP Tools:**

| Tool | Description |
|------|-------------|
| `search_papers(query, domain?, max_results?)` | Start search, returns session_id + first checkpoint |
| `decide(session_id, action, data?, note?)` | Submit checkpoint decision (approve/edit/reject) |
| `export_results(session_id, format?)` | Export results (json/bibtex/markdown) |
| `get_session(session_id)` | Query session status and progress |

**Agent interaction flow:**

```
Agent                                    MCP Server
  |                                          |
  +- search_papers("...") ------------------>|
  |                                          |-- starts background workflow
  |<- {session_id, checkpoint_payload: {   --|
  |      intent: {...}, strategy: {...}      |
  |   }} ----------------------------------- |
  |                                          |
  |  (Agent reviews strategy, decides)       |
  +- decide(sid, "approve") ---------------->|
  |                                          |-- pipeline continues
  |<- {checkpoint_payload: {               --|
  |      papers: [...], facets: {...}        |
  |   }} ----------------------------------- |
  |                                          |
  |  (Agent reviews results, decides)        |
  +- decide(sid, "approve") ---------------->|
  |                                          |-- complete
  |<- {is_complete: true} ------------------|
  |                                          |
  +- export_results(sid, "bibtex") --------->|
  |<- BibTeX content ---------------------- |
```

### CLI

Minimal command-line entry point for quick testing (auto-approves all checkpoints):

```bash
python -m paper_search "perovskite solar cells"
```

## Export Formats

### JSON

Full structured data with papers, metadata, and facet statistics:

```python
from paper_search import export_json
json_str = export_json(results)
```

### BibTeX

Reference format for LaTeX:

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

Table format for sharing:

```python
from paper_search import export_markdown
md_str = export_markdown(results)
```

```
| # | Title | Authors | Year | Venue | Score |
|---|-------|---------|------|-------|-------|
| 1 | Perovskite Solar Cells | Wang Lei, Zhang Wei | 2023 | Nature Energy | 0.95 |
```

## Data Models

```python
class Paper:
    id: str
    title: str
    authors: list[Author]       # Author(name, author_id?)
    year: int | None
    venue: str | None
    doi: str | None
    source: str                  # e.g. "serpapi_scholar"
    relevance_score: float       # 0.0 ~ 1.0
    relevance_reason: str
    tags: list[PaperTag]         # method / review / empirical / theoretical / dataset
    citation_count: int
    full_text_url: str | None

class PaperCollection:
    metadata: SearchMetadata     # query info, strategy, total count
    papers: list[Paper]          # sorted by relevance
    facets: Facets               # by_year, by_venue, top_authors, key_themes

class SearchStrategy:
    queries: list[SearchQuery]   # boolean query list
    sources: list[str]
    filters: SearchConstraints   # year range, language, etc.

class ParsedIntent:
    topic: str
    concepts: list[str]
    intent_type: IntentType      # survey / method / dataset / baseline
    constraints: SearchConstraints
```

## Domain Specialization

The system supports domain-specific prompt templates:

- **`general`** - General academic search (default)
- **`materials_science`** - Materials science with specialized terminology mapping and domain knowledge

Configure via `DOMAIN` environment variable or `config.domain` parameter.

Custom domain terminology can also be loaded from `.env` using the same variable name as `DOMAIN`:

```env
DOMAIN=makesi
makesi=makesi is a metallurgy-focused research domain; key terms include HEA, phase diagram, diffusion, CALPHAD
```

## Project Structure

```
src/paper_search/
├── __init__.py              # Public API: search(), export_*
├── __main__.py              # CLI entry point
├── config.py                # Configuration (.env loading)
├── export.py                # Export (JSON / BibTeX / Markdown)
├── mcp_server.py            # MCP Server (4 tools)
├── models.py                # Pydantic data models
├── llm/                     # LLM providers
│   ├── base.py              # Abstract LLMProvider
│   ├── openai_provider.py
│   ├── claude_provider.py
│   ├── gemini_provider.py
│   ├── factory.py           # Provider factory
│   ├── json_utils.py        # JSON extraction (3-step fallback)
│   └── exceptions.py        # Error hierarchy
├── prompts/                 # Prompt templates
│   ├── intent_parsing.py
│   ├── query_building.py
│   ├── relevance_scoring.py
│   ├── dedup.py
│   └── domains/             # Domain specialization
│       └── materials_science.py
├── skills/                  # Core pipeline skills
│   ├── intent_parser.py     # NL -> ParsedIntent
│   ├── query_builder.py     # Intent -> SearchStrategy
│   ├── searcher.py          # Strategy -> RawPaper[]
│   ├── deduplicator.py      # Algorithmic + LLM dedup
│   ├── relevance_scorer.py  # Concurrent batch scoring
│   └── result_organizer.py  # Filter, sort, facets
├── sources/                 # Search source adapters
│   ├── base.py              # Abstract SearchSource
│   ├── serpapi_scholar.py   # Google Scholar via SerpAPI
│   ├── factory.py
│   └── exceptions.py
└── workflow/                # Orchestration
    ├── engine.py            # SearchWorkflow (main pipeline)
    ├── checkpoints.py       # Checkpoint / Decision models
    └── state.py             # Iteration state management
```

## Testing

```bash
uv run pytest tests/ -v
```

213 tests covering all modules: models, LLM providers, SerpAPI adapter, all 6 skills, workflow engine, checkpoints, export, library API, MCP server, and CLI.

## Dependencies

- **pydantic** >= 2.0 - Data validation
- **httpx** - HTTP client
- **Python-dotenv** - Environment configuration
- **openai** - OpenAI provider
- **anthropic** - Claude provider
- **google-genai** - Gemini provider
- **google-search-results** - SerpAPI client
- **mcp** >= 1.22 - MCP server (optional)

## License

MIT
