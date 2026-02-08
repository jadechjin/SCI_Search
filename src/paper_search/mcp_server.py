"""MCP server for paper-search workflow.

Exposes the paper search pipeline as MCP tools for LLM agent integration.
Requires the `mcp` optional dependency: pip install paper-search[mcp]
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from paper_search.config import AppConfig, load_config
from paper_search.export import export_bibtex, export_json, export_markdown
from paper_search.models import PaperCollection
from paper_search.workflow.checkpoints import (
    Checkpoint,
    CheckpointKind,
    Decision,
    DecisionAction,
    ResultPayload,
    StrategyPayload,
)
from paper_search.workflow.engine import SearchWorkflow

logger = logging.getLogger(__name__)

_RESULT_PAYLOAD_MAX_PAPERS = 30


# ---------------------------------------------------------------------------
# Session infrastructure
# ---------------------------------------------------------------------------


def _serialize_checkpoint_payload(
    checkpoint: Checkpoint,
) -> dict[str, Any]:
    """Serialize checkpoint payload for MCP client consumption."""
    kind = checkpoint.kind
    payload = checkpoint.payload

    if kind == CheckpointKind.STRATEGY_CONFIRMATION:
        if not isinstance(payload, StrategyPayload):
            raise TypeError(
                f"Expected StrategyPayload for {kind.value}, "
                f"got {type(payload).__name__}"
            )
        return {
            "intent": {
                "topic": payload.intent.topic,
                "concepts": payload.intent.concepts,
                "intent_type": payload.intent.intent_type.value,
                "constraints": payload.intent.constraints.model_dump(
                    exclude_none=True, mode="json"
                ),
            },
            "strategy": {
                "queries": [
                    {
                        "keywords": q.keywords,
                        "boolean_query": q.boolean_query,
                    }
                    for q in payload.strategy.queries
                ],
                "sources": payload.strategy.sources,
                "filters": payload.strategy.filters.model_dump(
                    exclude_none=True, mode="json"
                ),
            },
        }

    if kind == CheckpointKind.RESULT_REVIEW:
        if not isinstance(payload, ResultPayload):
            raise TypeError(
                f"Expected ResultPayload for {kind.value}, "
                f"got {type(payload).__name__}"
            )
        all_papers = payload.collection.papers
        truncated = len(all_papers) > _RESULT_PAYLOAD_MAX_PAPERS
        shown = all_papers[:_RESULT_PAYLOAD_MAX_PAPERS]
        papers_summary = [
            {
                "id": p.id,
                "doi": p.doi,
                "title": p.title,
                "authors": [a.name for a in p.authors],
                "year": p.year,
                "venue": p.venue,
                "relevance_score": p.relevance_score,
                "tags": [t.value for t in p.tags],
            }
            for p in shown
        ]
        return {
            "papers": papers_summary,
            "total_papers": len(all_papers),
            "truncated": truncated,
            "facets": payload.collection.facets.model_dump(mode="json"),
            "accumulated_count": len(payload.accumulated_papers),
        }

    return {"_warning": "unsupported checkpoint kind", "raw_kind": kind.value}


class MCPCheckpointHandler:
    """CheckpointHandler that pauses workflow at checkpoints.

    Uses asyncio.Event pairs to synchronize with external decide() calls.
    """

    def __init__(self) -> None:
        self._checkpoint_ready = asyncio.Event()
        self._decision_ready = asyncio.Event()
        self._current_checkpoint: Checkpoint | None = None
        self._decision: Decision | None = None

    async def handle(self, checkpoint: Checkpoint) -> Decision:
        """Block until an external caller provides a Decision."""
        self._current_checkpoint = checkpoint
        self._decision_ready.clear()
        self._checkpoint_ready.set()
        await self._decision_ready.wait()
        self._checkpoint_ready.clear()
        assert self._decision is not None
        return self._decision

    def set_decision(self, decision: Decision) -> None:
        """Unblock handle() by providing a Decision."""
        self._decision = decision
        self._decision_ready.set()

    @property
    def current_checkpoint(self) -> Checkpoint | None:
        return self._current_checkpoint

    @property
    def has_pending_checkpoint(self) -> bool:
        return self._checkpoint_ready.is_set()

    def checkpoint_signature(self) -> str | None:
        """Return a stable signature for the currently pending checkpoint."""
        if not self.has_pending_checkpoint or self._current_checkpoint is None:
            return None
        ckpt = self._current_checkpoint
        return f"{ckpt.run_id}:{ckpt.iteration}:{ckpt.kind.value}"

    async def wait_for_checkpoint(self, timeout: float = 60.0) -> bool:
        """Wait until a checkpoint is ready or timeout."""
        try:
            await asyncio.wait_for(self._checkpoint_ready.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False


@dataclass
class WorkflowSession:
    session_id: str
    query: str
    handler: MCPCheckpointHandler
    task: asyncio.Task[Any] | None = None
    result: PaperCollection | None = None
    error: str | None = None
    is_complete: bool = False
    phase: str = "created"
    phase_details: dict[str, Any] = field(default_factory=dict)
    phase_updated_at: float = field(default_factory=time.time)
    started_at: float = field(default_factory=time.time)
    decide_wait_timeout_s: float = 15.0
    poll_interval_s: float = 0.05


class SessionManager:
    """Manages workflow sessions for MCP tool interactions."""

    def __init__(self) -> None:
        self._sessions: dict[str, WorkflowSession] = {}

    def create(self, query: str, config: AppConfig | None = None) -> str:
        """Create a new workflow session and start it in the background."""
        session_id = str(uuid.uuid4())
        handler = MCPCheckpointHandler()
        cfg = config or load_config()

        session = WorkflowSession(
            session_id=session_id,
            query=query,
            handler=handler,
            decide_wait_timeout_s=max(0.1, cfg.mcp_decide_wait_timeout_s),
            poll_interval_s=max(0.01, cfg.mcp_poll_interval_s),
        )
        self._update_progress(session, "starting", {})
        session.task = asyncio.create_task(self._run_workflow(session, cfg))
        self._sessions[session_id] = session
        return session_id

    def get(self, session_id: str) -> WorkflowSession | None:
        return self._sessions.get(session_id)

    async def wait_for_checkpoint_or_complete(
        self, session_id: str, timeout: float = 120.0
    ) -> dict[str, Any]:
        """Wait until the session hits a checkpoint or completes."""
        session = self._sessions.get(session_id)
        if session is None:
            return {"error": "Session not found"}

        deadline = asyncio.get_event_loop().time() + timeout
        while not session.handler.has_pending_checkpoint and not session.is_complete:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return {"error": "Timeout waiting for workflow"}
            await asyncio.sleep(session.poll_interval_s)

        return self._session_state(session)

    async def wait_after_decision(
        self,
        session_id: str,
        previous_checkpoint_sig: str | None,
        timeout: float,
    ) -> dict[str, Any]:
        """Wait for next checkpoint, completion, or timeout after a decision."""
        session = self._sessions.get(session_id)
        if session is None:
            return {"error": "Session not found"}

        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            state = self._session_state(session)
            if session.is_complete:
                return state

            current_sig = session.handler.checkpoint_signature()
            if current_sig is not None and current_sig != previous_checkpoint_sig:
                return state

            if asyncio.get_event_loop().time() >= deadline:
                return state

            await asyncio.sleep(session.poll_interval_s)

    def cleanup(self, session_id: str) -> None:
        """Cancel and remove a session."""
        session = self._sessions.pop(session_id, None)
        if session and session.task and not session.task.done():
            session.task.cancel()

    def _update_progress(
        self,
        session: WorkflowSession,
        phase: str,
        details: dict[str, Any],
    ) -> None:
        session.phase = phase
        session.phase_details = dict(details)
        session.phase_updated_at = time.time()

    def _session_state(self, session: WorkflowSession) -> dict[str, Any]:
        """Build a state dict for the session."""
        state: dict[str, Any] = {
            "session_id": session.session_id,
            "query": session.query,
            "is_complete": session.is_complete,
            "has_pending_checkpoint": session.handler.has_pending_checkpoint,
            "phase": session.phase,
            "phase_details": session.phase_details,
            "phase_updated_at": session.phase_updated_at,
            "elapsed_s": round(max(0.0, time.time() - session.started_at), 3),
        }
        if session.handler.has_pending_checkpoint and session.handler.current_checkpoint:
            ckpt = session.handler.current_checkpoint
            state["checkpoint_kind"] = ckpt.kind.value
            state["checkpoint_id"] = f"{ckpt.run_id}:{ckpt.iteration}"
            state["iteration"] = ckpt.iteration
            state["checkpoint_payload"] = _serialize_checkpoint_payload(ckpt)
            if ckpt.kind == CheckpointKind.STRATEGY_CONFIRMATION:
                state["summary"] = "Strategy ready for review"
            elif ckpt.kind == CheckpointKind.RESULT_REVIEW:
                state["summary"] = "Results ready for review"
            else:
                state["summary"] = f"Checkpoint ready: {ckpt.kind.value}"
        elif not session.is_complete:
            state["summary"] = f"Workflow processing ({session.phase})"
        if session.is_complete and session.result:
            state["paper_count"] = len(session.result.papers)
        if session.error:
            state["error"] = session.error
        return state

    async def _run_workflow(
        self, session: WorkflowSession, config: AppConfig
    ) -> None:
        """Run the workflow in background, capturing result or error."""
        try:
            wf = SearchWorkflow.from_config(
                config,
                checkpoint_handler=session.handler,
                progress_reporter=lambda phase, details: self._update_progress(
                    session, phase, details
                ),
            )
            session.result = await wf.run(session.query)
        except Exception as e:
            logger.exception("Workflow error in session %s", session.session_id)
            session.error = str(e)
            self._update_progress(session, "error", {"message": str(e)})
        finally:
            session.is_complete = True
            if session.error is None:
                paper_count = len(session.result.papers) if session.result else 0
                self._update_progress(
                    session, "completed", {"paper_count": paper_count}
                )


# ---------------------------------------------------------------------------
# MCP Tools
# ---------------------------------------------------------------------------

from mcp.server.fastmcp import FastMCP  # noqa: E402

mcp = FastMCP(
    "paper-search",
    instructions=(
        "Paper search workflow with human-in-the-loop checkpoints.\n"
        "\n"
        "INTERACTION FLOW:\n"
        "1. Call search_papers(query) → returns session_id + strategy_confirmation checkpoint\n"
        "2. IMPORTANT: Present the strategy (intent + queries) to the USER for review\n"
        "3. Ask the user to approve, edit, or reject. Then call decide(session_id, action)\n"
        "4. Pipeline runs (searching → dedup → scoring → organizing) → returns result_review checkpoint\n"
        "   If the pipeline is still running, use get_session(session_id) to poll progress\n"
        "5. IMPORTANT: Present the papers list to the USER for review\n"
        "6. Ask the user to approve, edit, or reject. Then call decide(session_id, action)\n"
        "7. If approved → call export_results(session_id, format) for final output\n"
        "\n"
        "CRITICAL RULES:\n"
        "- Do NOT auto-approve checkpoints. Always present checkpoint data to the user and let them decide.\n"
        "- The checkpoints exist specifically for human review and feedback.\n"
        "- If the user rejects results, the pipeline iterates with refined queries automatically.\n"
    ),
)
_session_manager = SessionManager()


@mcp.tool()
async def search_papers(
    query: str,
    domain: str = "general",
    max_results: int = 100,
) -> str:
    """Search academic papers. Returns a session_id and the first checkpoint or results.

    Args:
        query: Natural language search query (e.g., "perovskite solar cells efficiency")
        domain: Research domain - "general" or "materials_science"
        max_results: Maximum number of results to return

    Returns JSON with session_id and a strategy_confirmation checkpoint containing:
    - intent: parsed topic, concepts, intent_type, constraints
    - strategy: generated search queries (keywords + boolean_query), sources, filters

    IMPORTANT: Present the checkpoint_payload to the user for review before calling decide().
    """
    config = load_config()
    config.domain = domain
    config.default_max_results = max_results
    session_id = _session_manager.create(query, config)
    await asyncio.sleep(0.1)  # Yield to let workflow start
    state = await _session_manager.wait_for_checkpoint_or_complete(session_id)
    state["session_id"] = session_id
    return json.dumps(state, indent=2)


@mcp.tool()
async def decide(
    session_id: str,
    action: str,
    data: dict[str, Any] | None = None,
    note: str | None = None,
) -> str:
    """Make a decision on a pending checkpoint in a paper search session.

    Args:
        session_id: Session ID from search_papers
        action: Decision action - "approve", "edit", or "reject"
        data: Optional revised data (SearchStrategy dict for strategy, UserFeedback dict for results)
        note: Optional note explaining the decision

    Actions:
    - "approve": Accept the current checkpoint (strategy or results) and continue
    - "edit": Provide revised data and continue (data must match checkpoint schema)
    - "reject": Reject and iterate with new queries (provide feedback via note or data)

    For result_review checkpoints, data can include UserFeedback fields:
    - marked_relevant: list of paper IDs the user considers relevant
    - free_text_feedback: text feedback for refining the next search iteration

    IMPORTANT: Always ask the user which action to take. Do not decide automatically.
    """
    session = _session_manager.get(session_id)
    if session is None:
        return json.dumps({"error": "Session not found"})
    if session.is_complete:
        return json.dumps({"error": "Session already complete"})
    if not session.handler.has_pending_checkpoint:
        return json.dumps({"error": "No pending checkpoint"})

    valid_actions = {"approve", "edit", "reject"}
    if action not in valid_actions:
        return json.dumps(
            {"error": f"Invalid action '{action}'. Must be one of: {valid_actions}"}
        )

    previous_sig = session.handler.checkpoint_signature()
    decision = Decision(
        action=DecisionAction(action),
        revised_data=data,
        note=note,
    )
    session.handler.set_decision(decision)
    state = await _session_manager.wait_after_decision(
        session_id=session_id,
        previous_checkpoint_sig=previous_sig,
        timeout=session.decide_wait_timeout_s,
    )
    return json.dumps(state, indent=2)


@mcp.tool()
async def export_results(
    session_id: str,
    format: str = "markdown",
) -> str:
    """Export search results in the specified format.

    Args:
        session_id: Session ID from a completed search
        format: Output format - "json", "bibtex", or "markdown"
    """
    session = _session_manager.get(session_id)
    if session is None:
        return json.dumps({"error": "Session not found"})
    if not session.is_complete:
        return json.dumps({"error": "Session not complete yet"})
    if session.result is None:
        return json.dumps({"error": session.error or "No results available"})

    exporters = {
        "json": export_json,
        "bibtex": export_bibtex,
        "markdown": export_markdown,
    }
    exporter = exporters.get(format)
    if exporter is None:
        return json.dumps(
            {"error": f"Unknown format '{format}'. Must be one of: {list(exporters)}"}
        )
    return exporter(session.result)


@mcp.tool()
async def get_session(session_id: str) -> str:
    """Get current state of a search session.

    Use this to poll progress when the pipeline is running (searching, scoring, etc.).
    Returns phase, phase_details, elapsed_s, and checkpoint data if a checkpoint is pending.

    Args:
        session_id: Session ID to inspect
    """
    session = _session_manager.get(session_id)
    if session is None:
        return json.dumps({"error": "Session not found"})
    return json.dumps(_session_manager._session_state(session), indent=2)


def main() -> None:
    """Entry point for the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
