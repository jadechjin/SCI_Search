"""Deduplicator skill: RawPaper[] -> RawPaper[] (deduplicated)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from paper_search.llm.base import LLMProvider
from paper_search.llm.exceptions import LLMError
from paper_search.models import RawPaper
from paper_search.prompts.dedup import DEDUP_SYSTEM

logger = logging.getLogger(__name__)

_PUNCT_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


class Deduplicator:
    """Remove duplicate papers using algorithm + optional LLM matching."""

    def __init__(
        self,
        llm: LLMProvider | None = None,
        *,
        enable_llm_pass: bool = True,
        llm_max_candidates: int = 60,
    ) -> None:
        self._llm = llm
        self._enable_llm_pass = enable_llm_pass
        self._llm_max_candidates = max(2, llm_max_candidates)

    async def deduplicate(self, papers: list[RawPaper]) -> list[RawPaper]:
        if len(papers) <= 1:
            return list(papers)

        # Pass 1: Algorithm-based exact matching
        groups, ungrouped = self._algorithm_pass(papers)

        # Pass 2: LLM-based semantic matching
        if (
            self._llm
            and self._enable_llm_pass
            and 1 < len(ungrouped) <= self._llm_max_candidates
        ):
            llm_groups, remaining = await self._llm_pass(ungrouped)
            groups.extend(llm_groups)
            ungrouped = remaining
        elif (
            self._llm
            and self._enable_llm_pass
            and len(ungrouped) > self._llm_max_candidates
        ):
            logger.info(
                "Skipping LLM dedup pass for %s candidates (limit=%s)",
                len(ungrouped),
                self._llm_max_candidates,
            )

        # Merge each group + add ungrouped as singles
        result = [self._merge_group(g) for g in groups]
        result.extend(ungrouped)
        return result

    def _algorithm_pass(
        self, papers: list[RawPaper]
    ) -> tuple[list[list[RawPaper]], list[RawPaper]]:
        """Group papers by exact matches. Returns (groups, ungrouped)."""
        # Union-find via dict: paper.id -> canonical_id
        parent: dict[str, str] = {p.id: p.id for p in papers}
        paper_map: dict[str, RawPaper] = {p.id: p for p in papers}

        def find(pid: str) -> str:
            while parent[pid] != pid:
                parent[pid] = parent[parent[pid]]
                pid = parent[pid]
            return pid

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        # Pass 1: Group by DOI (case-insensitive)
        doi_map: dict[str, str] = {}
        for p in papers:
            if p.doi:
                key = p.doi.lower().strip()
                if key in doi_map:
                    union(p.id, doi_map[key])
                else:
                    doi_map[key] = p.id

        # Pass 2: Group by source result_id
        rid_map: dict[str, str] = {}
        for p in papers:
            rid = p.raw_data.get("result_id")
            if rid:
                key = str(rid)
                if key in rid_map:
                    union(p.id, rid_map[key])
                else:
                    rid_map[key] = p.id

        # Pass 3: Group by full_text_url
        url_map: dict[str, str] = {}
        for p in papers:
            if p.full_text_url:
                key = p.full_text_url.strip()
                if key in url_map:
                    union(p.id, url_map[key])
                else:
                    url_map[key] = p.id

        # Pass 4: Group by normalized title
        title_map: dict[str, str] = {}
        for p in papers:
            key = self._normalize_title(p.title)
            if key in title_map:
                union(p.id, title_map[key])
            else:
                title_map[key] = p.id

        # Collect groups
        group_dict: dict[str, list[RawPaper]] = {}
        for p in papers:
            root = find(p.id)
            group_dict.setdefault(root, []).append(p)

        groups = [g for g in group_dict.values() if len(g) > 1]
        ungrouped = [g[0] for g in group_dict.values() if len(g) == 1]
        return groups, ungrouped

    async def _llm_pass(
        self, papers: list[RawPaper]
    ) -> tuple[list[list[RawPaper]], list[RawPaper]]:
        """Use LLM to identify semantic duplicates. Returns (groups, remaining)."""
        paper_map = {p.id: p for p in papers}
        entries = [
            {"id": p.id, "title": p.title, "year": p.year}
            for p in papers
        ]
        user_msg = json.dumps(entries, ensure_ascii=False)

        try:
            result = await self._llm.complete_json(DEDUP_SYSTEM, user_msg)
        except LLMError as exc:
            logger.warning("Dedup LLM failed, skipping LLM pass: %s", exc)
            return [], list(papers)

        groups: list[list[RawPaper]] = []
        seen_ids: set[str] = set()

        # Parse groups from LLM response
        for group_ids in result.get("groups", []):
            if not isinstance(group_ids, list) or len(group_ids) < 2:
                continue
            group_papers = []
            for pid in group_ids:
                if pid in paper_map and pid not in seen_ids:
                    group_papers.append(paper_map[pid])
                    seen_ids.add(pid)
            if len(group_papers) > 1:
                groups.append(group_papers)

        # Remaining ungrouped
        remaining = [p for p in papers if p.id not in seen_ids]
        return groups, remaining

    @staticmethod
    def _normalize_title(title: str) -> str:
        """Normalize title for exact comparison."""
        t = title.lower().strip()
        t = _PUNCT_RE.sub("", t)
        t = _SPACE_RE.sub(" ", t).strip()
        return t

    @staticmethod
    def _merge_group(papers: list[RawPaper]) -> RawPaper:
        """Merge a group of duplicate papers, keeping the richest record."""
        if len(papers) == 1:
            return papers[0]

        def richness(p: RawPaper) -> tuple[int, int]:
            score = sum(
                1
                for v in (p.doi, p.snippet, p.abstract, p.year, p.venue, p.full_text_url)
                if v is not None
            )
            return (score, p.citation_count)

        # Sort by richness descending, pick best
        ranked = sorted(papers, key=richness, reverse=True)
        best = ranked[0].model_copy(deep=True)

        # Fill missing fields from other papers
        for other in ranked[1:]:
            if best.doi is None and other.doi is not None:
                best.doi = other.doi
            if best.snippet is None and other.snippet is not None:
                best.snippet = other.snippet
            if best.abstract is None and other.abstract is not None:
                best.abstract = other.abstract
            if best.year is None and other.year is not None:
                best.year = other.year
            if best.venue is None and other.venue is not None:
                best.venue = other.venue
            if best.full_text_url is None and other.full_text_url is not None:
                best.full_text_url = other.full_text_url
            best.citation_count = max(best.citation_count, other.citation_count)

        return best
