"""Search workflow orchestrator."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

from pydantic import ValidationError

from paper_search.config import AppConfig
from paper_search.models import (
    Paper,
    PaperCollection,
    QueryBuilderInput,
    SearchMetadata,
    SearchStrategy,
    UserFeedback,
)
from paper_search.skills.deduplicator import Deduplicator
from paper_search.skills.intent_parser import IntentParser
from paper_search.skills.query_builder import QueryBuilder
from paper_search.skills.relevance_scorer import RelevanceScorer
from paper_search.skills.result_organizer import ResultOrganizer
from paper_search.skills.searcher import Searcher
from paper_search.workflow.checkpoints import (
    Checkpoint,
    CheckpointHandler,
    CheckpointKind,
    Decision,
    DecisionAction,
    ResultPayload,
    StrategyPayload,
)
from paper_search.workflow.state import WorkflowState

logger = logging.getLogger(__name__)

ProgressReporter = Callable[[str, dict[str, Any]], None]


class SearchWorkflow:
    """Orchestrate the full paper search workflow.

    Coordinates all skills in sequence:
    intent_parser -> query_builder -> searcher -> deduplicator
    -> relevance_scorer -> result_organizer

    Supports human-in-the-loop checkpoints and iterative refinement.
    """

    def __init__(
        self,
        intent_parser: IntentParser,
        query_builder: QueryBuilder,
        searcher: Searcher,
        deduplicator: Deduplicator,
        relevance_scorer: RelevanceScorer,
        result_organizer: ResultOrganizer,
        checkpoint_handler: CheckpointHandler | None = None,
        max_iterations: int = 5,
        enable_strategy_checkpoint: bool = True,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._intent_parser = intent_parser
        self._query_builder = query_builder
        self._searcher = searcher
        self._deduplicator = deduplicator
        self._relevance_scorer = relevance_scorer
        self._result_organizer = result_organizer
        self._checkpoint_handler = checkpoint_handler
        self._max_iterations = max_iterations
        self._enable_strategy_checkpoint = enable_strategy_checkpoint
        self._progress_reporter = progress_reporter

    def _report_progress(self, phase: str, **details: Any) -> None:
        if not self._progress_reporter:
            return
        try:
            self._progress_reporter(phase, details)
        except Exception:  # pragma: no cover
            logger.exception("Progress reporter failed")

    async def run(self, user_input: str) -> PaperCollection:
        run_id = str(uuid.uuid4())
        state = WorkflowState()

        self._report_progress("intent_parsing")
        t0 = time.perf_counter()
        intent = await self._intent_parser.parse(user_input)
        logger.info("Intent parsing completed in %.1fs", time.perf_counter() - t0)

        last_collection: PaperCollection | None = None

        while state.current_iteration < self._max_iterations:
            self._report_progress(
                "query_building",
                iteration=state.current_iteration,
            )
            qb_input = QueryBuilderInput(
                intent=intent,
                previous_strategies=state.previous_strategies,
                user_feedback=state.latest_feedback,
            )
            t0 = time.perf_counter()
            strategy = await self._query_builder.build(qb_input)
            logger.info("Query building completed in %.1fs", time.perf_counter() - t0)

            if self._enable_strategy_checkpoint and self._checkpoint_handler:
                self._report_progress(
                    "waiting_checkpoint",
                    checkpoint_kind=CheckpointKind.STRATEGY_CONFIRMATION.value,
                    iteration=state.current_iteration,
                )
                ckpt = Checkpoint(
                    kind=CheckpointKind.STRATEGY_CONFIRMATION,
                    payload=StrategyPayload(
                        intent=intent,
                        strategy=strategy,
                        iteration=state.current_iteration,
                    ),
                    run_id=run_id,
                    iteration=state.current_iteration,
                )
                decision = await self._checkpoint_handler.handle(ckpt)

                if decision.action == DecisionAction.EDIT:
                    strategy = SearchStrategy.model_validate(decision.revised_data)
                elif decision.action == DecisionAction.REJECT:
                    feedback = _coerce_feedback(decision)
                    state.record_iteration(strategy, 0, feedback)
                    self._report_progress(
                        "iterating", next_iteration=state.current_iteration
                    )
                    continue

            self._report_progress(
                "searching",
                iteration=state.current_iteration,
            )
            t0 = time.perf_counter()
            raw = await self._searcher.search(strategy)
            logger.info("Searching completed in %.1fs (%d results)", time.perf_counter() - t0, len(raw))

            self._report_progress(
                "deduplicating",
                iteration=state.current_iteration,
                raw_count=len(raw),
            )
            t0 = time.perf_counter()
            deduped = await self._deduplicator.deduplicate(raw)
            logger.info("Deduplication completed in %.1fs (%d → %d)", time.perf_counter() - t0, len(raw), len(deduped))

            self._report_progress(
                "scoring",
                iteration=state.current_iteration,
                candidate_count=len(deduped),
            )
            t0 = time.perf_counter()
            scored = await self._relevance_scorer.score(deduped, intent)
            logger.info("Scoring completed in %.1fs (%d papers)", time.perf_counter() - t0, len(scored))

            self._report_progress(
                "organizing",
                iteration=state.current_iteration,
                scored_count=len(scored),
            )
            t0 = time.perf_counter()
            collection = await self._result_organizer.organize(
                scored, strategy, user_input
            )
            logger.info("Organizing completed in %.1fs", time.perf_counter() - t0)
            last_collection = collection

            if self._checkpoint_handler:
                self._report_progress(
                    "waiting_checkpoint",
                    checkpoint_kind=CheckpointKind.RESULT_REVIEW.value,
                    iteration=state.current_iteration,
                    paper_count=len(collection.papers),
                )
                ckpt = Checkpoint(
                    kind=CheckpointKind.RESULT_REVIEW,
                    payload=ResultPayload(
                        collection=collection,
                        accumulated_papers=list(state.accumulated_papers),
                        iteration=state.current_iteration,
                    ),
                    run_id=run_id,
                    iteration=state.current_iteration,
                )
                decision = await self._checkpoint_handler.handle(ckpt)
            else:
                decision = Decision(action=DecisionAction.APPROVE)

            if decision.action == DecisionAction.APPROVE:
                state.record_iteration(strategy, len(collection.papers))
                state.is_complete = True
                self._report_progress(
                    "completed",
                    iteration=state.current_iteration,
                    paper_count=len(collection.papers),
                )
                return _merge_accumulated(collection, state.accumulated_papers)

            feedback = _coerce_feedback(decision)
            _accumulate_relevant(state, collection, feedback)
            state.record_iteration(strategy, len(collection.papers), feedback)
            self._report_progress("iterating", next_iteration=state.current_iteration)

        state.is_complete = True
        self._report_progress("completed", reason="max_iterations_reached")
        if last_collection is not None:
            return _merge_accumulated(last_collection, state.accumulated_papers)
        return PaperCollection(
            metadata=SearchMetadata(
                query=user_input,
                search_strategy=SearchStrategy(queries=[], sources=[]),
                total_found=0,
            ),
            papers=[],
        )

    @classmethod
    def from_config(
        cls,
        config: AppConfig,
        checkpoint_handler: CheckpointHandler | None = None,
        max_iterations: int = 5,
        enable_strategy_checkpoint: bool = True,
        progress_reporter: ProgressReporter | None = None,
    ) -> SearchWorkflow:
        from paper_search.llm import create_provider
        from paper_search.sources.base import SearchSource

        llm = create_provider(config.llm)

        sources: list[SearchSource] = []
        for name, src_cfg in config.sources.items():
            if not src_cfg.enabled:
                continue
            if name == "serpapi_scholar":
                from paper_search.sources.serpapi_scholar import (
                    SerpAPIScholarSource,
                )

                sources.append(
                    SerpAPIScholarSource(
                        api_key=src_cfg.api_key,
                        rate_limit_rps=src_cfg.rate_limit,
                    )
                )

        available = [s.source_name for s in sources]

        return cls(
            intent_parser=IntentParser(llm, domain=config.domain),
            query_builder=QueryBuilder(
                llm, domain=config.domain, available_sources=available
            ),
            searcher=Searcher(sources),
            deduplicator=Deduplicator(
                llm=llm,
                enable_llm_pass=config.dedup_enable_llm_pass,
                llm_max_candidates=config.dedup_llm_max_candidates,
            ),
            relevance_scorer=RelevanceScorer(
                llm,
                batch_size=config.relevance_batch_size,
                max_concurrency=config.relevance_max_concurrency,
            ),
            result_organizer=ResultOrganizer(),
            checkpoint_handler=checkpoint_handler,
            max_iterations=max_iterations,
            enable_strategy_checkpoint=enable_strategy_checkpoint,
            progress_reporter=progress_reporter,
        )


def _coerce_feedback(decision: Decision) -> UserFeedback:
    """Convert Decision to UserFeedback for iteration."""
    if isinstance(decision.revised_data, dict):
        try:
            return UserFeedback.model_validate(decision.revised_data)
        except ValidationError:
            pass
    return UserFeedback(free_text_feedback=decision.note or "")


def _accumulate_relevant(
    state: WorkflowState,
    collection: PaperCollection,
    feedback: UserFeedback,
) -> None:
    """Add user-marked-relevant papers to accumulated_papers."""
    relevant_ids = set(feedback.marked_relevant)
    if not relevant_ids:
        return
    matching = [p for p in collection.papers if p.id in relevant_ids]
    state.add_accumulated(matching)


def _merge_accumulated(
    collection: PaperCollection, accumulated: list[Paper]
) -> PaperCollection:
    """Merge accumulated papers into collection, dedup by ID."""
    if not accumulated:
        return collection
    current_ids = {p.id for p in collection.papers}
    extras = [p for p in accumulated if p.id not in current_ids]
    if not extras:
        return collection
    merged = list(collection.papers) + extras
    return collection.model_copy(update={"papers": merged})
