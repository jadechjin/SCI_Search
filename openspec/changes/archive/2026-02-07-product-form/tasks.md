# Tasks: Product Form — Library + MCP Server + Dev CLI

All decisions are locked in `design.md`. Each task is pure mechanical execution.

---

## Task 1: Create export utilities [DONE]

**File**: `src/paper_search/export.py` (NEW)

Imports:
```python
from __future__ import annotations
import re
from paper_search.models import Paper, PaperCollection
```

Implement 3 public functions + private helpers:

1. `export_json(collection: PaperCollection, indent: int = 2) -> str`:
   - Return `collection.model_dump_json(indent=indent)`

2. `export_bibtex(collection: PaperCollection) -> str`:
   - If no papers, return `""`
   - For each paper, generate key via `_make_bibtex_key(paper, seen_keys)`
   - Format entry via `_format_bibtex_entry(paper, key)`
   - Join with `"\n\n"`

3. `export_markdown(collection: PaperCollection) -> str`:
   - Header: `"| # | Title | Authors | Year | Venue | Score |"`
   - Separator: `"|---|-------|---------|------|-------|-------|"`
   - One row per paper: index, title, `_format_authors_short(authors)`, year or `"-"`, venue or `"-"`, `f"{score:.2f}"`
   - Join with newline

4. `_make_bibtex_key(paper: Paper, seen: set[str]) -> str`:
   - First author last name (or "unknown"), underscore, year (or "nd"), underscore, first word of title (or "untitled")
   - Lowercase, strip non-alphanumeric except underscore
   - If key in `seen`, append `_a`, `_b`, etc.
   - Add key to `seen`, return it

5. `_escape_bibtex(text: str) -> str`:
   - Replace `&` → `\&`, `%` → `\%`, `_` → `\_`, `#` → `\#`

6. `_format_bibtex_entry(paper: Paper, key: str) -> str`:
   - `@article{key,` then fields: `author`, `title` (in `{...}`), `year`, `journal` (venue), `doi`, `url`
   - Omit fields that are None/empty
   - End with `}`

7. `_format_authors_short(authors: list[Author]) -> str`:
   - If empty: `"-"`
   - If 1-3: join by `, ` using `f"{a.family_name or ''} {a.given_name or ''}".strip()`
   - If >3: first author + ` et al.`

**Verify**: `from paper_search.export import export_json, export_bibtex, export_markdown` imports without error.

---

## Task 2: Update library public API [DONE]

**File**: `src/paper_search/__init__.py` (MODIFY)

Add:
```python
from paper_search.export import export_bibtex, export_json, export_markdown

async def search(
    query: str,
    config: "AppConfig | None" = None,
    max_results: int = 100,
    domain: str = "general",
) -> "PaperCollection":
    from paper_search.config import AppConfig, load_config
    from paper_search.workflow import SearchWorkflow
    cfg = config or load_config()
    wf = SearchWorkflow.from_config(cfg)
    return await wf.run(query)
```

Update `__all__` to include: `Paper`, `PaperCollection`, `ParsedIntent`, `SearchStrategy`, `search`, `export_json`, `export_bibtex`, `export_markdown`.

**Verify**: `from paper_search import search, export_json` imports without error.

---

## Task 3: Create dev CLI entry point [DONE]

**File**: `src/paper_search/__main__.py` (NEW)

```python
"""Dev CLI for paper-search. Usage: python -m paper_search <query>"""
from __future__ import annotations
import asyncio
import sys

def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m paper_search <query>", file=sys.stderr)
        sys.exit(1)
    query = " ".join(sys.argv[1:])
    try:
        result = asyncio.run(_run(query))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    from paper_search import export_markdown
    print(export_markdown(result))

async def _run(query: str):
    from paper_search import search
    from paper_search.config import load_config
    config = load_config()
    return await search(query, config=config)

if __name__ == "__main__":
    main()
```

**Verify**: `python -m paper_search` (no args) prints usage and exits with code 1.

---

## Task 4: Create MCP checkpoint handler [DONE]

**File**: `src/paper_search/mcp_server.py` (NEW — part 1: session infrastructure)

Imports:
```python
from __future__ import annotations
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any
from paper_search.config import AppConfig, load_config
from paper_search.models import PaperCollection
from paper_search.workflow.checkpoints import (
    Checkpoint, CheckpointKind, Decision, DecisionAction,
)
from paper_search.workflow.engine import SearchWorkflow
```

Implement:

1. `MCPCheckpointHandler`:
   - `__init__()`: creates `_checkpoint_ready: asyncio.Event()`, `_decision_ready: asyncio.Event()`, `_current_checkpoint: Checkpoint | None = None`, `_decision: Decision | None = None`
   - `async handle(checkpoint) -> Decision`: sets `_current_checkpoint`, sets `_checkpoint_ready`, clears `_decision_ready`, awaits `_decision_ready.wait()`, clears `_checkpoint_ready`, returns `_decision`
   - `set_decision(decision)`: sets `_decision`, sets `_decision_ready`
   - Properties: `current_checkpoint`, `has_pending_checkpoint` (= `_checkpoint_ready.is_set()`)

2. `WorkflowSession` dataclass:
   - Fields: `session_id: str`, `query: str`, `handler: MCPCheckpointHandler`, `task: asyncio.Task | None = None`, `result: PaperCollection | None = None`, `error: str | None = None`, `is_complete: bool = False`

3. `SessionManager`:
   - `__init__()`: `_sessions: dict[str, WorkflowSession] = {}`
   - `create(query: str, config: AppConfig | None = None) -> str`: generate UUID session_id, create MCPCheckpointHandler, create WorkflowSession, start `_run_workflow` in `asyncio.create_task`, store in `_sessions`, return session_id
   - `get(session_id) -> WorkflowSession | None`
   - `async wait_for_checkpoint_or_complete(session_id) -> dict`: loop checking `handler.has_pending_checkpoint` or `session.is_complete` with small sleep
   - `cleanup(session_id)`: cancel task if running, remove from `_sessions`
   - `async _run_workflow(session: WorkflowSession, config: AppConfig)`: try/except around `SearchWorkflow.from_config(config, checkpoint_handler=session.handler).run(session.query)`, set `session.result` or `session.error`, set `session.is_complete = True`

**Verify**: `from paper_search.mcp_server import MCPCheckpointHandler, SessionManager` imports without error.

---

## Task 5: Create MCP tool definitions [DONE]

**File**: `src/paper_search/mcp_server.py` (APPEND — part 2: FastMCP tools)

Add at module level:
```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("paper-search")
_session_manager = SessionManager()
```

Implement 4 tools:

1. `@mcp.tool() async def search_papers(query: str, domain: str = "general", max_results: int = 100) -> str`:
   - Load config via `load_config()`, override `config.domain = domain`
   - `session_id = _session_manager.create(query, config)`
   - `await asyncio.sleep(0.1)` — yield to let workflow start
   - `state = await _session_manager.wait_for_checkpoint_or_complete(session_id)`
   - Return JSON: `{"session_id": ..., "status": "checkpoint"|"complete", "checkpoint_kind"?: ..., "summary"?: ...}`

2. `@mcp.tool() async def decide(session_id: str, action: str, data: dict | None = None, note: str | None = None) -> str`:
   - Validate session exists, has pending checkpoint
   - Validate action in `{"approve", "edit", "reject"}`
   - Create `Decision(action=DecisionAction(action), revised_data=data, note=note)`
   - `session.handler.set_decision(decision)`
   - `state = await _session_manager.wait_for_checkpoint_or_complete(session_id)`
   - Return JSON with next state

3. `@mcp.tool() async def export_results(session_id: str, format: str = "markdown") -> str`:
   - Validate session exists and is complete
   - Call `export_json`, `export_bibtex`, or `export_markdown` based on format
   - Return formatted string

4. `@mcp.tool() async def get_session(session_id: str) -> str`:
   - Return JSON: `{"session_id", "query", "is_complete", "has_pending_checkpoint", "checkpoint_kind", "paper_count", "error"}`

Add entry point:
```python
def main():
    mcp.run(transport="stdio")
```

**Verify**: `from paper_search.mcp_server import mcp, main` imports without error (requires `mcp` package installed).

---

## Task 6: Update pyproject.toml [DONE]

**File**: `pyproject.toml` (MODIFY)

Add under `[project.optional-dependencies]`:
```toml
mcp = ["mcp>=1.22"]
```

Add under `[project.scripts]`:
```toml
paper-search-mcp = "paper_search.mcp_server:main"
```

**Verify**: `pip install -e ".[mcp]"` succeeds. `paper-search-mcp --help` or similar.

---

## Task 7: Write export tests [DONE]

**File**: `tests/test_export.py` (NEW)

Create test fixtures:
- `_EMPTY_COLLECTION`: PaperCollection with no papers
- `_SINGLE_PAPER_COLLECTION`: one paper with all fields
- `_MULTI_PAPER_COLLECTION`: 3 papers (varying authors, years, venues)
- `_SPECIAL_CHARS_COLLECTION`: paper with `&`, `%`, `_` in title/venue

Tests:
1. `test_export_json_valid`: output is valid JSON, parseable by `json.loads`
2. `test_export_json_preserves_papers`: parsed JSON has correct paper count and IDs
3. `test_export_json_idempotent`: two calls produce identical output
4. `test_export_json_empty`: empty collection → valid JSON with empty papers array
5. `test_export_bibtex_entry_count`: N papers → N `@article{` entries
6. `test_export_bibtex_key_uniqueness`: duplicate authors+year → unique keys
7. `test_export_bibtex_special_chars`: `&` and `_` escaped in output
8. `test_export_bibtex_empty`: empty collection → empty string
9. `test_export_bibtex_missing_fields`: paper with None doi/venue → those fields omitted
10. `test_export_markdown_row_count`: N papers → N+2 lines
11. `test_export_markdown_header`: first line contains all column names
12. `test_export_markdown_empty`: empty collection → header + separator only
13. `test_export_markdown_format`: score formatted as 2 decimal places

**Verify**: `pytest tests/test_export.py -v` all pass.

---

## Task 8: Write library API tests [DONE]

**File**: `tests/test_library_api.py` (NEW)

Tests:
1. `test_public_api_exports`: all names in `__all__` are importable from `paper_search`
2. `test_search_function_exists`: `paper_search.search` is callable and async
3. `test_export_functions_importable`: `export_json`, `export_bibtex`, `export_markdown` importable from `paper_search`

**Verify**: `pytest tests/test_library_api.py -v` all pass.

---

## Task 9: Write CLI tests [DONE]

**File**: `tests/test_main.py` (NEW)

Tests:
1. `test_no_args_exits_1`: `subprocess.run([sys.executable, "-m", "paper_search"])` returns exit code 1
2. `test_no_args_prints_usage`: stderr contains "Usage:"

**Verify**: `pytest tests/test_main.py -v` all pass.

---

## Task 10: Write MCP server tests [DONE]

**File**: `tests/test_mcp_server.py` (NEW)

Test fixtures:
- Mock `SearchWorkflow` that uses `MCPCheckpointHandler`
- Patch `load_config` and `SearchWorkflow.from_config`

Tests for MCPCheckpointHandler:
1. `test_handler_satisfies_protocol`: isinstance check against CheckpointHandler
2. `test_handler_checkpoint_flow`: call handle() in background, verify has_pending_checkpoint, set_decision, verify handle returns decision
3. `test_handler_current_checkpoint`: after handle() starts, current_checkpoint is the checkpoint passed in

Tests for SessionManager:
4. `test_create_returns_session_id`: create() returns non-empty string
5. `test_get_returns_session`: after create, get returns WorkflowSession
6. `test_get_unknown_returns_none`: get("bad-id") returns None
7. `test_cleanup_removes_session`: after cleanup, get returns None

Tests for MCP tools (if mcp package available, else skip):
8. `test_search_papers_creates_session`: mock workflow, verify session created
9. `test_decide_invalid_session`: returns error
10. `test_decide_invalid_action`: returns error
11. `test_export_results_incomplete`: returns error
12. `test_get_session_returns_state`: verify JSON structure

**Verify**: `pytest tests/test_mcp_server.py -v` all pass.

---

## Task 11: Final verification [DONE]

Run full test suite:
```
.venv/Scripts/pytest tests/ -v
```

Verify: 149 existing tests + all new tests pass. Zero regressions.

---

## Execution Order

```
Task 1              (export utilities — no dependencies)
Task 2              (library API — depends on Task 1)
Task 3              (dev CLI — depends on Task 2)
Task 4              (MCP handler + session — no dependency on Tasks 1-3)
Task 5              (MCP tools — depends on Task 1 + Task 4)
Task 6              (pyproject.toml — depends on Task 5)
Task 7              (export tests — depends on Task 1)
Task 8              (library tests — depends on Task 2)
Task 9              (CLI tests — depends on Task 3)
Task 10             (MCP tests — depends on Task 4 + Task 5)
Task 11             (final verification — depends on all)
```

Parallelizable groups:
- Group A: Tasks 1, 4 (export utils + MCP handler — fully independent)
- Group B: Tasks 2, 3, 5, 6, 7 (library API + CLI + MCP tools + deps + export tests — after Group A)
- Group C: Tasks 8, 9, 10 (remaining tests — after Group B)
- Group D: Task 11 (final — after all)

All 11 tasks are mechanical. Zero decisions remain.
