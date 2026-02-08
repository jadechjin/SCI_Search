"""Checkpoint models for human-in-the-loop workflow control."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from paper_search.models import (
    Paper,
    PaperCollection,
    ParsedIntent,
    SearchStrategy,
)


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


class ResultPayload(BaseModel):
    collection: PaperCollection
    accumulated_papers: list[Paper] = Field(default_factory=list)


class Checkpoint(BaseModel):
    kind: CheckpointKind
    payload: StrategyPayload | ResultPayload
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    iteration: int = 0
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


class Decision(BaseModel):
    action: DecisionAction
    revised_data: Any = None
    note: str | None = None


@runtime_checkable
class CheckpointHandler(Protocol):
    async def handle(self, checkpoint: Checkpoint) -> Decision: ...
