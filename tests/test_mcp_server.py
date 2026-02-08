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
from paper_search.mcp_server import (
    MCPCheckpointHandler,
    SessionManager,
    WorkflowSession,
    _serialize_checkpoint_payload,
    _RESULT_PAYLOAD_MAX_PAPERS,
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
            iteration=0,
        ),
    )


def _make_result_checkpoint() -> Checkpoint:
    return Checkpoint(
        kind=CheckpointKind.RESULT_REVIEW,
        payload=ResultPayload(
            collection=_MOCK_COLLECTION,
            iteration=0,
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
        with patch("paper_search.mcp_server.SearchWorkflow") as mock_wf_cls:
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
        with patch("paper_search.mcp_server.SearchWorkflow") as mock_wf_cls:
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
        with patch("paper_search.mcp_server.SearchWorkflow") as mock_wf_cls:
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
            payload=ResultPayload(collection=collection, iteration=0),
        )
        result = _serialize_checkpoint_payload(ckpt)

        assert len(result["papers"]) == 1
        assert result["papers"][0]["doi"] == "10.1234/test"
        assert result["papers"][0]["title"] == "Test Paper"
        assert result["papers"][0]["authors"] == ["Alice"]
        assert result["papers"][0]["year"] == 2024
        assert result["total_papers"] == 1
        assert result["truncated"] is False

    def test_result_payload_truncation(self):
        papers = [
            Paper(
                id=f"p{i}",
                title=f"Paper {i}",
                authors=[],
                source="serpapi",
                relevance_score=0.5,
            )
            for i in range(_RESULT_PAYLOAD_MAX_PAPERS + 10)
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
            payload=ResultPayload(collection=collection, iteration=0),
        )
        result = _serialize_checkpoint_payload(ckpt)

        assert len(result["papers"]) == _RESULT_PAYLOAD_MAX_PAPERS
        assert result["total_papers"] == _RESULT_PAYLOAD_MAX_PAPERS + 10
        assert result["truncated"] is True

    def test_strategy_payload_type_mismatch_raises(self):
        ckpt = Checkpoint(
            kind=CheckpointKind.STRATEGY_CONFIRMATION,
            payload=ResultPayload(collection=_MOCK_COLLECTION, iteration=0),
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
