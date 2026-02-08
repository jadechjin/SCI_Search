"""Tests for checkpoint models."""

from __future__ import annotations

from datetime import datetime

import pytest

from paper_search.models import (
    Facets,
    IntentType,
    Paper,
    PaperCollection,
    ParsedIntent,
    SearchMetadata,
    SearchQuery,
    SearchStrategy,
)
from paper_search.workflow.checkpoints import (
    Checkpoint,
    CheckpointHandler,
    CheckpointKind,
    Decision,
    DecisionAction,
    ResultPayload,
    StrategyPayload,
)


_INTENT = ParsedIntent(
    topic="test topic",
    concepts=["a", "b"],
    intent_type=IntentType.SURVEY,
)

_STRATEGY = SearchStrategy(
    queries=[SearchQuery(keywords=["a"], synonym_map=[], boolean_query="a")],
    sources=["serpapi_scholar"],
)

_COLLECTION = PaperCollection(
    metadata=SearchMetadata(
        query="test",
        search_strategy=_STRATEGY,
        total_found=0,
    ),
    papers=[],
    facets=Facets(),
)


class TestCheckpointKind:
    def test_values(self):
        assert CheckpointKind.STRATEGY_CONFIRMATION == "strategy_confirmation"
        assert CheckpointKind.RESULT_REVIEW == "result_review"

    def test_members(self):
        assert len(CheckpointKind) == 2


class TestDecisionAction:
    def test_values(self):
        assert DecisionAction.APPROVE == "approve"
        assert DecisionAction.EDIT == "edit"
        assert DecisionAction.REJECT == "reject"

    def test_members(self):
        assert len(DecisionAction) == 3


class TestStrategyPayload:
    def test_construction(self):
        p = StrategyPayload(
            intent=_INTENT, strategy=_STRATEGY
        )
        assert p.intent.topic == "test topic"
        assert p.strategy.sources == ["serpapi_scholar"]


class TestResultPayload:
    def test_construction(self):
        p = ResultPayload(collection=_COLLECTION)
        assert p.collection.metadata.total_found == 0
        assert p.accumulated_papers == []

    def test_with_accumulated(self):
        paper = Paper(
            id="p1", title="T", authors=[], source="s", relevance_score=0.5
        )
        p = ResultPayload(
            collection=_COLLECTION,
            accumulated_papers=[paper],
        )
        assert len(p.accumulated_papers) == 1


class TestCheckpoint:
    def test_auto_fields(self):
        ckpt = Checkpoint(
            kind=CheckpointKind.STRATEGY_CONFIRMATION,
            payload=StrategyPayload(
                intent=_INTENT, strategy=_STRATEGY
            ),
        )
        # run_id is a valid UUID string
        assert len(ckpt.run_id) == 36
        assert "-" in ckpt.run_id
        # timestamp is parseable ISO 8601
        datetime.fromisoformat(ckpt.timestamp)

    def test_explicit_fields(self):
        ckpt = Checkpoint(
            kind=CheckpointKind.RESULT_REVIEW,
            payload=ResultPayload(collection=_COLLECTION),
            run_id="custom-id",
            iteration=3,
        )
        assert ckpt.run_id == "custom-id"
        assert ckpt.iteration == 3


class TestDecision:
    def test_defaults(self):
        d = Decision(action=DecisionAction.APPROVE)
        assert d.revised_data is None
        assert d.note is None

    def test_with_data(self):
        d = Decision(
            action=DecisionAction.EDIT,
            revised_data={"key": "value"},
            note="edited",
        )
        assert d.revised_data == {"key": "value"}
        assert d.note == "edited"


class TestCheckpointHandlerProtocol:
    def test_satisfies_protocol(self):
        class MyHandler:
            async def handle(self, checkpoint: Checkpoint) -> Decision:
                return Decision(action=DecisionAction.APPROVE)

        assert isinstance(MyHandler(), CheckpointHandler)

    def test_not_satisfies_protocol(self):
        class NotHandler:
            pass

        assert not isinstance(NotHandler(), CheckpointHandler)
