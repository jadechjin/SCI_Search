"""MCP server for paper-search workflow.

Exposes the paper search pipeline as MCP tools for LLM agent integration.
Requires the `mcp` optional dependency: pip install paper-search[mcp]
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from paper_search.config import load_config
from paper_search.export import export_bibtex, export_json, export_markdown
from paper_search.workflow.checkpoints import Decision, DecisionAction
from paper_search.workflow.session import TRIVIAL_RESPONSES, SessionManager

mcp = FastMCP(
    "paper-search",
    instructions=(
        "Paper search workflow with MANDATORY human-in-the-loop checkpoints.\n"
        "\n"
        "INTERACTION FLOW:\n"
        "1. Call search_papers(query) -> returns session_id + strategy_confirmation checkpoint\n"
        "2. When the response contains 'user_action_required: true', you MUST:\n"
        "   - Use the AskUserQuestion tool (if available) to present options to the user\n"
        "   - The question should include the checkpoint summary from user_question\n"
        "   - Options should map to: approve, edit, reject\n"
        "   - If AskUserQuestion is not available, present the user_question text directly\n"
        "   - Wait for the user's explicit decision\n"
        "3. Call decide(session_id, action, user_response=<user's verbatim response>)\n"
        "   The user_response parameter is REQUIRED and must contain the user's actual input.\n"
        "4. Pipeline runs (searching -> dedup -> scoring -> organizing)\n"
        "   If still running, use get_session(session_id) to poll progress\n"
        "5. When result_review checkpoint arrives (user_action_required: true):\n"
        "   - Use the AskUserQuestion tool (if available) to present options to the user\n"
        "   - Include paper summary and facets in the question text\n"
        "   - If AskUserQuestion is not available, present the user_question text directly\n"
        "   - Wait for the user's decision\n"
        "6. Call decide(session_id, action, user_response=<user's response>)\n"
        "7. If approved -> call export_results(session_id, format) for final output\n"
        "\n"
        "CRITICAL RULES:\n"
        "- Do NOT auto-approve checkpoints. ALWAYS present checkpoint data to the user.\n"
        "- PREFER using AskUserQuestion tool over plain text for checkpoint interactions.\n"
        "- The decide() tool REQUIRES a substantive user_response parameter.\n"
        "- Trivial responses like 'ok', 'yes', 'approve' will be REJECTED by the server.\n"
        "- You must relay the user_question to the user and collect their actual response.\n"
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
    - user_action_required: true when a checkpoint needs user review
    - user_question: formatted question to present to the user
    - user_options: available actions ["approve", "edit", "reject"]

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
    user_response: str | None = None,
    data: dict[str, Any] | None = None,
    note: str | None = None,
) -> str:
    """Make a decision on a pending checkpoint in a paper search session.

    Args:
        session_id: Session ID from search_papers
        action: Decision action - "approve", "edit", or "reject"
        user_response: REQUIRED - The user's verbatim response explaining their decision.
            You MUST present the checkpoint to the user first and include their actual
            response here. Trivial responses like "ok" or "yes" will be rejected.
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

    if session.require_user_response:
        if (
            user_response is None
            or user_response.strip().lower() in TRIVIAL_RESPONSES
        ):
            return json.dumps({
                "error": (
                    "user_response is required. You MUST present the checkpoint "
                    "to the user and include their verbatim response. "
                    "Trivial responses like 'ok' or 'yes' are not accepted."
                ),
                "hint": "Show the user_question from the checkpoint and ask for their decision.",
            })

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
