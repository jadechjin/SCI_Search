"""Tests for MCP server components."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from paper_search.models import (
    Author,
    Facets,
    Paper,
    PaperCollection,
    SearchMetadata,
    SearchStrategy,
)
from paper_search.mcp_views import (
    serialize_checkpoint_payload as _serialize_checkpoint_payload,
    format_checkpoint_question as _format_checkpoint_question,
)
from paper_search.workflow.session import (
    MCPCheckpointHandler,
    SessionManager,
    WorkflowSession,
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
from paper_search.models import IntentType, ParsedIntent, SearchConstraints


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_checkpoint(kind: CheckpointKind = CheckpointKind.STRATEGY_CONFIRMATION) -> Checkpoint:
    return Checkpoint(
        kind=kind,
        payload=StrategyPayload(
            intent=ParsedIntent(
                topic="test",
                concepts=["a"],
                intent_type=IntentType.SURVEY,
                constraints=SearchConstraints(),
            ),
            strategy=SearchStrategy(queries=[], sources=[]),
        ),
    )


def _make_result_checkpoint() -> Checkpoint:
    return Checkpoint(
        kind=CheckpointKind.RESULT_REVIEW,
        payload=ResultPayload(
            collection=_MOCK_COLLECTION,
        ),
    )


_MOCK_COLLECTION = PaperCollection(
    metadata=SearchMetadata(
        query="test",
        search_strategy=SearchStrategy(queries=[], sources=[]),
        total_found=0,
    ),
    papers=[],
    facets=Facets(),
)


# ---------------------------------------------------------------------------
# MCPCheckpointHandler tests
# ---------------------------------------------------------------------------

class TestMCPCheckpointHandler:
    def test_satisfies_protocol(self):
        handler = MCPCheckpointHandler()
        assert isinstance(handler, CheckpointHandler)

    @pytest.mark.asyncio
    async def test_checkpoint_flow(self):
        handler = MCPCheckpointHandler()
        ckpt = _make_checkpoint()
        decision = Decision(action=DecisionAction.APPROVE)

        # Start handle in background
        async def _handle():
            return await handler.handle(ckpt)

        task = asyncio.create_task(_handle())
        await asyncio.sleep(0.05)

        assert handler.has_pending_checkpoint
        assert handler.current_checkpoint is ckpt

        handler.set_decision(decision)
        result = await task
        assert result.action == DecisionAction.APPROVE

    @pytest.mark.asyncio
    async def test_current_checkpoint(self):
        handler = MCPCheckpointHandler()
        assert handler.current_checkpoint is None
        assert not handler.has_pending_checkpoint

        ckpt = _make_checkpoint()
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        assert handler.current_checkpoint is ckpt

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task


# ---------------------------------------------------------------------------
# SessionManager tests
# ---------------------------------------------------------------------------

class TestSessionManager:
    @pytest.mark.asyncio
    async def test_create_returns_session_id(self):
        mgr = SessionManager()
        with patch("paper_search.workflow.session.SearchWorkflow") as mock_wf_cls:
            mock_wf = AsyncMock()
            mock_wf.run = AsyncMock(return_value=_MOCK_COLLECTION)
            mock_wf_cls.from_config.return_value = mock_wf
            sid = mgr.create("test query")
            assert isinstance(sid, str)
            assert len(sid) > 0
            # Clean up
            mgr.cleanup(sid)

    @pytest.mark.asyncio
    async def test_get_returns_session(self):
        mgr = SessionManager()
        with patch("paper_search.workflow.session.SearchWorkflow") as mock_wf_cls:
            mock_wf = AsyncMock()
            mock_wf.run = AsyncMock(return_value=_MOCK_COLLECTION)
            mock_wf_cls.from_config.return_value = mock_wf
            sid = mgr.create("test query")
            session = mgr.get(sid)
            assert session is not None
            assert session.query == "test query"
            mgr.cleanup(sid)

    def test_get_unknown_returns_none(self):
        mgr = SessionManager()
        assert mgr.get("nonexistent-id") is None

    @pytest.mark.asyncio
    async def test_cleanup_removes_session(self):
        mgr = SessionManager()
        with patch("paper_search.workflow.session.SearchWorkflow") as mock_wf_cls:
            mock_wf = AsyncMock()
            mock_wf.run = AsyncMock(return_value=_MOCK_COLLECTION)
            mock_wf_cls.from_config.return_value = mock_wf
            sid = mgr.create("test query")
            mgr.cleanup(sid)
            assert mgr.get(sid) is None


# ---------------------------------------------------------------------------
# MCP tool function tests (import and call directly)
# ---------------------------------------------------------------------------

class TestMCPTools:
    @pytest.mark.asyncio
    async def test_get_session_unknown(self):
        from paper_search.mcp_server import get_session
        result = json.loads(await get_session("bad-id"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_decide_invalid_session(self):
        from paper_search.mcp_server import decide
        result = json.loads(await decide("bad-id", "approve"))
        assert "error" in result

    @pytest.mark.asyncio
    async def test_decide_invalid_action(self):
        from paper_search.mcp_server import decide

        # Create a fake session in the manager
        from paper_search.mcp_server import _session_manager
        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-sid",
            query="test",
            handler=handler,
            require_user_response=False,
        )
        _session_manager._sessions["test-sid"] = session

        # Start a checkpoint so handler has pending
        ckpt = _make_checkpoint()
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        result = json.loads(await decide("test-sid", "invalid_action"))
        assert "error" in result
        assert "Invalid action" in result["error"]

        # Clean up
        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task
        del _session_manager._sessions["test-sid"]

    @pytest.mark.asyncio
    async def test_export_results_incomplete(self):
        from paper_search.mcp_server import export_results, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-export",
            query="test",
            handler=handler,
            is_complete=False,
        )
        _session_manager._sessions["test-export"] = session

        result = json.loads(await export_results("test-export", "markdown"))
        assert "error" in result
        assert "not complete" in result["error"]

        del _session_manager._sessions["test-export"]

    @pytest.mark.asyncio
    async def test_get_session_returns_state(self):
        from paper_search.mcp_server import get_session, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-state",
            query="my query",
            handler=handler,
            is_complete=True,
            result=_MOCK_COLLECTION,
        )
        _session_manager._sessions["test-state"] = session

        result = json.loads(await get_session("test-state"))
        assert result["session_id"] == "test-state"
        assert result["query"] == "my query"
        assert result["is_complete"] is True
        assert result["paper_count"] == 0
        assert "phase" in result
        assert "phase_updated_at" in result
        assert "elapsed_s" in result

        del _session_manager._sessions["test-state"]

    @pytest.mark.asyncio
    async def test_decide_returns_next_checkpoint_not_stale(self):
        from paper_search.mcp_server import decide, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-next-checkpoint",
            query="test",
            handler=handler,
            decide_wait_timeout_s=1.0,
            poll_interval_s=0.01,
            require_user_response=False,
        )
        _session_manager._sessions["test-next-checkpoint"] = session

        ckpt1 = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        ckpt2 = _make_result_checkpoint()

        async def _flow():
            await handler.handle(ckpt1)
            await handler.handle(ckpt2)

        flow_task = asyncio.create_task(_flow())
        await asyncio.sleep(0.05)

        result = json.loads(await decide("test-next-checkpoint", "approve"))
        assert result.get("has_pending_checkpoint") is True
        assert result.get("checkpoint_kind") == "result_review"

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await flow_task
        del _session_manager._sessions["test-next-checkpoint"]


# ---------------------------------------------------------------------------
# Checkpoint payload serialization tests
# ---------------------------------------------------------------------------


class TestSerializeCheckpointPayload:
    def test_strategy_payload_shape(self):
        ckpt = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        result = _serialize_checkpoint_payload(ckpt)

        assert "intent" in result
        assert result["intent"]["topic"] == "test"
        assert result["intent"]["concepts"] == ["a"]
        assert result["intent"]["intent_type"] == "survey"
        assert "constraints" in result["intent"]

        assert "strategy" in result
        assert "queries" in result["strategy"]
        assert "sources" in result["strategy"]
        assert "filters" in result["strategy"]

    def test_result_payload_shape(self):
        ckpt = _make_result_checkpoint()
        result = _serialize_checkpoint_payload(ckpt)

        assert "papers" in result
        assert "total_papers" in result
        assert "truncated" in result
        assert "facets" in result
        assert "accumulated_count" in result
        assert result["total_papers"] == 0
        assert result["truncated"] is False

    def test_result_payload_with_papers_includes_doi(self):
        paper = Paper(
            id="p1",
            doi="10.1234/test",
            title="Test Paper",
            authors=[Author(name="Alice")],
            year=2024,
            venue="Nature",
            source="serpapi",
            relevance_score=0.9,
            tags=[],
        )
        collection = PaperCollection(
            metadata=SearchMetadata(
                query="test",
                search_strategy=SearchStrategy(queries=[], sources=[]),
                total_found=1,
            ),
            papers=[paper],
            facets=Facets(),
        )
        ckpt = Checkpoint(
            kind=CheckpointKind.RESULT_REVIEW,
            payload=ResultPayload(collection=collection),
        )
        result = _serialize_checkpoint_payload(ckpt)

        assert len(result["papers"]) == 1
        assert result["papers"][0]["doi"] == "10.1234/test"
        assert result["papers"][0]["title"] == "Test Paper"
        assert result["papers"][0]["authors"] == ["Alice"]
        assert result["papers"][0]["year"] == 2024
        assert result["papers"][0]["relevance_reason"] == ""
        assert result["total_papers"] == 1
        assert result["truncated"] is False

    def test_result_payload_includes_relevance_reason(self):
        paper = Paper(
            id="p1",
            doi="10.1234/test",
            title="Test Paper",
            authors=[Author(name="Alice")],
            year=2024,
            venue="Nature",
            source="serpapi",
            relevance_score=0.9,
            relevance_reason="Directly addresses the research question",
            tags=[],
        )
        collection = PaperCollection(
            metadata=SearchMetadata(
                query="test",
                search_strategy=SearchStrategy(queries=[], sources=[]),
                total_found=1,
            ),
            papers=[paper],
            facets=Facets(),
        )
        ckpt = Checkpoint(
            kind=CheckpointKind.RESULT_REVIEW,
            payload=ResultPayload(collection=collection),
        )
        result = _serialize_checkpoint_payload(ckpt)

        assert result["papers"][0]["relevance_reason"] == "Directly addresses the research question"

    def test_result_payload_no_truncation_and_score_distribution(self):
        papers = [
            Paper(
                id=f"p{i}",
                title=f"Paper {i}",
                authors=[],
                source="serpapi",
                relevance_score=0.5,
            )
            for i in range(40)
        ]
        collection = PaperCollection(
            metadata=SearchMetadata(
                query="test",
                search_strategy=SearchStrategy(queries=[], sources=[]),
                total_found=len(papers),
            ),
            papers=papers,
            facets=Facets(),
        )
        ckpt = Checkpoint(
            kind=CheckpointKind.RESULT_REVIEW,
            payload=ResultPayload(collection=collection),
        )
        result = _serialize_checkpoint_payload(ckpt)

        assert len(result["papers"]) == 40
        assert result["total_papers"] == 40
        assert result["truncated"] is False
        assert "score_distribution" in result
        assert result["score_distribution"]["high"] == 0
        assert result["score_distribution"]["medium"] == 40
        assert result["score_distribution"]["low"] == 0

    def test_strategy_payload_type_mismatch_raises(self):
        ckpt = Checkpoint(
            kind=CheckpointKind.STRATEGY_CONFIRMATION,
            payload=ResultPayload(collection=_MOCK_COLLECTION),
        )
        with pytest.raises(TypeError, match="Expected StrategyPayload"):
            _serialize_checkpoint_payload(ckpt)

    def test_result_payload_type_mismatch_raises(self):
        ckpt = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        # Force kind to RESULT_REVIEW while keeping StrategyPayload
        ckpt.kind = CheckpointKind.RESULT_REVIEW
        with pytest.raises(TypeError, match="Expected ResultPayload"):
            _serialize_checkpoint_payload(ckpt)

    def test_strategy_payload_json_serializable(self):
        ckpt = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        result = _serialize_checkpoint_payload(ckpt)
        # Must not raise
        serialized = json.dumps(result)
        assert isinstance(serialized, str)

    def test_result_payload_json_serializable(self):
        ckpt = _make_result_checkpoint()
        result = _serialize_checkpoint_payload(ckpt)
        serialized = json.dumps(result)
        assert isinstance(serialized, str)


class TestSessionStatePayload:
    @pytest.mark.asyncio
    async def test_state_includes_strategy_payload(self):
        from paper_search.mcp_server import get_session, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-strategy-payload",
            query="test",
            handler=handler,
        )
        _session_manager._sessions["test-strategy-payload"] = session

        ckpt = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        result = json.loads(await get_session("test-strategy-payload"))
        assert "checkpoint_payload" in result
        assert "intent" in result["checkpoint_payload"]
        assert "strategy" in result["checkpoint_payload"]
        assert "checkpoint_id" in result

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task
        del _session_manager._sessions["test-strategy-payload"]

    @pytest.mark.asyncio
    async def test_state_includes_result_payload(self):
        from paper_search.mcp_server import get_session, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-result-payload",
            query="test",
            handler=handler,
        )
        _session_manager._sessions["test-result-payload"] = session

        ckpt = _make_result_checkpoint()
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        result = json.loads(await get_session("test-result-payload"))
        assert "checkpoint_payload" in result
        assert "papers" in result["checkpoint_payload"]
        assert "total_papers" in result["checkpoint_payload"]
        assert "truncated" in result["checkpoint_payload"]
        assert "checkpoint_id" in result

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task
        del _session_manager._sessions["test-result-payload"]

    @pytest.mark.asyncio
    async def test_decide_next_checkpoint_includes_payload(self):
        from paper_search.mcp_server import decide, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-decide-payload",
            query="test",
            handler=handler,
            decide_wait_timeout_s=1.0,
            poll_interval_s=0.01,
            require_user_response=False,
        )
        _session_manager._sessions["test-decide-payload"] = session

        ckpt1 = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        ckpt2 = _make_result_checkpoint()

        async def _flow():
            await handler.handle(ckpt1)
            await handler.handle(ckpt2)

        flow_task = asyncio.create_task(_flow())
        await asyncio.sleep(0.05)

        result = json.loads(await decide("test-decide-payload", "approve"))
        assert result.get("checkpoint_kind") == "result_review"
        assert "checkpoint_payload" in result
        assert "papers" in result["checkpoint_payload"]

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await flow_task
        del _session_manager._sessions["test-decide-payload"]


# ---------------------------------------------------------------------------
# _format_checkpoint_question tests
# ---------------------------------------------------------------------------


def _make_result_checkpoint_with_papers(n: int = 3) -> Checkpoint:
    papers = [
        Paper(
            id=f"p{i}",
            title=f"Paper Title {i}",
            authors=[Author(name=f"Author {i}")],
            year=2024,
            doi=f"10.1234/p{i}" if i % 2 == 0 else None,
            venue="Nature" if i % 2 == 0 else "Science",
            source="serpapi",
            relevance_score=round(max(0.0, 0.9 - i * 0.04), 2),
            relevance_reason=f"Reason for paper {i}",
            tags=[],
        )
        for i in range(n)
    ]
    collection = PaperCollection(
        metadata=SearchMetadata(
            query="test",
            search_strategy=SearchStrategy(queries=[], sources=[]),
            total_found=n,
        ),
        papers=papers,
        facets=Facets(
            by_venue={"Nature": n // 2, "Science": n - n // 2},
            top_authors=[f"Author {i}" for i in range(min(n, 5))],
            key_themes=["photocatalysis", "MOF"],
        ),
    )
    return Checkpoint(
        kind=CheckpointKind.RESULT_REVIEW,
        payload=ResultPayload(collection=collection),
    )


class TestFormatCheckpointQuestion:
    def test_strategy_question_includes_topic(self):
        ckpt = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        question = _format_checkpoint_question(ckpt)
        assert "test" in question
        assert "Approve" in question
        assert "Reject" in question
        assert "Strategy Review" in question

    def test_strategy_question_includes_concepts(self):
        ckpt = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        question = _format_checkpoint_question(ckpt)
        assert "a" in question
        assert "survey" in question

    def test_result_question_includes_paper_count(self):
        ckpt = _make_result_checkpoint_with_papers(3)
        question = _format_checkpoint_question(ckpt)
        assert "3 papers" in question
        assert "Approve" in question
        assert "Reject" in question
        assert "Results Review" in question

    def test_result_question_shows_top_papers(self):
        ckpt = _make_result_checkpoint_with_papers(3)
        question = _format_checkpoint_question(ckpt)
        assert "Paper Title 0" in question
        assert "Paper Title 1" in question
        assert "Paper Title 2" in question

    def test_result_question_limits_to_15_papers(self):
        ckpt = _make_result_checkpoint_with_papers(20)
        question = _format_checkpoint_question(ckpt)
        assert "Paper Title 0" in question
        assert "Paper Title 14" in question
        assert "showing top 15 in detail" in question
        # Complete paper list includes all papers
        assert "Complete paper list" in question
        assert "Paper Title 19" in question

    def test_empty_result_question(self):
        ckpt = _make_result_checkpoint()  # 0 papers
        question = _format_checkpoint_question(ckpt)
        assert "0 papers" in question

    def test_result_question_includes_doi_and_venue(self):
        ckpt = _make_result_checkpoint_with_papers(3)
        question = _format_checkpoint_question(ckpt)
        # Paper 0 has DOI and Nature venue
        assert "10.1234/p0" in question
        assert "Nature" in question
        assert "Science" in question

    def test_result_question_includes_relevance_reason(self):
        ckpt = _make_result_checkpoint_with_papers(3)
        question = _format_checkpoint_question(ckpt)
        assert "Reason for paper 0" in question
        assert "Reason for paper 1" in question

    def test_result_question_includes_facets(self):
        ckpt = _make_result_checkpoint_with_papers(6)
        question = _format_checkpoint_question(ckpt)
        assert "Venues:" in question
        assert "Top authors:" in question
        assert "Key themes:" in question
        assert "photocatalysis" in question
        assert "MOF" in question

    def test_result_question_shows_remaining_count(self):
        ckpt = _make_result_checkpoint_with_papers(20)
        question = _format_checkpoint_question(ckpt)
        assert "5 more papers" in question


# ---------------------------------------------------------------------------
# Session state user_question fields tests
# ---------------------------------------------------------------------------


class TestSessionStateUserQuestion:
    @pytest.mark.asyncio
    async def test_state_includes_user_question_when_checkpoint_pending(self):
        from paper_search.mcp_server import get_session, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-user-q",
            query="test",
            handler=handler,
        )
        _session_manager._sessions["test-user-q"] = session

        ckpt = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        result = json.loads(await get_session("test-user-q"))
        assert result["user_action_required"] is True
        assert "user_question" in result
        assert "Strategy Review" in result["user_question"]
        assert result["user_options"] == ["approve", "reject"]

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task
        del _session_manager._sessions["test-user-q"]

    @pytest.mark.asyncio
    async def test_state_no_user_question_without_checkpoint(self):
        from paper_search.mcp_server import get_session, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-no-q",
            query="test",
            handler=handler,
            is_complete=True,
            result=_MOCK_COLLECTION,
        )
        _session_manager._sessions["test-no-q"] = session

        result = json.loads(await get_session("test-no-q"))
        assert "user_action_required" not in result
        assert "user_question" not in result
        assert "user_options" not in result

        del _session_manager._sessions["test-no-q"]


# ---------------------------------------------------------------------------
# user_response validation tests
# ---------------------------------------------------------------------------


class TestDecideUserResponse:
    @pytest.mark.asyncio
    async def test_rejects_none_user_response(self):
        from paper_search.mcp_server import decide, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-ur-none",
            query="test",
            handler=handler,
            require_user_response=True,
        )
        _session_manager._sessions["test-ur-none"] = session

        ckpt = _make_checkpoint()
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        result = json.loads(await decide("test-ur-none", "approve"))
        assert "error" in result
        assert "user_response is required" in result["error"]

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task
        del _session_manager._sessions["test-ur-none"]

    @pytest.mark.asyncio
    async def test_rejects_empty_user_response(self):
        from paper_search.mcp_server import decide, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-ur-empty",
            query="test",
            handler=handler,
            require_user_response=True,
        )
        _session_manager._sessions["test-ur-empty"] = session

        ckpt = _make_checkpoint()
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        result = json.loads(await decide("test-ur-empty", "approve", user_response=""))
        assert "error" in result
        assert "user_response is required" in result["error"]

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task
        del _session_manager._sessions["test-ur-empty"]

    @pytest.mark.asyncio
    async def test_rejects_trivial_user_response(self):
        from paper_search.mcp_server import decide, _session_manager

        for trivial in ["ok", "yes", "approve", "OK", "Yes", "APPROVE", "  ok  "]:
            handler = MCPCheckpointHandler()
            sid = f"test-ur-trivial-{trivial.strip()}"
            session = WorkflowSession(
                session_id=sid,
                query="test",
                handler=handler,
                require_user_response=True,
            )
            _session_manager._sessions[sid] = session

            ckpt = _make_checkpoint()
            task = asyncio.create_task(handler.handle(ckpt))
            await asyncio.sleep(0.05)

            result = json.loads(await decide(sid, "approve", user_response=trivial))
            assert "error" in result, f"Expected error for trivial response: {trivial!r}"

            handler.set_decision(Decision(action=DecisionAction.APPROVE))
            await task
            del _session_manager._sessions[sid]

    @pytest.mark.asyncio
    async def test_accepts_substantive_user_response(self):
        from paper_search.mcp_server import decide, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-ur-good",
            query="test",
            handler=handler,
            decide_wait_timeout_s=1.0,
            poll_interval_s=0.01,
            require_user_response=True,
        )
        _session_manager._sessions["test-ur-good"] = session

        ckpt1 = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        ckpt2 = _make_result_checkpoint()

        async def _flow():
            await handler.handle(ckpt1)
            await handler.handle(ckpt2)

        flow_task = asyncio.create_task(_flow())
        await asyncio.sleep(0.05)

        result = json.loads(
            await decide(
                "test-ur-good",
                "approve",
                user_response="The search strategy looks good, proceed with searching",
            )
        )
        # Should succeed (no "error" key) and proceed to result_review
        assert "error" not in result
        assert result.get("checkpoint_kind") == "result_review"

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await flow_task
        del _session_manager._sessions["test-ur-good"]

    @pytest.mark.asyncio
    async def test_reject_requires_feedback_when_response_validation_disabled(self):
        from paper_search.mcp_server import decide, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-reject-needs-feedback",
            query="test",
            handler=handler,
            require_user_response=False,
        )
        _session_manager._sessions["test-reject-needs-feedback"] = session

        ckpt = _make_checkpoint()
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        result = json.loads(
            await decide("test-reject-needs-feedback", "reject")
        )
        assert "error" in result
        assert "requires substantive feedback" in result["error"]
        assert handler.has_pending_checkpoint is True

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task
        del _session_manager._sessions["test-reject-needs-feedback"]

    @pytest.mark.asyncio
    async def test_edit_requires_data_when_response_validation_disabled(self):
        from paper_search.mcp_server import decide, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-edit-needs-data",
            query="test",
            handler=handler,
            require_user_response=False,
        )
        _session_manager._sessions["test-edit-needs-data"] = session

        ckpt = _make_checkpoint()
        task = asyncio.create_task(handler.handle(ckpt))
        await asyncio.sleep(0.05)

        result = json.loads(await decide("test-edit-needs-data", "edit"))
        assert "error" in result
        assert "requires revised data" in result["error"]
        assert handler.has_pending_checkpoint is True

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await task
        del _session_manager._sessions["test-edit-needs-data"]

    @pytest.mark.asyncio
    async def test_skips_validation_when_disabled(self):
        from paper_search.mcp_server import decide, _session_manager

        handler = MCPCheckpointHandler()
        session = WorkflowSession(
            session_id="test-ur-skip",
            query="test",
            handler=handler,
            decide_wait_timeout_s=1.0,
            poll_interval_s=0.01,
            require_user_response=False,
        )
        _session_manager._sessions["test-ur-skip"] = session

        ckpt1 = _make_checkpoint(CheckpointKind.STRATEGY_CONFIRMATION)
        ckpt2 = _make_result_checkpoint()

        async def _flow():
            await handler.handle(ckpt1)
            await handler.handle(ckpt2)

        flow_task = asyncio.create_task(_flow())
        await asyncio.sleep(0.05)

        # No user_response provided, but validation is disabled
        result = json.loads(await decide("test-ur-skip", "approve"))
        assert "error" not in result
        assert result.get("checkpoint_kind") == "result_review"

        handler.set_decision(Decision(action=DecisionAction.APPROVE))
        await flow_task
        del _session_manager._sessions["test-ur-skip"]
