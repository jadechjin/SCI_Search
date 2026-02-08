"""Relevance scorer skill: RawPaper[] -> ScoredPaper[] (batch LLM scoring)."""

from __future__ import annotations

import asyncio
import logging
import time

from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError
from paper_search.models import ParsedIntent, PaperTag, RawPaper, ScoredPaper
from paper_search.prompts.relevance_scoring import RELEVANCE_SCORING_SYSTEM

logger = logging.getLogger(__name__)

_MAX_TITLE_LEN = 200
_MAX_SNIPPET_LEN = 500


class RelevanceScorer:
    """Score papers for relevance using LLM in batches."""

    def __init__(
        self,
        llm: LLMProvider,
        batch_size: int = 10,
        max_concurrency: int = 5,
    ) -> None:
        self._llm = llm
        self._batch_size = batch_size
        self._max_concurrency = max(1, max_concurrency)

    async def score(
        self, papers: list[RawPaper], intent: ParsedIntent
    ) -> list[ScoredPaper]:
        if not papers:
            return []

        batches = self._make_batches(papers)
        n_batches = len(batches)
        if n_batches <= 1 or self._max_concurrency == 1:
            all_scored: list[ScoredPaper] = []
            for batch in batches:
                scored = await self._score_batch(batch, intent)
                all_scored.extend(scored)
            return all_scored

        logger.info(
            "Scoring %d papers in %d batches (concurrency=%d)",
            len(papers), n_batches, self._max_concurrency,
        )

        semaphore = asyncio.Semaphore(self._max_concurrency)
        results: list[list[ScoredPaper] | None] = [None] * len(batches)

        async def _score_index(idx: int, batch: list[RawPaper]) -> None:
            async with semaphore:
                try:
                    results[idx] = await self._score_batch(batch, intent)
                except Exception as exc:  # pragma: no cover
                    logger.warning("Scoring batch crashed, using defaults: %s", exc)
                    results[idx] = [self._default_score(p) for p in batch]

        await asyncio.gather(
            *(_score_index(i, batch) for i, batch in enumerate(batches))
        )

        all_scored: list[ScoredPaper] = []
        for i, batch in enumerate(batches):
            all_scored.extend(results[i] or [self._default_score(p) for p in batch])
        return all_scored

    def _make_batches(self, papers: list[RawPaper]) -> list[list[RawPaper]]:
        return [
            papers[i : i + self._batch_size]
            for i in range(0, len(papers), self._batch_size)
        ]

    async def _score_batch(
        self, batch: list[RawPaper], intent: ParsedIntent
    ) -> list[ScoredPaper]:
        user_msg = self._format_batch(batch, intent)
        t0 = time.perf_counter()
        try:
            result = await self._llm.complete_json(
                RELEVANCE_SCORING_SYSTEM, user_msg
            )
            elapsed = time.perf_counter() - t0
            logger.info("Scored batch of %d papers in %.1fs", len(batch), elapsed)
            return self._parse_scores(batch, result)
        except LLMError as exc:
            elapsed = time.perf_counter() - t0
            logger.warning("Scoring batch failed after %.1fs, using defaults: %s", elapsed, exc)
            return [self._default_score(p) for p in batch]

    def _format_batch(
        self, batch: list[RawPaper], intent: ParsedIntent
    ) -> str:
        lines = [
            f"Research topic: {intent.topic}",
            f"Key concepts: {', '.join(intent.concepts)}",
            "",
            "Papers to score:",
        ]
        for p in batch:
            title = p.title[:_MAX_TITLE_LEN]
            snippet = (p.snippet or "")[:_MAX_SNIPPET_LEN]
            lines.append(f"- ID: {p.id}")
            lines.append(f"  Title: {title}")
            if snippet:
                lines.append(f"  Snippet: {snippet}")
            if p.year:
                lines.append(f"  Year: {p.year}")
            if p.venue:
                lines.append(f"  Venue: {p.venue}")
        return "\n".join(lines)

    def _parse_scores(
        self, batch: list[RawPaper], result: dict
    ) -> list[ScoredPaper]:
        paper_map = {p.id: p for p in batch}
        scored_map: dict[str, ScoredPaper] = {}

        for item in result.get("results", []):
            pid = item.get("paper_id", "")
            if pid not in paper_map or pid in scored_map:
                continue

            score = item.get("relevance_score", 0.0)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 0.0
            score = max(0.0, min(1.0, score))

            reason = str(item.get("relevance_reason", ""))

            # Filter to valid tags only
            raw_tags = item.get("tags", [])
            valid_tags = []
            for tag in raw_tags:
                try:
                    valid_tags.append(PaperTag(tag))
                except ValueError:
                    continue

            scored_map[pid] = ScoredPaper(
                paper=paper_map[pid],
                relevance_score=score,
                relevance_reason=reason,
                tags=valid_tags,
            )

        # Fill missing papers with defaults, maintain batch order
        result_list: list[ScoredPaper] = []
        for p in batch:
            if p.id in scored_map:
                result_list.append(scored_map[p.id])
            else:
                result_list.append(self._default_score(p))
        return result_list

    @staticmethod
    def _default_score(paper: RawPaper) -> ScoredPaper:
        return ScoredPaper(
            paper=paper,
            relevance_score=0.0,
            relevance_reason="Scoring unavailable",
            tags=[],
        )
