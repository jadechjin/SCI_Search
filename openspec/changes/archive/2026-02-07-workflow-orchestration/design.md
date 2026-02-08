# Design: Workflow Orchestration + Human Checkpoints

## Locked Constraints

| ID | Constraint | Decision |
|----|-----------|----------|
| C1 | Skill interfaces | Frozen — 6 skills, 111 tests |
| C2 | Models location | New checkpoint models in `workflow/checkpoints.py`, NOT `models.py` |
| C3 | WorkflowState | Use existing, extend with `add_accumulated()` helper |
| C4 | Pipeline order | parse → build → [ckpt1] → search → dedup → score → organize → [ckpt2] |
| C5 | Checkpoint optionality | ckpt1 optional, ckpt2 required |
| C6 | Iteration model | UserFeedback + previous_strategies → QueryBuilderInput |
| C7 | Checkpoint pattern | Unified object: `Checkpoint(kind, payload)` + `Decision(action, revised_data)` |
| C8 | Async-first | All public methods async |
| C9 | DI + factory | Skills as constructor args + `from_config()` classmethod |

## File Touch List

| File | Action | Purpose |
|------|--------|---------|
| `src/paper_search/workflow/checkpoints.py` | CREATE | CheckpointKind, DecisionAction, payload models, Checkpoint, Decision, CheckpointHandler Protocol |
| `src/paper_search/workflow/engine.py` | REWRITE | SearchWorkflow: constructor, run(), _run_iteration(), from_config() |
| `src/paper_search/workflow/state.py` | MODIFY | Add `add_accumulated()` helper method |
| `src/paper_search/workflow/__init__.py` | MODIFY | Export public API |
| `tests/test_workflow/__init__.py` | CREATE | Package init |
| `tests/test_workflow/test_engine.py` | CREATE | Orchestration + iteration + edge case tests |
| `tests/test_workflow/test_checkpoints.py` | CREATE | Checkpoint/Decision model validation tests |

## Component Design

### 1. Checkpoint Models (`workflow/checkpoints.py`)

```python
class CheckpointKind(str, Enum):
    STRATEGY_CONFIRMATION = "strategy_confirmation"
    RESULT_REVIEW = "result_review"

class DecisionAction(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"

class StrategyPayload(BaseModel):
    intent: ParsedIntent
    strategy: SearchStrategy
    iteration: int

class ResultPayload(BaseModel):
    collection: PaperCollection
    accumulated_papers: list[Paper]
    iteration: int

class Checkpoint(BaseModel):
    kind: CheckpointKind
    payload: StrategyPayload | ResultPayload
    run_id: str          # UUID for this workflow run
    iteration: int
    timestamp: str       # ISO 8601

class Decision(BaseModel):
    action: DecisionAction
    revised_data: Any = None     # SearchStrategy dict for ckpt1, UserFeedback dict for ckpt2
    note: str | None = None

class CheckpointHandler(Protocol):
    async def handle(self, checkpoint: Checkpoint) -> Decision: ...
```

### 2. Decision Semantics

| Checkpoint | Action | Behavior |
|-----------|--------|----------|
| STRATEGY_CONFIRMATION | APPROVE | Proceed with current strategy |
| STRATEGY_CONFIRMATION | EDIT | `revised_data` → validate as `SearchStrategy`, use it |
| STRATEGY_CONFIRMATION | REJECT | Convert `note` to free-text feedback, skip to next iteration |
| RESULT_REVIEW | APPROVE | Workflow complete, return collection |
| RESULT_REVIEW | EDIT | `revised_data` → validate as `UserFeedback`, iterate |
| RESULT_REVIEW | REJECT | `note` → free-text feedback, iterate |

### 3. SearchWorkflow Constructor

```python
class SearchWorkflow:
    def __init__(
        self,
        intent_parser: IntentParser,
        query_builder: QueryBuilder,
        searcher: Searcher,
        deduplicator: Deduplicator,
        relevance_scorer: RelevanceScorer,
        result_organizer: ResultOrganizer,
        checkpoint_handler: CheckpointHandler | None = None,
        max_iterations: int = 5,
        enable_strategy_checkpoint: bool = True,
    ) -> None: ...
```

### 4. SearchWorkflow.run() Algorithm

```
run(user_input: str) -> PaperCollection:
    run_id = uuid4()
    state = WorkflowState()
    intent = await intent_parser.parse(user_input)

    while state.current_iteration < max_iterations:
        # Build query
        qb_input = QueryBuilderInput(
            intent=intent,
            previous_strategies=state.previous_strategies,
            user_feedback=state.latest_feedback,
        )
        strategy = await query_builder.build(qb_input)

        # Checkpoint 1: Strategy confirmation (optional)
        if enable_strategy_checkpoint and checkpoint_handler:
            ckpt = make_checkpoint(STRATEGY_CONFIRMATION, StrategyPayload(...), ...)
            decision = await checkpoint_handler.handle(ckpt)
            if decision.action == EDIT:
                strategy = SearchStrategy.model_validate(decision.revised_data)
            elif decision.action == REJECT:
                feedback = _coerce_feedback(decision)
                state.record_iteration(strategy, 0, feedback)
                continue

        # Execute pipeline
        raw = await searcher.search(strategy)
        deduped = await deduplicator.deduplicate(raw)
        scored = await relevance_scorer.score(deduped, intent)
        collection = await result_organizer.organize(scored, strategy, user_input)

        # Checkpoint 2: Result review
        if checkpoint_handler:
            ckpt = make_checkpoint(RESULT_REVIEW, ResultPayload(...), ...)
            decision = await checkpoint_handler.handle(ckpt)
        else:
            decision = Decision(action=APPROVE)

        if decision.action == APPROVE:
            _accumulate_relevant(state, collection, decision)
            state.record_iteration(strategy, len(collection.papers))
            state.is_complete = True
            return _merge_accumulated(collection, state.accumulated_papers)

        # EDIT or REJECT → iterate
        feedback = _coerce_feedback(decision)
        _accumulate_relevant(state, collection, feedback)
        state.record_iteration(strategy, len(collection.papers), feedback)

    # Max iterations reached
    state.is_complete = True
    return collection  # Return last iteration's result
```

### 5. Helper Functions (private in engine.py)

```python
def _coerce_feedback(decision: Decision) -> UserFeedback:
    """Convert Decision to UserFeedback for iteration."""
    if decision.revised_data and isinstance(decision.revised_data, dict):
        try:
            return UserFeedback.model_validate(decision.revised_data)
        except ValidationError:
            pass
    return UserFeedback(free_text_feedback=decision.note or "")

def _accumulate_relevant(state: WorkflowState, collection: PaperCollection, feedback_or_decision) -> None:
    """Add user-marked-relevant papers to accumulated_papers."""
    if isinstance(feedback_or_decision, UserFeedback):
        fb = feedback_or_decision
    elif isinstance(feedback_or_decision, Decision) and feedback_or_decision.revised_data:
        fb = _coerce_feedback(feedback_or_decision)
    else:
        return
    relevant_ids = set(fb.marked_relevant)
    if not relevant_ids:
        return
    existing_ids = {p.id for p in state.accumulated_papers}
    for paper in collection.papers:
        if paper.id in relevant_ids and paper.id not in existing_ids:
            state.accumulated_papers.append(paper)

def _merge_accumulated(collection: PaperCollection, accumulated: list[Paper]) -> PaperCollection:
    """Merge accumulated papers into collection, dedup by ID."""
    if not accumulated:
        return collection
    current_ids = {p.id for p in collection.papers}
    extras = [p for p in accumulated if p.id not in current_ids]
    if not extras:
        return collection
    merged = list(collection.papers) + extras
    return collection.model_copy(update={"papers": merged})
```

### 6. from_config() Factory

```python
@classmethod
def from_config(
    cls,
    config: AppConfig,
    checkpoint_handler: CheckpointHandler | None = None,
    max_iterations: int = 5,
) -> SearchWorkflow:
    llm = create_provider(config.llm)
    sources: list[SearchSource] = []
    for name, src_cfg in config.sources.items():
        if not src_cfg.enabled:
            continue
        if name == "serpapi_scholar":
            from paper_search.sources.serpapi_scholar import SerpAPIScholarSource
            sources.append(SerpAPIScholarSource(
                api_key=src_cfg.api_key,
                rate_limit_rps=src_cfg.rate_limit,
            ))
    available = [s.source_name for s in sources]
    return cls(
        intent_parser=IntentParser(llm, domain=config.domain),
        query_builder=QueryBuilder(llm, domain=config.domain, available_sources=available),
        searcher=Searcher(sources),
        deduplicator=Deduplicator(llm=llm),
        relevance_scorer=RelevanceScorer(llm),
        result_organizer=ResultOrganizer(),
        checkpoint_handler=checkpoint_handler,
        max_iterations=max_iterations,
    )
```

### 7. WorkflowState Extension

Add one helper to `state.py`:

```python
def add_accumulated(self, papers: list[Paper]) -> None:
    """Add papers to accumulated list, dedup by ID."""
    existing = {p.id for p in self.accumulated_papers}
    for p in papers:
        if p.id not in existing:
            self.accumulated_papers.append(p)
            existing.add(p.id)
```

### 8. Edge Cases

| Case | Handling |
|------|----------|
| Empty search results | Pipeline continues → empty PaperCollection → checkpoint 2 fires → user can iterate or accept |
| All sources fail | Same as empty — Searcher returns `[]` |
| IntentParser fails | Propagate exception (fatal — can't proceed without intent) |
| Checkpoint handler raises | Propagate exception (handler is user-controlled) |
| Max iterations reached | Return last collection, set `state.is_complete = True` |
| No checkpoint handler | Auto-approve all → single iteration, pure automation |
| Strategy checkpoint disabled | Skip checkpoint 1 regardless of handler |
