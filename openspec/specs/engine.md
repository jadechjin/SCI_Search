# Spec: Workflow Engine

## Capability: workflow-engine

### Requirement: SearchWorkflow constructor — DI (REQ-8)
**Given** skills are injected for testability
**When** constructing SearchWorkflow
**Then** accepts: `intent_parser`, `query_builder`, `searcher`, `deduplicator`, `relevance_scorer`, `result_organizer`, `checkpoint_handler: CheckpointHandler | None`, `max_iterations: int = 5`, `enable_strategy_checkpoint: bool = True`

### Requirement: SearchWorkflow.run() — full pipeline (REQ-9)
**Given** a user input string
**When** `run(user_input)` is called
**Then** executes: parse → build → [ckpt1] → search → dedup → score → organize → [ckpt2] → return `PaperCollection`

### Requirement: Checkpoint 1 — strategy confirmation (REQ-10)
**Given** `enable_strategy_checkpoint=True` and `checkpoint_handler` is not None
**When** strategy is built
**Then** fires `Checkpoint(kind=STRATEGY_CONFIRMATION, payload=StrategyPayload(...))`
**And** APPROVE proceeds, EDIT replaces strategy, REJECT skips to next iteration

### Requirement: Checkpoint 1 — skip when disabled (REQ-11)
**Given** `enable_strategy_checkpoint=False` OR `checkpoint_handler is None`
**When** strategy is built
**Then** checkpoint 1 does NOT fire

### Requirement: Checkpoint 2 — result review (REQ-12)
**Given** `checkpoint_handler` is not None
**When** results are organized
**Then** fires `Checkpoint(kind=RESULT_REVIEW, payload=ResultPayload(...))`
**And** APPROVE completes workflow, EDIT/REJECT triggers iteration

### Requirement: Checkpoint 2 — auto-approve without handler (REQ-13)
**Given** `checkpoint_handler is None`
**When** results are organized
**Then** auto-approve: workflow completes after first iteration

### Requirement: Iteration loop (REQ-14)
**Given** checkpoint 2 returns EDIT or REJECT
**When** iteration triggers
**Then** `_coerce_feedback(decision)` produces `UserFeedback`
**And** next `QueryBuilderInput` includes `previous_strategies` and `user_feedback`
**And** loop continues from query building (NOT intent parsing)

### Requirement: Max iterations (REQ-15)
**Given** `max_iterations` is set
**When** `state.current_iteration >= max_iterations`
**Then** loop exits, returns last collection, `state.is_complete = True`

### Requirement: Accumulated papers (REQ-16)
**Given** user marks papers as relevant via `UserFeedback.marked_relevant`
**When** iterating
**Then** relevant papers from current collection are added to `state.accumulated_papers`
**And** on final return, accumulated papers are merged into collection (dedup by ID)

### Requirement: _coerce_feedback helper (REQ-17)
**Given** a `Decision` from checkpoint
**When** coercing to `UserFeedback`
**Then** if `revised_data` is dict validatable as `UserFeedback`, use it
**Else** create `UserFeedback(free_text_feedback=decision.note or "")`

### Requirement: from_config factory (REQ-18)
**Given** an `AppConfig`
**When** `SearchWorkflow.from_config(config, checkpoint_handler, max_iterations)` is called
**Then** constructs LLM provider via `create_provider(config.llm)`
**And** constructs enabled search sources (serpapi_scholar → SerpAPIScholarSource)
**And** constructs all 6 skills with correct params
**And** returns configured `SearchWorkflow`

### Requirement: Empty results handling (REQ-19)
**Given** searcher returns empty list
**When** pipeline continues
**Then** produces valid empty `PaperCollection` and fires checkpoint 2

### Requirement: WorkflowState tracking (REQ-20)
**Given** each iteration
**When** iteration completes (approve or iterate)
**Then** `state.record_iteration(strategy, result_count, feedback)` is called
**And** on workflow exit, `state.is_complete = True`

---

## Properties

| ID | Property | Invariant | Falsification |
|----|----------|-----------|---------------|
| PROP-4 | Auto-approve equivalence | `run(input, handler=None)` produces same result as `run(input, handler=AlwaysApprove)` | Compare outputs with both modes |
| PROP-5 | Iteration bounded | `state.current_iteration <= max_iterations` at exit | Set max_iterations=1, always reject, verify single iteration |
| PROP-6 | Pipeline type chain | IntentParser→ParsedIntent→QueryBuilder→SearchStrategy→Searcher→list[RawPaper]→Deduplicator→list[RawPaper]→Scorer→list[ScoredPaper]→Organizer→PaperCollection | Mock each skill, verify correct arg types at each boundary |
| PROP-7 | State completeness | `state.is_complete == True` at all exit paths | Trigger every exit path, assert is_complete |
| PROP-8 | Checkpoint ordering | Within one iteration, ckpt1 always before ckpt2 | Log checkpoint kinds, verify order |
| PROP-9 | Output validity | Return value always passes `PaperCollection.model_validate()` | Run with empty results, failures, max iterations |
| PROP-10 | Iteration monotonicity | `state.current_iteration` increases by exactly 1 per loop iteration | Inspect history length |
| PROP-11 | Accumulated subset | Every paper in accumulated_papers has an ID that was in some collection.papers during the workflow | Track all paper IDs across iterations |
