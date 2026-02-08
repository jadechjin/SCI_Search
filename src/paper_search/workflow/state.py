"""Workflow state management for iterative search."""

from __future__ import annotations

from pydantic import BaseModel, Field

from paper_search.models import Paper, SearchStrategy, UserFeedback


class IterationRecord(BaseModel):
    iteration: int
    strategy: SearchStrategy
    result_count: int
    feedback: UserFeedback | None = None


class WorkflowState(BaseModel):
    """Tracks state across search iterations."""

    current_iteration: int = 0
    history: list[IterationRecord] = []
    accumulated_papers: list[Paper] = []
    is_complete: bool = False

    def record_iteration(
        self,
        strategy: SearchStrategy,
        result_count: int,
        feedback: UserFeedback | None = None,
    ) -> None:
        self.history.append(
            IterationRecord(
                iteration=self.current_iteration,
                strategy=strategy,
                result_count=result_count,
                feedback=feedback,
            )
        )
        self.current_iteration += 1

    @property
    def previous_strategies(self) -> list[SearchStrategy]:
        return [r.strategy for r in self.history]

    @property
    def latest_feedback(self) -> UserFeedback | None:
        if self.history and self.history[-1].feedback:
            return self.history[-1].feedback
        return None

    def add_accumulated(self, papers: list[Paper]) -> None:
        """Add papers to accumulated list, dedup by ID."""
        existing_ids = {p.id for p in self.accumulated_papers}
        for p in papers:
            if p.id not in existing_ids:
                self.accumulated_papers.append(p)
                existing_ids.add(p.id)
