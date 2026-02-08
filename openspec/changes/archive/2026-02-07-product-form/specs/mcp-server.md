# Spec: MCP Server

## Capability: mcp-server

### Requirement: FastMCP server instance (REQ-7)
Server created via `FastMCP("paper-search")`. Runs on STDIO transport by default.

### Requirement: search_papers tool (REQ-8)
`search_papers(query: str, domain: str = "general", max_results: int = 100) -> str` creates a new session, starts the workflow in a background task, waits for the first checkpoint or completion, and returns JSON with `session_id` and either `checkpoint` (kind + payload summary) or `result` (paper count + summary).

### Requirement: decide tool (REQ-9)
`decide(session_id: str, action: str, data: dict | None = None, note: str | None = None) -> str` validates `action` is one of `approve/edit/reject`, constructs a `Decision`, pushes it to the session's checkpoint handler, waits for the next checkpoint or completion, returns JSON with next state.

### Requirement: export_results tool (REQ-10)
`export_results(session_id: str, format: str = "markdown") -> str` validates the session is complete, calls the appropriate `export_*` function, returns formatted output. Supported formats: `json`, `bibtex`, `markdown`.

### Requirement: get_session tool (REQ-11)
`get_session(session_id: str) -> str` returns JSON with session state: `session_id`, `query`, `is_complete`, `has_pending_checkpoint`, `current_checkpoint_kind` (if pending), `error` (if any).

### Requirement: MCPCheckpointHandler (REQ-12)
Implements `CheckpointHandler` Protocol using `asyncio.Event` pair:
- `_checkpoint_ready`: set when checkpoint arrives, cleared after decision consumed
- `_decision_ready`: set when decision provided, cleared when next checkpoint arrives
- `handle()` blocks on `_decision_ready.wait()`
- `set_decision()` unblocks `handle()` by setting the event

### Requirement: SessionManager (REQ-13)
Thread-safe session storage:
- `create(query, config) -> session_id`: creates session, starts background task
- `get(session_id) -> WorkflowSession | None`
- `decide(session_id, decision) -> dict`: pushes decision, waits for result
- `cleanup(session_id)`: cancels task if running, removes from storage

### Requirement: Error handling (REQ-14)
Tool errors return `isError=True` responses (not exceptions) for:
- Unknown session_id
- No pending checkpoint for decide
- Session already complete
- Invalid action value
- Export on incomplete session
- Workflow runtime errors (captured in session.error)

### Requirement: Session isolation (REQ-15)
Each session has its own `MCPCheckpointHandler` instance, `asyncio.Task`, and `WorkflowState`. No shared mutable state between sessions.

### Requirement: Server entry point (REQ-16)
`paper_search.mcp_server:main` function calls `mcp.run(transport="stdio")`. Registered as `paper-search-mcp` script in pyproject.toml.

---

## PBT Properties

### PROP-6: Session lifecycle
After `search_papers(q)` returns `session_id`, `get_session(session_id)` returns a valid state dict with `is_complete=False` (unless auto-completed).

**Falsification**: Call search_papers, extract session_id, call get_session, verify structure.

### PROP-7: Decision mapping completeness
For every `DecisionAction` enum value, `decide(session_id, action.value)` produces a valid response (no unhandled action).

**Falsification**: Enumerate DecisionAction values, call decide for each, verify no internal errors.

### PROP-8: Session isolation
Two sessions created with different queries never share checkpoint state.

**Falsification**: Create two sessions, advance one, verify other's state unchanged.

### PROP-9: Monotonic workflow progress
Each `decide()` call either increments the iteration counter or completes the workflow.

**Falsification**: Track iteration before/after decide, verify monotonic increase or completion.

### PROP-10: Cleanup safety
After `cleanup(session_id)`, `get_session(session_id)` returns None.

**Falsification**: Create session, cleanup, get — verify None.
