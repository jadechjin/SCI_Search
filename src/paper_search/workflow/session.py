"""MCP session infrastructure: checkpoint handler and session management."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from paper_search.config import AppConfig, load_config
from paper_search.mcp_views import format_checkpoint_question, serialize_checkpoint_payload
from paper_search.models import PaperCollection
from paper_search.workflow.checkpoints import (
    Checkpoint,
    CheckpointKind,
    Decision,
)
from paper_search.workflow.engine import SearchWorkflow

logger = logging.getLogger(__name__)

TRIVIAL_RESPONSES = frozenset({
    "", "approve", "ok", "yes", "y", "proceed", "continue",
    "确认", "批准", "同意", "好", "是",
})


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
    require_user_response: bool = True


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
            require_user_response=cfg.require_user_response,
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
            state["checkpoint_payload"] = serialize_checkpoint_payload(ckpt)
            state["user_action_required"] = True
            state["user_question"] = format_checkpoint_question(ckpt)
            state["user_options"] = ["approve", "edit", "reject"]
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
