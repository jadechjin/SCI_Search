# Spec: Library API + Dev CLI

## Capability: library-api

### Requirement: search convenience function (REQ-17)
`async search(query: str, config: AppConfig | None = None, max_results: int = 100, domain: str = "general") -> PaperCollection` runs the full workflow with no checkpoint handler (auto-approve). If `config` is None, calls `load_config()`.

### Requirement: Public API exports (REQ-18)
`paper_search.__init__.py` exports: `Paper`, `PaperCollection`, `ParsedIntent`, `SearchStrategy`, `search`, `export_json`, `export_bibtex`, `export_markdown`.

### Requirement: search equivalence (REQ-19)
`await search(query, config)` produces the same result as `await SearchWorkflow.from_config(config).run(query)` (both use no checkpoint handler → auto-approve → single iteration).

---

## Capability: dev-cli

### Requirement: CLI entry point (REQ-20)
`python -m paper_search "query text"` runs the search with auto-approve mode and prints Markdown table to stdout.

### Requirement: CLI error handling (REQ-21)
If no query argument provided, print usage to stderr and exit with code 1. If workflow raises, print error to stderr and exit with code 1.

### Requirement: CLI config (REQ-22)
CLI loads config from environment via `load_config()`. No CLI-specific config flags (keep minimal).

---

## Capability: dependencies

### Requirement: MCP as optional dependency (REQ-23)
`mcp` package is in `[project.optional-dependencies]` under key `mcp`. Library core does not import `mcp` — only `mcp_server.py` does. Users can `pip install paper-search` without MCP, or `pip install paper-search[mcp]` with it.

### Requirement: Script entry point (REQ-24)
`pyproject.toml` defines `paper-search-mcp = "paper_search.mcp_server:main"` in `[project.scripts]`.

---

## PBT Properties

### PROP-11: search convenience equivalence
For any query string and valid AppConfig, `await search(q, cfg)` returns a PaperCollection with the same structure as direct `SearchWorkflow.from_config(cfg).run(q)`.

**Falsification**: Generate random query, run both paths with same config and mocked LLM, compare paper IDs.

### PROP-12: CLI exit codes
CLI returns 0 on success (valid query + working config) and non-zero on error (no args, bad config).

**Falsification**: Run CLI with no args → assert exit code != 0. Run with valid args + mock → assert exit code == 0.

### PROP-13: Public API completeness
All names in `__all__` are importable from `paper_search` without error.

**Falsification**: For each name in `__all__`, assert `getattr(paper_search, name)` is not None.
