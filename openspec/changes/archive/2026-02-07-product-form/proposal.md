# Proposal: Product Form — Library + MCP Server + Dev CLI

## Context

Phase 0-4 implemented the full paper search pipeline with 149 passing tests. `SearchWorkflow.run(user_input)` orchestrates 6 skills with optional human-in-the-loop checkpoints via `CheckpointHandler` Protocol. Phase 5 wraps this engine into consumable product forms.

## User Need

Expose the paper search workflow as:
1. **Python Library** (primary) — clean public API for programmatic use, notebooks, and automation
2. **MCP Server** (agent integration) — tools callable by Claude Desktop, Cursor, and other LLM agents
3. **Dev CLI** (internal) — minimal `python -m paper_search "query"` for quick testing

The `CheckpointHandler` abstraction already decouples the engine from any specific UI/agent protocol, making it a natural fit for MCP tool-based interaction.

---

## Constraints

### C1: Product Hierarchy
Library is the primary product. MCP Server builds on Library. CLI is dev-only, not a main product.

### C2: MCP SDK
Use official `mcp` Python SDK (v1.22+), `FastMCP` class with `@mcp.tool()` decorators.

### C3: Unified `decide` Tool
Single `decide(session_id, action, data, note)` MCP tool maps 1:1 to the existing `Decision` model. No per-action tool proliferation.

### C4: Export Formats
JSON, BibTeX, Markdown. No CSV for now.

### C5: CLI Scope
Minimal `__main__.py` — auto-approve mode, print results. Not a user-facing product.

### C6: Zero Regressions
All existing 149 tests must continue to pass.

### C7: Frozen Engine
SearchWorkflow, CheckpointHandler, and all skill interfaces are frozen from Phase 4. No modifications to `workflow/` or `skills/`.

### C8: Async-First
All public functions maintain async-first design.

---

## Risks

| # | Risk | Mitigation |
|---|------|------------|
| R1 | MCP session state leak (workflow task hangs) | Session timeout (default 30min) + explicit cleanup |
| R2 | Concurrent sessions contention | Each session has isolated handler/state/task |
| R3 | asyncio.Event deadlock in checkpoint flow | Timeout on Event.wait() + proper error propagation |
| R4 | BibTeX generation edge cases (missing fields, special chars) | Defensive generation with fallbacks for all optional fields |

---

## Success Criteria

1. `from paper_search import search; result = await search("query")` works in a single line
2. `export_json`, `export_bibtex`, `export_markdown` produce valid output for any PaperCollection
3. MCP server exposes 4 tools: `search_papers`, `decide`, `export_results`, `get_session`
4. MCP `search_papers` → `decide` → `decide` flow completes a full checkpoint cycle
5. MCP sessions are isolated — concurrent sessions don't interfere
6. `python -m paper_search "some query"` prints results to stdout
7. All 149 existing tests pass + new tests cover library, MCP, and CLI
