# Proposal: Workflow Orchestration + Human Checkpoints

## Context

Phase 0-3 implemented all 6 individual skills (IntentParser, QueryBuilder, Searcher, Deduplicator, RelevanceScorer, ResultOrganizer) with 111 passing tests. The `SearchWorkflow` engine skeleton exists at `src/paper_search/workflow/engine.py` (raises `NotImplementedError`). `WorkflowState` already tracks iteration history. Phase 4 wires these skills together with human-in-the-loop checkpoints and iterative refinement.

## User Need

Run the full pipeline — from natural language input to organized `PaperCollection` — in a single `await workflow.run(user_input)` call, with the ability for humans to inspect/modify the search strategy and review results at designated checkpoints. The checkpoint mechanism must be product-form agnostic (CLI, MCP, library all work).

---

## Constraints

### C1: Frozen Skill Interfaces
All 6 skill classes and their method signatures are implemented and tested (111 tests). Cannot change:
- `IntentParser.parse(user_input: str) -> ParsedIntent`
- `QueryBuilder.build(input: QueryBuilderInput) -> SearchStrategy`
- `Searcher.search(strategy: SearchStrategy) -> list[RawPaper]`
- `Deduplicator.deduplicate(papers: list[RawPaper]) -> list[RawPaper]`
- `RelevanceScorer.score(papers: list[RawPaper], intent: ParsedIntent) -> list[ScoredPaper]`
- `ResultOrganizer.organize(papers: list[ScoredPaper], strategy: SearchStrategy, original_query: str) -> PaperCollection`

### C2: Frozen Models
All Pydantic models in `models.py` are fixed: `ParsedIntent`, `SearchStrategy`, `QueryBuilderInput`, `UserFeedback`, `PaperCollection`, etc. New models for checkpoints go in `workflow/` modules, not `models.py`.

### C3: Existing WorkflowState
`WorkflowState` in `workflow/state.py` already has: `current_iteration`, `history: list[IterationRecord]`, `accumulated_papers: list[Paper]`, `is_complete`, `record_iteration()`, `previous_strategies`, `latest_feedback`. Must use as-is or extend minimally.

### C4: Pipeline Order (Design Doc)
`parse -> build -> [checkpoint1] -> search -> dedup -> score -> organize -> [checkpoint2] -> [iterate or finish]`

### C5: Checkpoint Optionality (Design Doc)
- Checkpoint 1 (strategy confirmation): **optional** (skippable for automated use)
- Checkpoint 2 (result review): **required**

### C6: Iteration Model
User feedback (`UserFeedback`) + `previous_strategies` feed back into `QueryBuilderInput` for next round. Accumulated papers = user-confirmed relevant papers persisted across iterations.

### C7: Unified Checkpoint Object Pattern (User Decision)
Single `handle(checkpoint) -> Decision` interface. Checkpoint carries `kind + payload + context`. Decision carries `action (approve/edit/reject) + revised_data + note`. New checkpoint types = new `CheckpointKind` enum value + payload type, no handler signature change.

### C8: Async-First
All skills are async. Workflow must be async.

### C9: Dependency Injection
Skills as constructor args (testable with mocks). Convenience `from_config()` class method for production use.

---

## Risks

| # | Risk | Mitigation |
|---|------|------------|
| R1 | Checkpoint handler blocks indefinitely (user never responds) | Add optional `timeout` to checkpoint, default `None` (no timeout) |
| R2 | Iteration loop runs forever | `max_iterations` parameter with default 5 |
| R3 | Accumulated papers grow unbounded across iterations | Cap at `max_results` from config; warn when approaching limit |

---

## Success Criteria

1. `SearchWorkflow.run(user_input)` executes the full 6-step pipeline and returns `PaperCollection`
2. Without a `CheckpointHandler`, the workflow runs fully automated (no checkpoints)
3. With a `CheckpointHandler`, checkpoint 1 fires after strategy generation and checkpoint 2 fires after result organization
4. User "reject" at checkpoint 2 triggers iteration with updated `QueryBuilderInput`
5. User "approve" at checkpoint 2 completes the workflow
6. `WorkflowState` records all iterations
7. `from_config(AppConfig)` builds a ready-to-use workflow from environment config
8. All existing 111 tests still pass + new workflow tests cover the orchestration logic
