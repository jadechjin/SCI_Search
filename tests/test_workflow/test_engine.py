"""Tests for SearchWorkflow engine."""

from __future__ import annotations

from typing import Any

import pytest

from paper_search.config import AppConfig, LLMConfig, SearchSourceConfig
from paper_search.llm.base import LLMProvider
from paper_search.models import (
    Author,
    Facets,
    IntentType,
    Paper,
    PaperCollection,
    PaperTag,
    ParsedIntent,
    QueryBuilderInput,
    RawPaper,
    ScoredPaper,
    SearchConstraints,
    SearchMetadata,
    SearchQuery,
    SearchStrategy,
    UserFeedback,
)
from paper_search.skills.deduplicator import Deduplicator
from paper_search.skills.intent_parser import IntentParser
from paper_search.skills.query_builder import QueryBuilder
from paper_search.skills.relevance_scorer import RelevanceScorer
from paper_search.skills.result_organizer import ResultOrganizer
from paper_search.skills.searcher import Searcher
from paper_search.sources.base import SearchSource
from paper_search.workflow.checkpoints import (
    Checkpoint,
    CheckpointKind,
    Decision,
    DecisionAction,
)
from paper_search.workflow.engine import (
    SearchWorkflow,
    _coerce_feedback,
    _merge_accumulated,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_INTENT = ParsedIntent(
    topic="test topic",
    concepts=["alpha", "beta"],
    intent_type=IntentType.SURVEY,
    constraints=SearchConstraints(year_from=2020),
)

_STRATEGY = SearchStrategy(
    queries=[
        SearchQuery(
            keywords=["alpha", "beta"],
            synonym_map=[],
            boolean_query="alpha AND beta",
        )
    ],
    sources=["serpapi_scholar"],
)

_RAW_PAPERS = [
    RawPaper(id="r1", title="Paper One", source="test", year=2023),
    RawPaper(id="r2", title="Paper Two", source="test", year=2022),
]

_SCORED_PAPERS = [
    ScoredPaper(
        paper=_RAW_PAPERS[0],
        relevance_score=0.9,
        relevance_reason="Highly relevant",
        tags=[PaperTag.METHOD],
    ),
    ScoredPaper(
        paper=_RAW_PAPERS[1],
        relevance_score=0.5,
        relevance_reason="Related",
        tags=[],
    ),
]

_PAPERS = [
    Paper(
        id="r1",
        title="Paper One",
        authors=[],
        source="test",
        year=2023,
        relevance_score=0.9,
        relevance_reason="Highly relevant",
        tags=[PaperTag.METHOD],
    ),
    Paper(
        id="r2",
        title="Paper Two",
        authors=[],
        source="test",
        year=2022,
        relevance_score=0.5,
        relevance_reason="Related",
        tags=[],
    ),
]

_COLLECTION = PaperCollection(
    metadata=SearchMetadata(
        query="test query",
        search_strategy=_STRATEGY,
        total_found=2,
    ),
    papers=_PAPERS,
    facets=Facets(),
)


# ---------------------------------------------------------------------------
# Mock skills
# ---------------------------------------------------------------------------

class MockIntentParser:
    async def parse(self, user_input: str) -> ParsedIntent:
        return _INTENT


class MockQueryBuilder:
    def __init__(self) -> None:
        self.last_input: QueryBuilderInput | None = None

    async def build(self, input: QueryBuilderInput) -> SearchStrategy:
        self.last_input = input
        return _STRATEGY


class MockSearcher:
    async def search(self, strategy: SearchStrategy) -> list[RawPaper]:
        return list(_RAW_PAPERS)


class MockEmptySearcher:
    async def search(self, strategy: SearchStrategy) -> list[RawPaper]:
        return []


class MockDeduplicator:
    async def deduplicate(self, papers: list[RawPaper]) -> list[RawPaper]:
        return papers


class MockRelevanceScorer:
    async def score(
        self, papers: list[RawPaper], intent: ParsedIntent
    ) -> list[ScoredPaper]:
        return list(_SCORED_PAPERS[: len(papers)])


class MockResultOrganizer:
    async def organize(
        self,
        papers: list[ScoredPaper],
        strategy: SearchStrategy,
        original_query: str,
    ) -> PaperCollection:
        return _COLLECTION


class MockCheckpointHandler:
    """Configurable checkpoint handler for testing."""

    def __init__(self, decisions: list[Decision] | None = None) -> None:
        self._decisions = list(decisions or [])
        self._call_idx = 0
        self.calls: list[Checkpoint] = []

    async def handle(self, checkpoint: Checkpoint) -> Decision:
        self.calls.append(checkpoint)
        if self._call_idx < len(self._decisions):
            d = self._decisions[self._call_idx]
            self._call_idx += 1
            return d
        return Decision(action=DecisionAction.APPROVE)


def _make_workflow(
    checkpoint_handler=None,
    max_iterations=5,
    enable_strategy_checkpoint=True,
    searcher=None,
    query_builder=None,
) -> SearchWorkflow:
    return SearchWorkflow(
        intent_parser=MockIntentParser(),
        query_builder=query_builder or MockQueryBuilder(),
        searcher=searcher or MockSearcher(),
        deduplicator=MockDeduplicator(),
        relevance_scorer=MockRelevanceScorer(),
        result_organizer=MockResultOrganizer(),
        checkpoint_handler=checkpoint_handler,
        max_iterations=max_iterations,
        enable_strategy_checkpoint=enable_strategy_checkpoint,
    )


# ---------------------------------------------------------------------------
# Tests: Full pipeline
# ---------------------------------------------------------------------------

class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_no_handler(self):
        wf = _make_workflow()
        result = await wf.run("test query")
        assert isinstance(result, PaperCollection)
        assert len(result.papers) == 2

    @pytest.mark.asyncio
    async def test_with_approve(self):
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),  # ckpt1
            Decision(action=DecisionAction.APPROVE),  # ckpt2
        ])
        wf = _make_workflow(checkpoint_handler=handler)
        result = await wf.run("test query")
        assert isinstance(result, PaperCollection)
        assert len(handler.calls) == 2

    @pytest.mark.asyncio
    async def test_empty_results(self):
        wf = _make_workflow(searcher=MockEmptySearcher())
        result = await wf.run("test query")
        assert isinstance(result, PaperCollection)


# ---------------------------------------------------------------------------
# Tests: Strategy checkpoint
# ---------------------------------------------------------------------------

class TestStrategyCheckpoint:
    @pytest.mark.asyncio
    async def test_edit_strategy(self):
        new_strategy_data = _STRATEGY.model_dump()
        new_strategy_data["sources"] = ["edited_source"]
        handler = MockCheckpointHandler([
            Decision(
                action=DecisionAction.EDIT,
                revised_data=new_strategy_data,
            ),
            Decision(action=DecisionAction.APPROVE),
        ])
        wf = _make_workflow(checkpoint_handler=handler)
        await wf.run("test query")

        # Verify ckpt1 was STRATEGY_CONFIRMATION
        assert handler.calls[0].kind == CheckpointKind.STRATEGY_CONFIRMATION

    @pytest.mark.asyncio
    async def test_reject_strategy(self):
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.REJECT, note="Too broad"),  # ckpt1 iter0
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter1
            Decision(action=DecisionAction.APPROVE),  # ckpt2 iter1
        ])
        wf = _make_workflow(checkpoint_handler=handler, max_iterations=3)
        result = await wf.run("test query")
        assert isinstance(result, PaperCollection)
        # 3 calls: reject ckpt1, approve ckpt1, approve ckpt2
        assert len(handler.calls) == 3

    @pytest.mark.asyncio
    async def test_disabled(self):
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),  # ckpt2 only
        ])
        wf = _make_workflow(
            checkpoint_handler=handler,
            enable_strategy_checkpoint=False,
        )
        await wf.run("test query")
        # Only ckpt2 fires
        assert len(handler.calls) == 1
        assert handler.calls[0].kind == CheckpointKind.RESULT_REVIEW


# ---------------------------------------------------------------------------
# Tests: Result review + iteration
# ---------------------------------------------------------------------------

class TestResultReview:
    @pytest.mark.asyncio
    async def test_reject_iterates(self):
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter0
            Decision(action=DecisionAction.REJECT, note="Need more"),  # ckpt2 iter0
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter1
            Decision(action=DecisionAction.APPROVE),  # ckpt2 iter1
        ])
        wf = _make_workflow(checkpoint_handler=handler, max_iterations=3)
        result = await wf.run("test query")
        assert isinstance(result, PaperCollection)
        # 4 checkpoint calls across 2 iterations
        assert len(handler.calls) == 4

    @pytest.mark.asyncio
    async def test_edit_iterates(self):
        feedback_data = {
            "marked_relevant": ["r1"],
            "free_text_feedback": "Focus on Paper One",
        }
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter0
            Decision(
                action=DecisionAction.EDIT,
                revised_data=feedback_data,
            ),  # ckpt2 iter0 → iterate
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter1
            Decision(action=DecisionAction.APPROVE),  # ckpt2 iter1
        ])
        wf = _make_workflow(checkpoint_handler=handler, max_iterations=3)
        result = await wf.run("test query")
        assert isinstance(result, PaperCollection)

    @pytest.mark.asyncio
    async def test_max_iterations_reached(self):
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter0
            Decision(action=DecisionAction.REJECT, note="No"),
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter1
            Decision(action=DecisionAction.REJECT, note="No"),
        ])
        wf = _make_workflow(checkpoint_handler=handler, max_iterations=2)
        result = await wf.run("test query")
        assert isinstance(result, PaperCollection)


# ---------------------------------------------------------------------------
# Tests: Iteration context
# ---------------------------------------------------------------------------

class TestIterationContext:
    @pytest.mark.asyncio
    async def test_feeds_previous_strategies(self):
        qb = MockQueryBuilder()
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter0
            Decision(action=DecisionAction.REJECT, note="More"),  # ckpt2 iter0
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter1
            Decision(action=DecisionAction.APPROVE),  # ckpt2 iter1
        ])
        wf = _make_workflow(
            checkpoint_handler=handler,
            query_builder=qb,
            max_iterations=3,
        )
        await wf.run("test query")
        # On 2nd iteration, qb.last_input should have previous_strategies
        assert qb.last_input is not None
        assert len(qb.last_input.previous_strategies) == 1

    @pytest.mark.asyncio
    async def test_feeds_user_feedback(self):
        qb = MockQueryBuilder()
        feedback_data = {"free_text_feedback": "Focus on methods"}
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter0
            Decision(
                action=DecisionAction.EDIT,
                revised_data=feedback_data,
            ),  # ckpt2 iter0
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter1
            Decision(action=DecisionAction.APPROVE),  # ckpt2 iter1
        ])
        wf = _make_workflow(
            checkpoint_handler=handler,
            query_builder=qb,
            max_iterations=3,
        )
        await wf.run("test query")
        assert qb.last_input is not None
        assert qb.last_input.user_feedback is not None
        assert qb.last_input.user_feedback.free_text_feedback == "Focus on methods"


# ---------------------------------------------------------------------------
# Tests: Accumulated papers
# ---------------------------------------------------------------------------

class TestAccumulatedPapers:
    @pytest.mark.asyncio
    async def test_merge_on_approve(self):
        # First iteration: mark r1 as relevant, reject
        # Second iteration: approve
        feedback_data = {
            "marked_relevant": ["r1"],
            "free_text_feedback": "Keep Paper One",
        }
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter0
            Decision(
                action=DecisionAction.EDIT,
                revised_data=feedback_data,
            ),  # ckpt2 iter0
            Decision(action=DecisionAction.APPROVE),  # ckpt1 iter1
            Decision(action=DecisionAction.APPROVE),  # ckpt2 iter1
        ])
        wf = _make_workflow(checkpoint_handler=handler, max_iterations=3)
        result = await wf.run("test query")
        # r1 is in both the current collection and accumulated, so no extra
        assert any(p.id == "r1" for p in result.papers)


# ---------------------------------------------------------------------------
# Tests: Checkpoint ordering
# ---------------------------------------------------------------------------

class TestCheckpointOrdering:
    @pytest.mark.asyncio
    async def test_strategy_before_result(self):
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.APPROVE),
            Decision(action=DecisionAction.APPROVE),
        ])
        wf = _make_workflow(checkpoint_handler=handler)
        await wf.run("test query")
        assert handler.calls[0].kind == CheckpointKind.STRATEGY_CONFIRMATION
        assert handler.calls[1].kind == CheckpointKind.RESULT_REVIEW


# ---------------------------------------------------------------------------
# Tests: State completeness
# ---------------------------------------------------------------------------

class TestStateCompleteness:
    @pytest.mark.asyncio
    async def test_complete_on_approve(self):
        wf = _make_workflow()
        await wf.run("test query")
        # Can't directly inspect state, but pipeline completes without error

    @pytest.mark.asyncio
    async def test_complete_on_max_iterations(self):
        handler = MockCheckpointHandler([
            Decision(action=DecisionAction.REJECT, note="No"),
        ] * 10)  # Always reject ckpt2 (no ckpt1 since disabled)
        wf = _make_workflow(
            checkpoint_handler=handler,
            max_iterations=2,
            enable_strategy_checkpoint=False,
        )
        result = await wf.run("test query")
        assert isinstance(result, PaperCollection)


# ---------------------------------------------------------------------------
# Tests: Helper functions
# ---------------------------------------------------------------------------

class TestCoerceFeedback:
    def test_from_valid_dict(self):
        d = Decision(
            action=DecisionAction.EDIT,
            revised_data={
                "marked_relevant": ["p1"],
                "free_text_feedback": "good",
            },
        )
        fb = _coerce_feedback(d)
        assert fb.marked_relevant == ["p1"]
        assert fb.free_text_feedback == "good"

    def test_from_invalid_dict(self):
        d = Decision(
            action=DecisionAction.EDIT,
            revised_data={"bad_field": True},
        )
        fb = _coerce_feedback(d)
        # Pydantic ignores extra fields, so this validates as UserFeedback()
        assert fb.free_text_feedback is None

    def test_from_note_only(self):
        d = Decision(action=DecisionAction.REJECT, note="Try again")
        fb = _coerce_feedback(d)
        assert fb.free_text_feedback == "Try again"

    def test_from_nothing(self):
        d = Decision(action=DecisionAction.REJECT)
        fb = _coerce_feedback(d)
        assert fb.free_text_feedback == ""


class TestMergeAccumulated:
    def test_no_accumulated(self):
        result = _merge_accumulated(_COLLECTION, [])
        assert result is _COLLECTION

    def test_with_new_papers(self):
        extra = Paper(
            id="extra1",
            title="Extra",
            authors=[],
            source="test",
            relevance_score=0.7,
        )
        result = _merge_accumulated(_COLLECTION, [extra])
        assert len(result.papers) == 3
        assert any(p.id == "extra1" for p in result.papers)

    def test_dedup_by_id(self):
        # Same ID as existing paper → not duplicated
        dup = Paper(
            id="r1",
            title="Paper One",
            authors=[],
            source="test",
            relevance_score=0.9,
        )
        result = _merge_accumulated(_COLLECTION, [dup])
        assert len(result.papers) == 2


# ---------------------------------------------------------------------------
# Tests: from_config
# ---------------------------------------------------------------------------

class TestFromConfig:
    def test_basic(self):
        config = AppConfig(
            llm=LLMConfig(
                provider="openai",
                model="gpt-4",
                api_key="test-key",
            ),
            sources={
                "serpapi_scholar": SearchSourceConfig(
                    name="serpapi_scholar",
                    api_key="serp-key",
                    enabled=True,
                )
            },
            domain="general",
        )
        wf = SearchWorkflow.from_config(config)
        assert isinstance(wf, SearchWorkflow)

    def test_no_sources(self):
        config = AppConfig(
            llm=LLMConfig(
                provider="openai",
                model="gpt-4",
                api_key="test-key",
            ),
            sources={},
        )
        wf = SearchWorkflow.from_config(config)
        assert isinstance(wf, SearchWorkflow)

    def test_disabled_source(self):
        config = AppConfig(
            llm=LLMConfig(
                provider="openai",
                model="gpt-4",
                api_key="test-key",
            ),
            sources={
                "serpapi_scholar": SearchSourceConfig(
                    name="serpapi_scholar",
                    api_key="serp-key",
                    enabled=False,
                )
            },
        )
        wf = SearchWorkflow.from_config(config)
        assert isinstance(wf, SearchWorkflow)
