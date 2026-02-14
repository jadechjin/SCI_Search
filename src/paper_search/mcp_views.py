"""Checkpoint serialization and formatting for MCP responses."""

from __future__ import annotations

from typing import Any

from paper_search.models import Paper
from paper_search.workflow.checkpoints import (
    Checkpoint,
    CheckpointKind,
    ResultPayload,
    StrategyPayload,
)


def _score_distribution(papers: list[Paper]) -> dict[str, int]:
    high = sum(1 for p in papers if p.relevance_score >= 0.7)
    medium = sum(1 for p in papers if 0.3 <= p.relevance_score < 0.7)
    low = sum(1 for p in papers if p.relevance_score < 0.3)
    return {"high": high, "medium": medium, "low": low}


def serialize_checkpoint_payload(
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
        papers_summary = [
            {
                "id": p.id,
                "doi": p.doi,
                "title": p.title,
                "authors": [a.name for a in p.authors],
                "year": p.year,
                "venue": p.venue,
                "relevance_score": p.relevance_score,
                "relevance_reason": p.relevance_reason,
                "tags": [t.value for t in p.tags],
            }
            for p in all_papers
        ]
        return {
            "papers": papers_summary,
            "total_papers": len(all_papers),
            "truncated": False,
            "score_distribution": _score_distribution(all_papers),
            "facets": payload.collection.facets.model_dump(mode="json"),
            "accumulated_count": len(payload.accumulated_papers),
        }

    return {"_warning": "unsupported checkpoint kind", "raw_kind": kind.value}


def format_checkpoint_question(checkpoint: Checkpoint) -> str:
    """Format checkpoint payload as a human-readable question."""
    kind = checkpoint.kind
    payload = checkpoint.payload

    if kind == CheckpointKind.STRATEGY_CONFIRMATION:
        assert isinstance(payload, StrategyPayload)
        queries_text = "\n".join(
            f"  {i + 1}. {q.boolean_query}"
            for i, q in enumerate(payload.strategy.queries)
        )
        return (
            f"## Search Strategy Review\n\n"
            f"**Topic:** {payload.intent.topic}\n"
            f"**Concepts:** {', '.join(payload.intent.concepts)}\n"
            f"**Intent:** {payload.intent.intent_type.value}\n\n"
            f"**Proposed queries:**\n{queries_text}\n\n"
            f"**Sources:** {', '.join(payload.strategy.sources)}\n\n"
            f"Please choose an action:\n"
            f"1. **Approve** - proceed with searching\n"
            f"2. **Reject** - generate new queries with your feedback\n"
        )

    if kind == CheckpointKind.RESULT_REVIEW:
        assert isinstance(payload, ResultPayload)
        papers = payload.collection.papers
        n = len(papers)
        top_papers = papers[:15]
        lines: list[str] = []
        for i, p in enumerate(top_papers, 1):
            year_s = str(p.year) if p.year else "N/A"
            doi_s = p.doi or "N/A"
            venue_s = p.venue or "N/A"
            tags_s = ", ".join(t.value for t in p.tags) if p.tags else ""
            reason_s = p.relevance_reason or ""
            line = (
                f"  {i}. **[{p.relevance_score:.2f}]** {p.title}\n"
                f"     DOI: {doi_s} | Year: {year_s} | Venue: {venue_s}"
            )
            if tags_s:
                line += f" | Tags: {tags_s}"
            if reason_s:
                line += f"\n     Reason: {reason_s}"
            lines.append(line)
        papers_text = "\n".join(lines)

        dist = _score_distribution(papers)
        dist_text = (
            f"\n**Score distribution:** "
            f"High (>=0.7): {dist['high']}, "
            f"Medium (0.3-0.7): {dist['medium']}, "
            f"Low (<0.3): {dist['low']}"
        )

        facets = payload.collection.facets
        facets_parts: list[str] = []
        if facets.by_venue:
            venue_items = ", ".join(f"{k}: {v}" for k, v in facets.by_venue.items())
            facets_parts.append(f"**Venues:** {venue_items}")
        if facets.top_authors:
            facets_parts.append(
                f"**Top authors:** {', '.join(facets.top_authors[:10])}"
            )
        if facets.key_themes:
            facets_parts.append(
                f"**Key themes:** {', '.join(facets.key_themes)}"
            )
        facets_text = "\n".join(facets_parts)

        remaining = n - len(top_papers)
        more_text = f"\n... and {remaining} more papers\n" if remaining > 0 else ""

        full_lines = [
            f"  {i}. [{p.relevance_score:.2f}] {p.title} | DOI: {p.doi or '-'}"
            for i, p in enumerate(papers, 1)
        ]
        full_list_text = (
            "\n**Complete paper list:**\n" + "\n".join(full_lines)
        )

        return (
            f"## Search Results Review\n\n"
            f"Found **{n} papers** (showing top {len(top_papers)} in detail):\n\n"
            f"{papers_text}\n{more_text}\n"
            f"{dist_text}\n\n"
            f"{facets_text}\n\n"
            f"{full_list_text}\n\n"
            f"Please choose an action:\n"
            f"1. **Approve** - accept results and finish\n"
            f"2. **Reject** - search again with your feedback\n"
        )

    return f"Checkpoint ready: {kind.value}"
