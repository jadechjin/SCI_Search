# Design: Product Form — Library + MCP Server + Dev CLI

## Locked Constraints

| ID | Constraint | Decision |
|----|-----------|----------|
| C1 | Product hierarchy | Library (primary) > MCP (agent) > CLI (dev-only) |
| C2 | MCP SDK | Official `mcp` package v1.22+, FastMCP class |
| C3 | Tool granularity | Unified `decide` tool, maps 1:1 to Decision model |
| C4 | Export formats | JSON, BibTeX, Markdown |
| C5 | CLI scope | Minimal `__main__.py`, auto-approve, print results |
| C6 | Zero regressions | 149 existing tests must pass |
| C7 | Frozen engine | No modifications to workflow/ or skills/ |
| C8 | Async-first | All public functions async |
| C9 | Session management | asyncio.Event-based CheckpointHandler for MCP |

## File Touch List

| File | Action | Purpose |
|------|--------|---------|
| `src/paper_search/export.py` | CREATE | Export utilities (JSON, BibTeX, Markdown) |
| `src/paper_search/mcp_server.py` | CREATE | MCP server with 4 tools + session manager |
| `src/paper_search/__main__.py` | CREATE | Dev CLI entry point |
| `src/paper_search/__init__.py` | MODIFY | Add search(), export_* to public API |
| `pyproject.toml` | MODIFY | Add mcp dependency, optional group |
| `tests/test_export.py` | CREATE | Export function tests |
| `tests/test_mcp_server.py` | CREATE | MCP server + session tests |
| `tests/test_main.py` | CREATE | CLI entry point tests |

## Component Design

### 1. Export Utilities (`export.py`)

```python
from paper_search.models import PaperCollection

def export_json(collection: PaperCollection, indent: int = 2) -> str:
    """Serialize collection to JSON string."""
    return collection.model_dump_json(indent=indent)

def export_bibtex(collection: PaperCollection) -> str:
    """Generate BibTeX entries for all papers."""
    entries = []
    for paper in collection.papers:
        key = _make_bibtex_key(paper)
        entry = _format_bibtex_entry(paper, key)
        entries.append(entry)
    return "\n\n".join(entries)

def export_markdown(collection: PaperCollection) -> str:
    """Generate Markdown table of papers."""
    header = "| # | Title | Authors | Year | Venue | Score |"
    sep = "|---|-------|---------|------|-------|-------|"
    rows = []
    for i, paper in enumerate(collection.papers, 1):
        authors = _format_authors_short(paper.authors)
        rows.append(f"| {i} | {paper.title} | {authors} | {paper.year or '-'} | {paper.venue or '-'} | {paper.relevance_score:.2f} |")
    return "\n".join([header, sep] + rows)
```

BibTeX key generation: `firstauthor_year_firstword` (e.g., `wang_2023_perovskite`).
Special character escaping: `&` → `\&`, `%` → `\%`, `_` → `\_`, `#` → `\#`.
Missing fields: omit from entry (BibTeX allows optional fields).

### 2. Library Public API (`__init__.py`)

```python
from paper_search.models import Paper, PaperCollection, ParsedIntent, SearchStrategy
from paper_search.export import export_json, export_bibtex, export_markdown

async def search(
    query: str,
    config: AppConfig | None = None,
    max_results: int = 100,
    domain: str = "general",
) -> PaperCollection:
    """One-line convenience function. Auto-approve, no checkpoints."""
    from paper_search.config import load_config
    from paper_search.workflow import SearchWorkflow
    cfg = config or load_config()
    wf = SearchWorkflow.from_config(cfg)
    return await wf.run(query)

__all__ = [
    "Paper", "PaperCollection", "ParsedIntent", "SearchStrategy",
    "search",
    "export_json", "export_bibtex", "export_markdown",
]
```

### 3. MCP Server (`mcp_server.py`)

#### 3.1 Session Architecture

```python
import asyncio
import uuid
from dataclasses import dataclass, field
from paper_search.workflow.checkpoints import Checkpoint, Decision, DecisionAction

@dataclass
class WorkflowSession:
    session_id: str
    query: str
    _handler: "MCPCheckpointHandler"
    _task: asyncio.Task | None = None
    result: PaperCollection | None = None
    error: str | None = None
    is_complete: bool = False

class MCPCheckpointHandler:
    """CheckpointHandler that pauses workflow at checkpoints, resumes on decide()."""

    def __init__(self):
        self._checkpoint_ready = asyncio.Event()
        self._decision_ready = asyncio.Event()
        self._current_checkpoint: Checkpoint | None = None
        self._decision: Decision | None = None

    async def handle(self, checkpoint: Checkpoint) -> Decision:
        self._current_checkpoint = checkpoint
        self._checkpoint_ready.set()    # Signal: checkpoint available
        self._decision_ready.clear()     # Reset: wait for decision
        await self._decision_ready.wait()  # Block until decide() is called
        self._checkpoint_ready.clear()
        return self._decision

    def set_decision(self, decision: Decision) -> None:
        self._decision = decision
        self._decision_ready.set()  # Unblock handle()

    @property
    def current_checkpoint(self) -> Checkpoint | None:
        return self._current_checkpoint

    @property
    def has_pending_checkpoint(self) -> bool:
        return self._checkpoint_ready.is_set()

class SessionManager:
    def __init__(self):
        self._sessions: dict[str, WorkflowSession] = {}

    def create(self, query: str, config: AppConfig) -> str: ...
    def get(self, session_id: str) -> WorkflowSession | None: ...
    async def decide(self, session_id: str, decision: Decision) -> dict: ...
    def cleanup(self, session_id: str) -> None: ...
```

#### 3.2 MCP Tool Definitions

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("paper-search")

@mcp.tool()
async def search_papers(
    query: str,
    domain: str = "general",
    max_results: int = 100,
) -> str:
    """Search academic papers. Returns session_id and first checkpoint (or results if no checkpoint handler needed).

    Args:
        query: Natural language search query (e.g., "perovskite solar cells efficiency improvement")
        domain: Research domain - "general" or "materials_science"
        max_results: Maximum number of results to return
    """
    # Creates session, starts workflow in background task
    # Waits for first checkpoint or completion
    # Returns JSON with session_id + checkpoint/results

@mcp.tool()
async def decide(
    session_id: str,
    action: str,
    data: dict | None = None,
    note: str | None = None,
) -> str:
    """Make a decision on a pending checkpoint in a paper search session.

    Args:
        session_id: Session ID from search_papers
        action: Decision action - "approve", "edit", or "reject"
        data: Optional revised data (SearchStrategy dict for strategy checkpoint, UserFeedback dict for result review)
        note: Optional note explaining the decision
    """
    # Validates action, creates Decision, calls session_manager.decide()
    # Returns next checkpoint or final results

@mcp.tool()
async def export_results(
    session_id: str,
    format: str = "markdown",
) -> str:
    """Export search results in the specified format.

    Args:
        session_id: Session ID from a completed search
        format: Output format - "json", "bibtex", or "markdown"
    """

@mcp.tool()
async def get_session(session_id: str) -> str:
    """Get current state of a search session (for debugging).

    Args:
        session_id: Session ID to inspect
    """
```

#### 3.3 Server Entry Point

```python
def main():
    mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
```

### 4. Dev CLI (`__main__.py`)

```python
"""Dev CLI for paper-search. Usage: python -m paper_search "query" """
import asyncio
import sys
from paper_search import search, export_markdown
from paper_search.config import load_config

def main():
    if len(sys.argv) < 2:
        print("Usage: python -m paper_search <query>", file=sys.stderr)
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    config = load_config()
    result = asyncio.run(_run(query, config))
    print(export_markdown(result))

async def _run(query, config):
    return await search(query, config=config)

if __name__ == "__main__":
    main()
```

### 5. Dependency Changes (`pyproject.toml`)

```toml
[project.optional-dependencies]
mcp = ["mcp>=1.22"]

[project.scripts]
paper-search-mcp = "paper_search.mcp_server:main"
```

The `mcp` dependency is optional — library users don't need it.

### 6. Edge Cases

| Case | Handling |
|------|----------|
| search_papers called with invalid config | Return error in tool response, no session created |
| decide called with unknown session_id | Return tool error "Session not found" |
| decide called when no checkpoint pending | Return tool error "No pending checkpoint" |
| decide called after session complete | Return tool error "Session already complete" |
| export_results on incomplete session | Return tool error "Session not complete" |
| Session timeout (30min idle) | Background cleanup task removes stale sessions |
| Workflow raises exception during run | Capture in session.error, mark complete, return error on next decide |
| Empty PaperCollection for export | export_json → valid JSON with empty papers array; export_bibtex → empty string; export_markdown → header only |
| Paper with no authors for BibTeX | Use "Unknown" as author |
| Paper title with special BibTeX chars | Escape &, %, _, #, {, } |
| Concurrent decide calls on same session | Second call gets "checkpoint already being processed" error |
