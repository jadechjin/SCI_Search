# Tasks: Workflow Orchestration + Human Checkpoints

All decisions are locked in `design.md`. Each task is pure mechanical execution.

---

## Task 1: Create checkpoint models [DONE]

**File**: `src/paper_search/workflow/checkpoints.py` (NEW)

Create all checkpoint-related models:

```python
from __future__ import annotations
import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable
from pydantic import BaseModel, Field
```

1. `CheckpointKind(str, Enum)`: `STRATEGY_CONFIRMATION = "strategy_confirmation"`, `RESULT_REVIEW = "result_review"`
2. `DecisionAction(str, Enum)`: `APPROVE = "approve"`, `EDIT = "edit"`, `REJECT = "reject"`
3. `StrategyPayload(BaseModel)`: `intent: ParsedIntent`, `strategy: SearchStrategy`, `iteration: int`
4. `ResultPayload(BaseModel)`: `collection: PaperCollection`, `accumulated_papers: list[Paper] = Field(default_factory=list)`, `iteration: int`
5. `Checkpoint(BaseModel)`: `kind: CheckpointKind`, `payload: StrategyPayload | ResultPayload`, `run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))`, `iteration: int = 0`, `timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())`
6. `Decision(BaseModel)`: `action: DecisionAction`, `revised_data: Any = None`, `note: str | None = None`
7. `CheckpointHandler(Protocol)`: decorated with `@runtime_checkable`, single method `async def handle(self, checkpoint: Checkpoint) -> Decision: ...`

Import from `paper_search.models`: `ParsedIntent`, `SearchStrategy`, `PaperCollection`, `Paper`.

**Verify**: `from paper_search.workflow.checkpoints import Checkpoint, Decision, CheckpointHandler` imports without error.

---

## Task 2: Extend WorkflowState [DONE]

**File**: `src/paper_search/workflow/state.py` (MODIFY)

Add method to `WorkflowState`:

```python
def add_accumulated(self, papers: list[Paper]) -> None:
    """Add papers to accumulated list, dedup by ID."""
    existing_ids = {p.id for p in self.accumulated_papers}
    for p in papers:
        if p.id not in existing_ids:
            self.accumulated_papers.append(p)
            existing_ids.add(p.id)
```

**Verify**: Existing tests still pass.

---

## Task 3: Implement SearchWorkflow [DONE]

**File**: `src/paper_search/workflow/engine.py` (REWRITE)

Imports:
```python
from __future__ import annotations
import logging
import uuid
from pydantic import ValidationError
from paper_search.models import (
    PaperCollection, QueryBuilderInput, SearchStrategy, UserFeedback,
)
from paper_search.skills.intent_parser import IntentParser
from paper_search.skills.query_builder import QueryBuilder
from paper_search.skills.searcher import Searcher
from paper_search.skills.deduplicator import Deduplicator
from paper_search.skills.relevance_scorer import RelevanceScorer
from paper_search.skills.result_organizer import ResultOrganizer
from paper_search.workflow.checkpoints import (
    Checkpoint, CheckpointKind, CheckpointHandler, Decision, DecisionAction,
    StrategyPayload, ResultPayload,
)
from paper_search.workflow.state import WorkflowState
```

Constructor: Accept all 6 skills + `checkpoint_handler: CheckpointHandler | None = None` + `max_iterations: int = 5` + `enable_strategy_checkpoint: bool = True`. Store all as private attributes.

`async run(self, user_input: str) -> PaperCollection`:
1. `run_id = str(uuid.uuid4())`
2. `state = WorkflowState()`
3. `intent = await self._intent_parser.parse(user_input)`
4. `last_collection: PaperCollection | None = None`
5. Loop `while state.current_iteration < self._max_iterations`:
   a. Build `QueryBuilderInput(intent, state.previous_strategies, state.latest_feedback)`
   b. `strategy = await self._query_builder.build(qb_input)`
   c. If `self._enable_strategy_checkpoint and self._checkpoint_handler`:
      - Build `Checkpoint(kind=STRATEGY_CONFIRMATION, payload=StrategyPayload(intent, strategy, state.current_iteration), run_id=run_id, iteration=state.current_iteration)`
      - `decision = await self._checkpoint_handler.handle(ckpt)`
      - If `decision.action == EDIT`: `strategy = SearchStrategy.model_validate(decision.revised_data)`
      - If `decision.action == REJECT`: `feedback = _coerce_feedback(decision)`, `state.record_iteration(strategy, 0, feedback)`, `continue`
   d. `raw = await self._searcher.search(strategy)`
   e. `deduped = await self._deduplicator.deduplicate(raw)`
   f. `scored = await self._relevance_scorer.score(deduped, intent)`
   g. `collection = await self._result_organizer.organize(scored, strategy, user_input)`
   h. `last_collection = collection`
   i. If `self._checkpoint_handler`:
      - Build `Checkpoint(kind=RESULT_REVIEW, payload=ResultPayload(collection, list(state.accumulated_papers), state.current_iteration), run_id=run_id, iteration=state.current_iteration)`
      - `decision = await self._checkpoint_handler.handle(ckpt)`
   j. Else: `decision = Decision(action=DecisionAction.APPROVE)`
   k. If `decision.action == DecisionAction.APPROVE`:
      - `state.record_iteration(strategy, len(collection.papers))`
      - `state.is_complete = True`
      - return `_merge_accumulated(collection, state.accumulated_papers)`
   l. Else (EDIT or REJECT):
      - `feedback = _coerce_feedback(decision)`
      - `_accumulate_relevant(state, collection, feedback)`
      - `state.record_iteration(strategy, len(collection.papers), feedback)`
6. After loop: `state.is_complete = True`, return `last_collection` (or empty PaperCollection if None)

Private module-level helpers:
- `_coerce_feedback(decision: Decision) -> UserFeedback`: try `UserFeedback.model_validate(decision.revised_data)` if dict, else `UserFeedback(free_text_feedback=decision.note or "")`
- `_accumulate_relevant(state: WorkflowState, collection: PaperCollection, feedback: UserFeedback) -> None`: find papers in collection with IDs in `feedback.marked_relevant`, call `state.add_accumulated(matching_papers)`
- `_merge_accumulated(collection: PaperCollection, accumulated: list[Paper]) -> PaperCollection`: add accumulated papers not already in collection.papers (by ID), return updated collection

**Verify**: Import + basic instantiation with mock skills.

---

## Task 4: Implement from_config [DONE]

**File**: `src/paper_search/workflow/engine.py` (MODIFY — add classmethod)

Add to `SearchWorkflow`:

```python
@classmethod
def from_config(
    cls,
    config: AppConfig,
    checkpoint_handler: CheckpointHandler | None = None,
    max_iterations: int = 5,
    enable_strategy_checkpoint: bool = True,
) -> SearchWorkflow:
```

Implementation:
1. `from paper_search.llm import create_provider`
2. `llm = create_provider(config.llm)`
3. Build sources list: iterate `config.sources`, for each enabled source:
   - If `name == "serpapi_scholar"`: `from paper_search.sources.serpapi_scholar import SerpAPIScholarSource; sources.append(SerpAPIScholarSource(api_key=src_cfg.api_key, rate_limit_rps=src_cfg.rate_limit))`
4. `available = [s.source_name for s in sources]`
5. Construct all 6 skills with correct params (see design.md §6)
6. Return `cls(...)`

Import `AppConfig` from `paper_search.config`.

**Verify**: `SearchWorkflow.from_config(mock_config)` returns a SearchWorkflow instance.

---

## Task 5: Update workflow exports [DONE]

**File**: `src/paper_search/workflow/__init__.py` (MODIFY)

Add exports:
```python
from paper_search.workflow.checkpoints import (
    Checkpoint,
    CheckpointHandler,
    CheckpointKind,
    Decision,
    DecisionAction,
    ResultPayload,
    StrategyPayload,
)
from paper_search.workflow.engine import SearchWorkflow
from paper_search.workflow.state import WorkflowState
```

**Verify**: `from paper_search.workflow import SearchWorkflow, Checkpoint, Decision` imports without error.

---

## Task 6: Write checkpoint model tests [DONE]

**File**: `tests/test_workflow/__init__.py` (NEW, empty)
**File**: `tests/test_workflow/test_checkpoints.py` (NEW)

Tests:
1. `test_checkpoint_kind_values` — verify enum values match expected strings
2. `test_decision_action_values` — verify enum values
3. `test_strategy_payload_construction` — valid StrategyPayload
4. `test_result_payload_construction` — valid ResultPayload
5. `test_checkpoint_auto_fields` — verify run_id is UUID, timestamp is ISO 8601
6. `test_decision_defaults` — `revised_data=None`, `note=None` by default
7. `test_checkpoint_handler_protocol` — class with `async handle()` satisfies `isinstance(..., CheckpointHandler)`

**Verify**: `pytest tests/test_workflow/test_checkpoints.py -v` all pass.

---

## Task 7: Write workflow engine tests [DONE]

**File**: `tests/test_workflow/test_engine.py` (NEW)

Create mock skills (all async, return configurable data):
- `MockIntentParser`: returns fixed ParsedIntent
- `MockQueryBuilder`: returns fixed SearchStrategy
- `MockSearcher`: returns fixed list[RawPaper]
- `MockDeduplicator`: returns input as-is
- `MockRelevanceScorer`: returns fixed list[ScoredPaper]
- `MockResultOrganizer`: returns fixed PaperCollection
- `MockCheckpointHandler`: records calls, returns configurable Decision

Tests:
1. `test_full_pipeline_no_handler` — runs all 6 skills in order, returns PaperCollection
2. `test_full_pipeline_with_approve` — handler approves both checkpoints → same as no handler
3. `test_strategy_checkpoint_edit` — handler edits strategy → modified strategy used for search
4. `test_strategy_checkpoint_reject` — handler rejects → skip to next iteration
5. `test_strategy_checkpoint_disabled` — `enable_strategy_checkpoint=False` → ckpt1 never fires
6. `test_result_review_reject_iterates` — handler rejects at ckpt2 → loop continues
7. `test_result_review_edit_iterates` — handler returns EDIT with UserFeedback → loop continues
8. `test_max_iterations_reached` — handler always rejects → stops at max_iterations, returns last collection
9. `test_iteration_feeds_previous_strategies` — verify QueryBuilderInput has previous strategies on 2nd iteration
10. `test_iteration_feeds_user_feedback` — verify QueryBuilderInput has feedback on 2nd iteration
11. `test_accumulated_papers_merge` — mark papers relevant → appear in final output
12. `test_empty_results` — searcher returns [] → valid empty PaperCollection
13. `test_coerce_feedback_from_dict` — Decision with UserFeedback dict → valid UserFeedback
14. `test_coerce_feedback_from_note` — Decision with just note → UserFeedback(free_text_feedback=note)
15. `test_checkpoint_ordering` — handler logs kind order → STRATEGY_CONFIRMATION before RESULT_REVIEW
16. `test_state_is_complete_on_approve` — verify state.is_complete is True after approve
17. `test_state_is_complete_on_max_iterations` — verify state.is_complete is True after max iterations

**Verify**: `pytest tests/test_workflow/test_engine.py -v` all pass.

---

## Task 8: Write from_config tests [DONE]

**File**: `tests/test_workflow/test_engine.py` (APPEND) or separate section

Tests:
1. `test_from_config_basic` — valid config → returns SearchWorkflow with correct skill types
2. `test_from_config_no_sources` — config with empty sources → workflow still constructs (Searcher has empty source list)
3. `test_from_config_disabled_source` — source with `enabled=False` → not included

**Verify**: `pytest tests/test_workflow/ -v` all pass.

---

## Task 9: Final verification [DONE]

Run full test suite:
```
.venv/Scripts/pytest tests/ -v
```

Verify: 111 existing tests + all new tests pass. Zero regressions.

---

## Execution Order

```
Task 1              (checkpoint models — no dependencies)
Task 2              (WorkflowState extension — no dependencies)
Task 3              (SearchWorkflow — depends on Task 1 + Task 2)
Task 4              (from_config — depends on Task 3)
Task 5              (exports — depends on Task 1 + Task 3)
Task 6              (checkpoint tests — depends on Task 1)
Task 7              (engine tests — depends on Task 3 + Task 4)
Task 8              (from_config tests — depends on Task 4)
Task 9              (final verification — depends on all)
```

Parallelizable groups:
- Group A: Tasks 1, 2 (models — fully independent)
- Group B: Tasks 3, 6 (engine + checkpoint tests — after Group A)
- Group C: Tasks 4, 5 (from_config + exports — after Task 3)
- Group D: Tasks 7, 8 (engine + config tests — after Group C)
- Group E: Task 9 (final — after all)

All 9 tasks are mechanical. Zero decisions remain.
